"""Moving images into folders, and undoing the last moves.

A move never overwrites: if the target folder already has a file with that name, the
moved file gets " (2)", " (3)", ... before its extension. Every batch is appended to
appdata/moves.log (a record that only grows) and pushed on an undo stack kept in
appdata/undo.json, so undo also works after a restart.
"""
import json
import os
import shutil
import time
from pathlib import Path

from .library import file_key


def free_name(folder: Path, name):
    stem, ext = os.path.splitext(name)
    cand, n = folder / name, 2
    while cand.exists():
        cand, n = folder / f"{stem} ({n}){ext}", n + 1
    return cand


def clean_folder(rel):
    """'fashion\\street style/ ' -> 'fashion/street style'. Refuses '..' and drive letters."""
    parts = [p.strip() for p in rel.replace("\\", "/").split("/") if p.strip() and p.strip() != "."]
    if any(p == ".." or ":" in p for p in parts):
        raise ValueError("folder names may not contain '..' or ':'")
    return "/".join(parts)


class Mover:
    def __init__(self, lib):
        self.lib = lib
        self.log = Path(lib.data_dir) / "moves.log"
        self.undo_file = Path(lib.data_dir) / "undo.json"

    def _stack(self):
        try:
            return json.loads(self.undo_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def _save_stack(self, stack):
        self.undo_file.write_text(json.dumps(stack[-50:], ensure_ascii=False), encoding="utf-8")

    def _write_log(self, entry):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _relocate(self, src_rel, dest_folder_abs, name=None):
        """Move one file (keeping its name, or taking `name`); update the index. Returns the new rel path."""
        lib = self.lib
        src = lib.abs(src_rel)
        dest = free_name(dest_folder_abs, name or src.name)
        shutil.move(str(src), str(dest))
        new_rel = lib.rel_of(dest)
        f = lib.files.pop(src_rel)
        f.update(rel=new_rel, name=dest.name, folder=lib.rel_of(dest.parent))
        if dest.name != src.name:  # the cache key includes the name
            st = os.stat(dest)
            f["key"] = file_key(dest.name, st.st_size, st.st_mtime_ns)
        lib.files[new_rel] = f
        return new_rel

    def _make_dirs(self, folder_rel):
        """Create folder_rel (and parents). Returns the folders that did not exist before."""
        lib, created, cur = self.lib, [], ""
        for part in folder_rel.split("/") if folder_rel else []:
            cur = f"{cur}/{part}" if cur else part
            p = lib.abs(cur)
            if not p.exists():
                p.mkdir()
                created.append(cur)
            lib.folders.add(cur)
        return created

    def mkdir(self, folder_rel):
        with self.lib.lock:
            folder_rel = clean_folder(folder_rel)
            self._make_dirs(folder_rel)
            return folder_rel

    def move(self, rels, dest):
        lib = self.lib
        with lib.lock:
            dest = clean_folder(dest)
            created = self._make_dirs(dest)
            dest_abs = lib.abs(dest)
            done, skipped, errors = [], 0, []
            for rel in rels:
                f = lib.files.get(rel)
                if not f:
                    errors.append([rel, "not found (rescan?)"])
                    continue
                if f["folder"] == dest:
                    skipped += 1
                    continue
                try:
                    done.append([rel, self._relocate(rel, dest_abs)])
                except (OSError, ValueError) as e:
                    errors.append([rel, str(e)])
            renamed = sum(1 for a, b in done if a.rsplit("/", 1)[-1] != b.rsplit("/", 1)[-1])
            if done or created:
                batch = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "root": str(lib.root), "dest": dest,
                         "moves": done, "created": created}
                self._write_log({"action": "move", **batch})
                stack = self._stack()
                stack.append(batch)
                self._save_stack(stack)
            return {"moved": len(done), "renamed": renamed, "skipped": skipped,
                    "errors": errors, "dest": dest, "moved_to": [b for _, b in done]}

    def last(self):
        stack = self._stack()
        if not stack:
            return None
        b = stack[-1]
        if b.get("root") != str(self.lib.root):
            return None
        return {"time": b["time"], "dest": b["dest"], "n": len(b["moves"])}

    def undo(self):
        """Move the files of the last batch back; remove folders it created if now empty."""
        lib = self.lib
        with lib.lock:
            stack = self._stack()
            if not stack:
                return {"undone": 0, "errors": [], "message": "nothing to undo"}
            if stack[-1].get("root") != str(lib.root):
                return {"undone": 0, "errors": [],
                        "message": f"the last move was in another folder: {stack[-1].get('root')}"}
            batch = stack.pop()
            back, errors = [], []
            for orig, now in reversed(batch["moves"]):
                if now not in lib.files:
                    errors.append([now, "no longer there"])
                    continue
                folder, _, name = orig.rpartition("/")
                try:
                    self._make_dirs(folder)
                    back.append([now, self._relocate(now, lib.abs(folder), name)])
                except (OSError, ValueError) as e:
                    errors.append([now, str(e)])
            for folder in reversed(batch.get("created", [])):
                p = lib.abs(folder)
                try:
                    if p.is_dir() and not any(p.iterdir()):
                        p.rmdir()
                        lib.folders.discard(folder)
                except OSError:
                    pass
            self._save_stack(stack)
            self._write_log({"action": "undo", "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "of": batch["time"], "moves": back})
            return {"undone": len(back), "errors": errors, "dest": batch["dest"]}
