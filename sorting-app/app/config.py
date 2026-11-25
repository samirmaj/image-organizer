import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config(path=None):
    path = Path(path or os.environ.get("SORTER_CONFIG") or ROOT / "config.yaml")
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    base = path.resolve().parent
    cfg["data_dir"] = (base / cfg.get("data_dir", "./appdata")).resolve()
    cfg.setdefault("display_size", 1600)
    cfg.setdefault("port", 8001)
    cfg["image_extensions"] = {e.lower() for e in cfg["image_extensions"]}
    cfg["skip_folders"] = {s.lower() for s in cfg.get("skip_folders") or []}
    return cfg
