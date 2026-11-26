"""The image folder in memory: every image under the root, its folder, size and pixel size.

An image is identified by its path relative to the root, with "/" separators ("rel").
Thumbnails and screen-size copies are cached in appdata under a key made of the file
name, byte size and modification time, so they survive moving a file to another folder.
"""
import hashlib
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

THUMB_SIZE = 320  # long side, px


def lowest_priority():
    """Run the calling thread at the lowest CPU priority, so Windows (or Linux) gives the CPU
    to everything else first: the browser, other programs and the images you are looking at.
    The background job then only uses CPU time that nothing else wants."""
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority(k32.GetCurrentThread(), -15)  # THREAD_PRIORITY_IDLE
        elif hasattr(os, "setpriority"):
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)  # Linux: per thread
    except Exception:
        pass


def file_key(name, size, mtime_ns):
    return hashlib.sha1(f"{name}|{size}|{mtime_ns}".encode()).hexdigest()


def read_size(path):
    """Pixel size as displayed (EXIF rotation applied). Only reads the header."""
    try:
        with Image.open(path) as im:
            w, h = im.size
            if im.getexif().get(0x0112) in (5, 6, 7, 8):
                w, h = h, w
            return w, h
    except Exception:
        return None, None


def make_thumb(path, out):
    """Write the JPEG thumbnail (JPEG encodes far faster than WebP, which used to be most of
    the work). Returns the image's displayed (w, h), or None on failure."""
    try:
        with Image.open(path) as im:
            w, h = im.size
            if im.getexif().get(0x0112) in (5, 6, 7, 8):
                w, h = h, w
            im.draft("RGB", (THUMB_SIZE, THUMB_SIZE))
            im = ImageOps.exif_transpose(im)
            if "A" in im.mode or "transparency" in im.info:  # JPEG has no transparency:
                im = im.convert("RGBA")                       # put it on the tile colour
                bg = Image.new("RGB", im.size, (14, 15, 17))
                bg.paste(im, mask=im.getchannel("A"))
                im = bg
            im = im.convert("RGB")
            im.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.BILINEAR, reducing_gap=2.0)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "JPEG", quality=82)
            os.replace(tmp, out)
        return w, h
    except Exception:
        return None


def make_display(path, out, size):
    """JPEG copy with long side = size. None for images with transparency (JPEG has none)."""
    try:
        with Image.open(path) as im:
            if "A" in im.mode or "transparency" in im.info:
                return False
            im.draft("RGB", (size, size))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size), Image.BICUBIC, reducing_gap=2.0)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "JPEG", quality=88)
            os.replace(tmp, out)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- name groups

_HASHLIKE = re.compile(r"^(?=.*\d)[0-9a-f]{8,}$")  # long hex strings: camera ids, hashes


def name_tokens(name):
    """Words of a file name that can tie images together: no numbers, no hashes."""
    stem = os.path.splitext(name)[0].lower()
    out = []
    for t in re.split(r"[^0-9a-z]+", stem):
        t = t.strip("0123456789") if not t.isdigit() else ""
        if len(t) < 2 or _HASHLIKE.match(t):
            continue
        out.append(t)
    return out


def group_key(name, words=1):
    toks = name_tokens(name)
    return " ".join(toks[:words]) if toks else ""


class Library:
    def __init__(self, cfg):
        self.cfg = cfg
        self.data_dir = Path(cfg["data_dir"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "cache.db", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS sizes (key TEXT PRIMARY KEY, w INTEGER, h INTEGER)")
        self.db_lock = threading.Lock()
        self.lock = threading.RLock()
        self.root = None
        self.files = {}     # rel -> {"rel", "name", "folder", "size", "mtime", "key", "w", "h"}
        self.folders = set()  # rel folder paths ("" = root)
        self.version = 0      # bumped when files are added, removed or moved
        self.size_version = 0  # bumped when pixel sizes become known
        self._cache = {}      # search cache: params -> list of files
        self._gen = 0         # background job generation; a new scan cancels the old job
        self.progress = {"sizes_left": 0, "thumbs_left": 0, "thumbs_total": 0}
        # On-demand thumbnails (the images on screen) - at most this many at once,
        # so fast scrolling does not start dozens of decodes in parallel.
        self._ondemand = threading.Semaphore(cfg.get("thumb_threads", 2))
        # Screen-size copies for the enlarged view (about 0.2 s of CPU each): at most 2 at once,
        # so holding the arrow key does not start a dozen of them in parallel.
        self._displays = threading.Semaphore(2)
        self.active_until = 0.0  # the background job waits while the user is browsing
        self.paused = False      # ... and while "Pause" is on in the header

    # ------------------------------------------------------------ paths

    def abs(self, rel):
        """Absolute path of a rel path; refuses anything outside the root."""
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError("path outside the image folder")
        return p

    def rel_of(self, path):
        r = Path(path).resolve().relative_to(self.root).as_posix()
        return "" if r == "." else r

    def thumb_path(self, f):
        return self.data_dir / "thumbs" / f["key"][:2] / f"{f['key']}.jpg"

    def has_thumb(self, f):
        """The thumbnail if it exists - also one in the older WebP format."""
        p = self.thumb_path(f)
        if p.exists():
            return p
        old = p.with_suffix(".webp")
        return old if old.exists() else None

    def display_path(self, f):
        return self.data_dir / "display" / str(self.cfg["display_size"]) / f["key"][:2] / f"{f['key']}.jpg"

    def _skip_dir(self, name, full):
        return (name.startswith(".") or name.lower() in self.cfg["skip_folders"]
                or Path(full).resolve() == self.data_dir)

    def changed(self):
        self.version += 1
        self._cache.clear()

    # ------------------------------------------------------------ scan

    def set_root(self, root):
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"not a folder: {root}")
        with self.lock:
            self.root = root
            return self.scan()

    def _walk(self):
        """All image files under the root: (folder rel, name, stat). Uses scandir, whose
        stat results come with the directory listing on Windows (no extra disk access)."""
        exts = self.cfg["image_extensions"]
        folders, out, stack = {""}, [], [(str(self.root), "")]
        while stack:
            path, rel = stack.pop()
            try:
                entries = list(os.scandir(path))
            except OSError:
                continue
            for e in entries:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if not self._skip_dir(e.name, e.path):
                            sub = f"{rel}/{e.name}" if rel else e.name
                            folders.add(sub)
                            stack.append((e.path, sub))
                    elif os.path.splitext(e.name)[1].lower() in exts:
                        out.append((rel, e.name, e.stat()))
                except OSError:
                    continue
        return folders, out

    def scan(self):
        """List the root and rebuild the index. Only file names and dates are read here;
        pixel sizes come from the cache, unknown ones and thumbnails follow in the background."""
        folders, found = self._walk()
        files = {}
        for folder, name, st in found:
            rel = f"{folder}/{name}" if folder else name
            files[rel] = {"rel": rel, "name": name, "folder": folder, "size": st.st_size,
                          "mtime": st.st_mtime, "key": file_key(name, st.st_size, st.st_mtime_ns),
                          "w": None, "h": None}
        keys = [f["key"] for f in files.values()]
        known = {}
        with self.db_lock:
            for i in range(0, len(keys), 900):
                chunk = keys[i:i + 900]
                known.update({k: (w, h) for k, w, h in self.db.execute(
                    f"SELECT key, w, h FROM sizes WHERE key IN ({','.join('?' * len(chunk))})", chunk)})
        for f in files.values():
            f["w"], f["h"] = known.get(f["key"], (None, None))
        self.files, self.folders = files, folders
        self.changed()
        unknown = sum(1 for f in files.values() if f["key"] not in known)
        self.start_background()
        return {"root": str(self.root), "images": len(files), "folders": len(folders),
                "sizes_unknown": unknown}

    def _store_sizes(self, rows):
        with self.db_lock:
            self.db.executemany("INSERT OR REPLACE INTO sizes VALUES (?, ?, ?)", rows)
            self.db.commit()

    def _set_size(self, f, wh):
        if wh and wh[0] and f["w"] is None:
            f["w"], f["h"] = wh
            self.size_version += 1
            return True
        return False

    # ------------------------------------------------------------ thumbnails

    def touch(self, seconds=3.0):
        """The user is doing something: keep the background job paused for a moment."""
        self.active_until = max(self.active_until, time.monotonic() + seconds)

    def thumb(self, f):
        self.touch()
        p = self.has_thumb(f)
        if p:
            return p
        p = self.thumb_path(f)
        with self._ondemand:
            if not p.exists():
                wh = make_thumb(self.root / f["rel"], p)
                if self._set_size(f, wh):
                    self._store_sizes([(f["key"], *wh)])
        return p if p.exists() else None

    def display(self, f):
        """Screen-size copy for images larger than display_size, else None (use the original)."""
        self.touch()
        size = self.cfg["display_size"]
        if f["w"] is None:
            wh = read_size(self.root / f["rel"])
            if self._set_size(f, wh):
                self._store_sizes([(f["key"], *wh)])
        if not f["w"] or max(f["w"], f["h"]) <= size:
            return None
        p = self.display_path(f)
        if not p.exists():
            with self._displays:
                if not p.exists():
                    make_display(self.root / f["rel"], p, size)
        return p if p.exists() else None

    def stop_background(self):
        """Cancel the background job (on exit: Python waits for queued pool tasks before it
        quits, so without this, Ctrl+C would leave it making thumbnails until all are done)."""
        self._gen += 1

    def start_background(self):
        """Read unknown pixel sizes, then make missing thumbnails, on background_threads
        threads (default 1) running at the lowest CPU priority. It waits while the user is
        browsing (the images on screen are made on demand meanwhile) and while it is paused,
        and resumes after a few quiet seconds. A new scan, another folder or closing the app
        cancels it."""
        self._gen += 1
        gen, files = self._gen, list(self.files.values())
        workers = max(1, int(self.cfg.get("background_threads", 1)))

        def alive():
            return gen == self._gen

        def wait():
            while alive() and (self.paused or time.monotonic() < self.active_until):
                time.sleep(0.5)

        def run():
            lowest_priority()
            todo = [f for f in files if f["w"] is None]
            self.progress = {"sizes_left": len(todo), "thumbs_left": 0, "thumbs_total": 0}
            with ThreadPoolExecutor(max_workers=workers, initializer=lowest_priority) as pool:
                batch = []
                def size_of(f):
                    wait()
                    return read_size(self.root / f["rel"]) if alive() else None
                for f, wh in zip(todo, pool.map(size_of, todo)):
                    if not alive():
                        return
                    if self._set_size(f, wh):
                        batch.append((f["key"], *wh))
                    self.progress["sizes_left"] -= 1
                    if len(batch) >= 500:
                        self._store_sizes(batch)
                        batch = []
                self._store_sizes(batch)
            if not alive():
                return
            todo = [f for f in files if not self.has_thumb(f)]
            self.progress.update(thumbs_left=len(todo), thumbs_total=len(todo))

            def one(f):
                wait()
                if alive() and not self.has_thumb(f):
                    wh = make_thumb(self.root / f["rel"], self.thumb_path(f))
                    if self._set_size(f, wh):
                        self._store_sizes([(f["key"], *wh)])
                self.progress["thumbs_left"] -= 1

            with ThreadPoolExecutor(max_workers=workers, initializer=lowest_priority) as pool:
                slots = threading.Semaphore(workers * 2)  # submit lazily, so cancelling is quick
                for f in todo:
                    if not alive():
                        break
                    slots.acquire()
                    pool.submit(one, f).add_done_callback(lambda _: slots.release())
            if alive():
                self.progress.update(thumbs_left=0)

        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ queries

    def tree(self):
        """Nested folders with the number of images directly in each and in total."""
        direct = {}
        for f in self.files.values():
            direct[f["folder"]] = direct.get(f["folder"], 0) + 1
        nodes = {p: {"path": p, "name": p.rsplit("/", 1)[-1] if p else self.root.name,
                     "n": direct.get(p, 0), "total": 0, "children": []}
                 for p in self.folders}
        for p in sorted(self.folders, key=lambda p: (-p.count("/"), p)):
            node = nodes[p]
            node["total"] += node["n"]
            if p:
                parent = nodes.get(p.rsplit("/", 1)[0] if "/" in p else "")
                if parent is not None:
                    parent["total"] += node["total"]
                    parent["children"].append(node)
        for node in nodes.values():
            node["children"].sort(key=lambda c: c["name"].lower())
        return nodes[""]

    def in_folder(self, folder, recursive):
        if recursive:
            pre = folder + "/" if folder else ""
            return [f for f in self.files.values() if f["folder"] == folder or f["folder"].startswith(pre)]
        return [f for f in self.files.values() if f["folder"] == folder]

    @staticmethod
    def gkey(f, words):
        cache = f.setdefault("_g", {})
        if words not in cache:
            cache[words] = group_key(f["name"], words)
        return cache[words]

    def search(self, folder="", recursive=False, q="", sort="name", group=None, words=1, fresh=True):
        """Filtered and sorted file list. Cached, because paging asks for the same list again.
        Sorting by resolution changes while pixel sizes come in; it is sorted again only for
        the first page (fresh=True), so the later pages of a view keep the same order and
        100,000 images are not sorted again for every page."""
        res = sort in ("res_desc", "res_asc")
        base = (folder, recursive, q, sort, group, words, self.version)
        ck = base + ((self.size_version if res else 0),)
        hit = self._cache.get(ck)
        if hit is None and res and not fresh:
            hit = self._cache.get(("last",) + base)
        if hit is not None:
            return hit
        fs = self.in_folder(folder, recursive)
        for word in q.lower().split():
            fs = [f for f in fs if word in f["rel"].lower()]
        if group is not None:
            fs = [f for f in fs if self.gkey(f, words) == group]
        px = lambda f: f["w"] * f["h"] if f["w"] and f["h"] else None
        fs.sort(key=lambda f: f["rel"].lower())
        if sort == "newest":
            fs.sort(key=lambda f: -f["mtime"])
        elif sort == "oldest":
            fs.sort(key=lambda f: f["mtime"])
        elif sort == "res_desc":
            fs.sort(key=lambda f: (px(f) is None, -(px(f) or 0)))
        elif sort == "res_asc":
            fs.sort(key=lambda f: (px(f) is None, px(f) or 0))
        elif sort == "group":
            fs.sort(key=lambda f: (self.gkey(f, words) == "", self.gkey(f, words)))
        if len(self._cache) > 20:
            self._cache.clear()
        self._cache[ck] = fs
        if res:
            self._cache[("last",) + base] = fs
        return fs

    def groups(self, folder="", recursive=False, q="", words=1, min_size=2):
        counts = {}
        for f in self.search(folder, recursive, q):
            k = self.gkey(f, words)
            counts[k] = counts.get(k, 0) + 1
        nokey = counts.pop("", 0)
        out = [{"key": k, "n": n} for k, n in counts.items() if n >= min_size]
        out.sort(key=lambda g: (-g["n"], g["key"]))
        singles = sum(n for n in counts.values() if n < min_size)
        return {"groups": out, "singles": singles, "no_words": nokey}
