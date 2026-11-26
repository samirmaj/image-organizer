"""FastAPI app: browse an image folder, inspect images, move selected images to folders."""
import json
import mimetypes
import os
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT, load_config
from .library import Library
from .moves import Mover

mimetypes.add_type("image/jpeg", ".jfif")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")

cfg = load_config()
lib = Library(cfg)
mover = Mover(lib)
STATE = Path(cfg["data_dir"]) / "state.json"  # remembers the last opened folder
OPEN_BROWSER = False  # set by run.py
LONG_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(**changes):
    STATE.write_text(json.dumps({**load_state(), **changes}), encoding="utf-8")


def start_root():
    last = load_state().get("root")
    return last if last and os.path.isdir(last) else cfg["image_root"]


@asynccontextmanager
async def lifespan(app):
    lib.paused = bool(load_state().get("paused"))
    r = lib.set_root(start_root())
    print(f"{r['root']}: {r['images']} images in {r['folders']} folders")
    if OPEN_BROWSER:
        threading.Timer(0.5, webbrowser.open, [f"http://localhost:{cfg['port']}"]).start()
    yield
    lib.stop_background()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def get_file(rel):
    f = lib.files.get(rel)
    if not f:
        raise HTTPException(404, "image not found - try Rescan")
    return f


def bad(e):
    raise HTTPException(400, str(e))


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/state")
def state():
    return {"root": str(lib.root), "images": len(lib.files), "last_move": mover.last(),
            "tree": lib.tree(), "progress": progress_info(), **trash_info()}


def trash_info():
    return {"trash": cfg["trash_folder"], "trash_count": mover.trash_count()}


def progress_info():
    return {**lib.progress, "paused": lib.paused}


@app.get("/api/progress")
def progress():
    """Background work: pixel sizes still to read, thumbnails still to make."""
    return progress_info()


@app.post("/api/pause")
def pause(body: dict = Body(...)):
    """Pause or resume the background thumbnails (remembered for the next start)."""
    lib.paused = bool(body.get("paused"))
    save_state(paused=lib.paused)
    return progress_info()


@app.post("/api/root")
def set_root(body: dict = Body(...)):
    try:
        r = lib.set_root(body["path"].strip().strip('"'))
    except ValueError as e:
        bad(e)
    save_state(root=r["root"])
    return r


@app.post("/api/rescan")
def rescan():
    with lib.lock:
        return lib.scan()


def item(f):
    return {"id": f["rel"], "name": f["name"], "folder": f["folder"], "v": f["key"][:12],
            "w": f["w"], "h": f["h"], "b": f["size"]}


@app.get("/api/size")
def size(id: str):
    """Pixel size for the hover label, read from the file header if not known yet."""
    w, h = lib.size_of(get_file(id))
    return {"w": w, "h": h}


@app.post("/api/list")
def list_images(body: dict = Body(...)):
    lib.touch()
    fs = lib.search(body.get("folder", ""), body.get("recursive", False), body.get("q", ""),
                    body.get("sort", "name"), body.get("group"), body.get("words", 1),
                    fresh=not body.get("offset"))
    if body.get("ids_only"):  # "select all"
        return {"ids": [f["rel"] for f in fs]}
    offset, limit = body.get("offset", 0), body.get("limit", 200)
    return {"total": len(fs), "offset": offset, "items": [item(f) for f in fs[offset:offset + limit]]}


@app.post("/api/groups")
def groups(body: dict = Body(...)):
    return lib.groups(body.get("folder", ""), body.get("recursive", False), body.get("q", ""),
                      body.get("words", 1), body.get("min_size", 2))


@app.get("/api/info")
def info(id: str):
    f = get_file(id)
    p = lib.root / f["rel"]
    return {**item(f), "path": str(p), "bytes": f["size"], "mtime": f["mtime"]}


@app.get("/thumb")
def thumb(id: str):
    p = lib.thumb(get_file(id))
    if not p:
        raise HTTPException(404)
    return FileResponse(p, headers=LONG_CACHE)


@app.get("/full")
def full(id: str):
    """The original. URLs carry ?v=<cache key>, so the browser may keep it."""
    f = get_file(id)
    return FileResponse(lib.root / f["rel"], headers=LONG_CACHE)


@app.get("/display")
def display(id: str):
    """Screen-size copy for large images; falls back to the original."""
    f = get_file(id)
    p = lib.display(f)
    if p:
        return FileResponse(p, media_type="image/jpeg", headers=LONG_CACHE)
    return FileResponse(lib.root / f["rel"], headers=LONG_CACHE)


@app.post("/api/mkdir")
def mkdir(body: dict = Body(...)):
    try:
        return {"folder": mover.mkdir(body["folder"]), "tree": lib.tree()}
    except (ValueError, OSError) as e:
        bad(e)


@app.post("/api/move")
def move(body: dict = Body(...)):
    """{ids: [rel], dest: "fashion/street style"} - the folder is created if needed."""
    try:
        r = mover.move(body["ids"], body["dest"])
    except (ValueError, OSError) as e:
        bad(e)
    return {**r, "last_move": mover.last(), "tree": lib.tree(), **trash_info()}


@app.post("/api/trash")
def trash(body: dict = Body(...)):
    """{ids: [rel]} -> moved into the trash folder (undoable)."""
    r = mover.trash(body["ids"])
    return {**r, "last_move": mover.last(), "tree": lib.tree(), **trash_info()}


@app.post("/api/empty-trash")
def empty_trash():
    try:
        r = mover.empty_trash()
    except ImportError:
        bad("send2trash is not installed: run  pip install send2trash")
    return {**r, "last_move": mover.last(), "tree": lib.tree(), **trash_info()}


@app.post("/api/undo")
def undo():
    r = mover.undo()
    return {**r, "last_move": mover.last(), "tree": lib.tree(), **trash_info()}


@app.post("/api/open-folder")
def open_folder(body: dict = Body(...)):
    """Show a folder in Windows Explorer (local, single-user app)."""
    try:
        p = lib.abs(body.get("folder", ""))
    except ValueError as e:
        bad(e)
    if hasattr(os, "startfile"):
        os.startfile(p)
    return {"ok": True}
