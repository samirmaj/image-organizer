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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

THUMB_SIZE = 320  # long side, px


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
    try:
        with Image.open(path) as im:
            im.draft("RGB", (THUMB_SIZE, THUMB_SIZE))
            im = ImageOps.exif_transpose(im)
            alpha = "A" in im.mode or "transparency" in im.info
            im = im.convert("RGBA" if alpha else "RGB")
            im.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "WEBP", quality=80)
            os.replace(tmp, out)
        return True
    except Exception:
        return False


def make_display(path, out, size):
    """JPEG copy with long side = size. None for images with transparency (JPEG has none)."""
    try:
        with Image.open(path) as im:
            if "A" in im.mode or "transparency" in im.info:
                return False
            im.draft("RGB", (size, size))
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size), Image.LANCZOS)
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "JPEG", quality=88, optimize=True)
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
        self.lock = threading.RLock()
        self.root = None
        self.files = {}     # rel -> {"rel", "name", "folder", "size", "mtime", "key", "w", "h"}
        self.folders = set()  # rel folder paths ("" = root)
        self._warm_gen = 0

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
        return self.data_dir / "thumbs" / f["key"][:2] / f"{f['key']}.webp"

    def display_path(self, f):
        return self.data_dir / "display" / str(self.cfg["display_size"]) / f["key"][:2] / f"{f['key']}.jpg"

    def _skip_dir(self, name, full):
        return (name.startswith(".") or name.lower() in self.cfg["skip_folders"]
                or Path(full).resolve() == self.data_dir)

    # ------------------------------------------------------------ scan

    def set_root(self, root):
        root = Path(root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"not a folder: {root}")
        with self.lock:
            self.root = root
            return self.scan()

    def _entry(self, path, folder, name):
        st = os.stat(path)
        key = file_key(name, st.st_size, st.st_mtime_ns)
        rel = f"{folder}/{name}" if folder else name
        return {"rel": rel, "name": name, "folder": folder, "size": st.st_size,
                "mtime": st.st_mtime, "key": key, "w": None, "h": None}

    def scan(self):
        """Walk the root and rebuild the index. Pixel sizes come from the cache when known."""
        exts = self.cfg["image_extensions"]
        files, folders = {}, {""}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if not self._skip_dir(d, os.path.join(dirpath, d)))
            folder = self.rel_of(dirpath)
            folders.add(folder)
            for name in filenames:
                if os.path.splitext(name)[1].lower() in exts:
                    try:
                        e = self._entry(os.path.join(dirpath, name), folder, name)
                    except OSError:
                        continue
                    files[e["rel"]] = e
        known = {}
        keys = [f["key"] for f in files.values()]
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            known.update({k: (w, h) for k, w, h in self.db.execute(
                f"SELECT key, w, h FROM sizes WHERE key IN ({','.join('?' * len(chunk))})", chunk)})
        todo = [f for f in files.values() if f["key"] not in known]
        with ThreadPoolExecutor() as pool:
            for f, wh in zip(todo, pool.map(lambda f: read_size(self.root / f["rel"]), todo)):
                known[f["key"]] = wh
        self.db.executemany("INSERT OR REPLACE INTO sizes VALUES (?, ?, ?)",
                            [(f["key"], *known[f["key"]]) for f in todo])
        self.db.commit()
        for f in files.values():
            f["w"], f["h"] = known[f["key"]]
        self.files, self.folders = files, folders
        self.start_warming()
        return {"root": str(self.root), "images": len(files), "folders": len(folders), "new_sizes_read": len(todo)}

    # ------------------------------------------------------------ thumbnails

    def thumb(self, f):
        p = self.thumb_path(f)
        if not p.exists():
            make_thumb(self.root / f["rel"], p)
        return p if p.exists() else None

    def display(self, f):
        """Screen-size copy for images larger than display_size, else None (use the original)."""
        size = self.cfg["display_size"]
        if not f["w"] or max(f["w"], f["h"]) <= size:
            return None
        p = self.display_path(f)
        if not p.exists():
            make_display(self.root / f["rel"], p, size)
        return p if p.exists() else None

    def start_warming(self):
        """Make the missing thumbnails in the background, so scrolling is fast later."""
        self._warm_gen += 1
        gen, files = self._warm_gen, list(self.files.values())

        def run():
            with ThreadPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
                for f in files:
                    if gen != self._warm_gen:
                        return
                    if not self.thumb_path(f).exists():
                        pool.submit(self.thumb, f)
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
                parent = nodes[p.rsplit("/", 1)[0] if "/" in p else ""]
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

    def search(self, folder="", recursive=False, q="", sort="name", group=None, words=1):
        fs = self.in_folder(folder, recursive)
        for word in q.lower().split():
            fs = [f for f in fs if word in f["rel"].lower()]
        if group is not None:
            fs = [f for f in fs if group_key(f["name"], words) == group]
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
            fs.sort(key=lambda f: (group_key(f["name"], words) == "", group_key(f["name"], words)))
        return fs

    def groups(self, folder="", recursive=False, q="", words=1, min_size=2):
        counts = {}
        for f in self.search(folder, recursive, q):
            k = group_key(f["name"], words)
            counts[k] = counts.get(k, 0) + 1
        nokey = counts.pop("", 0)
        out = [{"key": k, "n": n} for k, n in counts.items() if n >= min_size]
        out.sort(key=lambda g: (-g["n"], g["key"]))
        singles = sum(n for n in counts.values() if n < min_size)
        return {"groups": out, "singles": singles, "no_words": nokey}
