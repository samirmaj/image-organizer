# sorting-app

Local, single-user app to sort an image folder by hand (browse, inspect, select, move).
Stripped-down copy of image-app; see README.md for what it does.

## Rules
- Python + FastAPI + Pillow; frontend is one HTML page with Alpine.js, no Node, no build step.
- Keep it lightweight: no auth, no abstractions that aren't needed.
- The app may only move image files and create folders inside the open folder. Never
  overwrite or edit an image. Every move goes through app/moves.py so it is logged and undoable.
  The only removal is "Empty trash" (approved by the user 2026-11-26): it sends the files in the
  trash folder to the OS Recycle Bin via send2trash, never deletes permanently.
- All app data goes to ./appdata (git-ignored).
- Never change image-app (the original app/repo); this is a separate copy.
