# sorting-app

A small local web app for sorting an image folder by hand: browse the folders, look at the
images, select groups of them and move them into folders. It is a stripped-down copy of
image-app (same stack and the same gallery, enlarged view and selection), without the
annotations, filters, editor, collections and export.

## Start

```
cd sorting-app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

The browser opens at http://localhost:8001 (port 8001, so it can run next to image-app on 8000).

Set `image_root` in `config.yaml` to the folder it should open on the first start. After
that, **Change folder…** opens any other folder, and the app remembers the last one.

## Using it

**Folders (left).** Click a folder to show its images. The numbers are "images in this
folder · images including subfolders". **subfolders** in the header also shows the images
of all subfolders. **+ New folder** creates a subfolder of the open folder.

**Selecting.** This works as in image-app:

| Action | Effect |
|---|---|
| Click | opens the enlarged view |
| Ctrl-click | selects / deselects one image |
| Shift-click | selects everything between the last Ctrl-click and this image |
| Ctrl+A | selects all images shown (all pages) |
| Esc | clears the selection |

**Moving.** When something is selected, the bar at the bottom offers:
- **Folder…** (or the M key): pick a folder from the tree, or type a path such as
  `fashion/street style/nyfw`. Missing folders are created.
- The last 9 targets as buttons. The keys **1** to **9** move the selection to them.
- You can also drag selected images onto a folder in the tree.

A move never overwrites a file. If the target already has a file with the same name, the
moved file gets " (2)" added. **↶ Undo move** (or Ctrl+Z) puts the last move back,
including the original names, and removes folders that the move created if they are empty
again. It keeps the last 50 moves, also after a restart. Every move and undo is written to
`appdata/moves.log`.

**Name groups (left, second tab).** Groups the images of the open folder by the first words
of their file name, ignoring numbers and hash-like strings. For example, `nyfw_001.jpg` and
`NYFW-2024-17.jpg` both go into *nyfw*. Click a group to show only its images, or
**select** to add the whole group to the selection. "words" sets how many words make up a
group (`alexa-chung-…` → *alexa* or *alexa chung*). The sort option "name group" puts
images of the same group next to each other.

**Enlarged view.** ← → for the previous and next image. Click the image to zoom to 100 %,
scroll to zoom gradually, and drag to pan. **S** (or Ctrl-click on the image) selects the
image. **I** shows or hides the info panel, and Esc or Space goes back to the grid.

**Rescan** reads the folder again after you change files outside the app.

## Files

```
sorting-app/
  config.yaml        start folder, port, image types, cache settings
  run.py             starts the server and opens the browser
  app/config.py      loads config.yaml (SORTER_CONFIG=path uses another file)
  app/library.py     walks the folder, pixel sizes, thumbnails, name groups
  app/moves.py       move, create folder, undo, move log
  app/server.py      FastAPI endpoints
  static/index.html  the whole frontend (Alpine.js, no build step)
  appdata/           created at runtime, git-ignored: cache.db (pixel sizes),
                     thumbs/, display/ (screen-size copies), moves.log, undo.json, state.json
```

Thumbnails are made in the background after a scan and on demand while you scroll. They
are stored under a key made of the file name, size and date, so moving a file does not
make a new thumbnail. The app only ever moves files and creates folders. It never deletes
or changes an image.
