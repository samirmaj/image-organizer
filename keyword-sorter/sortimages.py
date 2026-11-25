#!/usr/bin/env python3
"""
sortimages.py - sort an image folder into folders by keywords in the filenames.

Only needs Python 3.8+ (no extra packages). Works on Windows, macOS and Linux.

Workflow (run these inside your image folder, or pass the folder path):

  1. py sortimages.py scan      Count the words in your filenames and folder
                                names (all subfolders included) and write a
                                starter keywords.json plus a word report.
                                Edit keywords.json to add people, brands, etc.
  2. py sortimages.py plan      Preview: decide a destination for every image
                                and write sort_plan.csv. Nothing is moved.
                                Leftovers are grouped by recurring words.
  3. py sortimages.py apply     Move the files exactly as sort_plan.csv says
                                (you may edit the CSV first). Writes an undo log.
  4. py sortimages.py undo      Put everything back using the newest undo log.

Use "py" on Windows, "python3" elsewhere. Add --help to any step for options.
"""

import argparse
import collections
import csv
import datetime as _dt
import json
import os
import re
import shutil
import sys

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".avif", ".jfif", ".svg",
}

CONFIG_NAME = "keywords.json"
REPORT_NAME = "keyword_report.csv"
PLAN_NAME = "sort_plan.csv"
UNDO_PREFIX = "undo_log_"

# Words that say nothing about the content of an image. They are ignored when
# counting words and when grouping leftovers. Extend via "ignore_words" in
# keywords.json.
DEFAULT_IGNORE = {
    "img", "image", "images", "photo", "photos", "pic", "pics", "picture",
    "dsc", "dscn", "dscf", "dcim", "pxl", "mvimg", "wp", "whatsapp", "signal",
    "copy", "kopie", "final", "edit", "edited", "new", "old", "small", "large",
    "big", "thumb", "thumbnail", "original", "orig", "full", "hd", "hq", "lq",
    "the", "and", "der", "die", "das", "und", "von", "for", "with",
    "jpg", "jpeg", "png", "webp", "gif", "heic", "jfif", "file", "download",
    "downloaded", "unknown", "untitled", "unbenannt", "at", "am", "pm", "of",
    "in", "on", "by", "a", "to", "x", "px", "w", "h", "s", "o", "f", "n",
}

# Starter rules. Folder paths use "/" and are created inside the image folder.
# The FIRST matching rule wins: people first, then specific fashion weeks,
# magazines and brands, then the general fashion folders, then misc.
STARTER_RULES = collections.OrderedDict([
    ("people/Alexa Chung", ["alexa chung", "alexachung"]),

    ("fashion/street style/New York Fashion Week",
     ["nyfw", "new york fashion week", "nyfashionweek", "ny fashion week"]),
    ("fashion/street style/Paris Fashion Week",
     ["pfw", "paris fashion week", "parisfashionweek"]),
    ("fashion/street style/Milan Fashion Week",
     ["mfw", "milan fashion week", "milanfashionweek"]),
    ("fashion/street style/London Fashion Week",
     ["lfw", "london fashion week", "londonfashionweek"]),
    ("fashion/street style/Copenhagen Fashion Week",
     ["cphfw", "copenhagen fashion week"]),

    ("fashion/editorial/Vogue", ["vogue"]),
    ("fashion/editorial/Elle", ["elle"]),
    ("fashion/editorial/Harper's Bazaar", ["harpers bazaar", "bazaar"]),
    ("fashion/editorial/i-D", ["i-d magazine", "id magazine"]),
    ("fashion/editorial/Dazed", ["dazed"]),
    ("fashion/editorial/W Magazine", ["w magazine", "wmagazine"]),

    ("fashion/brands/Zara", ["zara"]),
    ("fashion/brands/Mango", ["mango"]),
    ("fashion/brands/H&M", ["h&m", "hm", "hennes"]),
    ("fashion/brands/COS", ["cos"]),
    ("fashion/brands/& Other Stories", ["other stories", "otherstories"]),
    ("fashion/brands/Arket", ["arket"]),
    ("fashion/brands/Uniqlo", ["uniqlo"]),
    ("fashion/brands/Acne Studios", ["acne studios", "acne"]),
    ("fashion/brands/Ganni", ["ganni"]),
    ("fashion/brands/Toteme", ["toteme", "totême"]),
    ("fashion/brands/The Row", ["the row", "therow"]),
    ("fashion/brands/Miu Miu", ["miu miu", "miumiu"]),
    ("fashion/brands/Prada", ["prada"]),
    ("fashion/brands/Celine", ["celine", "céline"]),
    ("fashion/brands/Chanel", ["chanel"]),

    # General folders last, so a specific brand or magazine wins over them.
    ("fashion/street style", ["street style", "streetstyle", "streetwear",
                              "street snap", "fashion week", "fw"]),
    ("fashion/editorial", ["editorial", "magazine", "cover", "photoshoot",
                           "shoot", "campaign", "lookbook"]),

    ("misc/screenshots", ["screenshot", "screen shot", "bildschirmfoto",
                          "capture", "snip", "scrnli"]),
])

STARTER_CONFIG_HELP = (
    "Edit this file to teach the sorter. 'rules' maps a destination folder to "
    "the keywords that send an image there; the first matching rule wins, so "
    "keep people at the top and misc at the bottom. Keywords are not case "
    "sensitive, and 'alexa chung' also matches alexa_chung, Alexa-Chung and "
    "AlexaChung. 'suggestions' lists frequent words from your filenames that no "
    "rule uses yet: move the useful ones into a rule. 'ignore_words' are left "
    "out of counts and leftover groups."
)


# --------------------------------------------------------------------------
# CSV helpers: use the list separator Excel expects on this computer (a
# semicolon on German Windows, a comma on English), and read either back.

def excel_delimiter():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Control Panel\International") as k:
            sep = winreg.QueryValueEx(k, "sList")[0]
            if sep in (",", ";", "\t"):
                return sep
    except Exception:
        pass
    return ","


def csv_writer(f):
    return csv.writer(f, delimiter=excel_delimiter())


def csv_dict_reader(f):
    first = f.readline()
    f.seek(0)
    counts = {d: first.count(d) for d in (",", ";", "\t")}
    return csv.DictReader(f, delimiter=max(counts, key=counts.get))


# --------------------------------------------------------------------------
# Filename helpers
# --------------------------------------------------------------------------

def strip_accents(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def split_words(stem):
    """'AlexaChung_NYFW-2019 (2)' -> ['alexa', 'chung', 'nyfw', '2019', '2']"""
    s = strip_accents(stem)
    s = s.replace("&", " & ")
    # split camelCase / PascalCase and letter-digit boundaries
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)
    s = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", s)
    s = s.lower()
    return [w for w in re.split(r"[^a-z0-9&]+", s) if w]


def squash(text):
    return re.sub(r"[^a-z0-9&]+", "", strip_accents(text).lower())


def is_noise(word, ignore):
    if word in ignore or len(word) < 2:
        return True
    if word.isdigit():
        return True
    # hex-ish hashes and long random ids, e.g. 'a3f9c02b', 'e35b1e7d4f'
    if len(word) >= 8 and re.fullmatch(r"[a-z0-9]+", word) and \
            sum(c.isdigit() for c in word) >= 2:
        return True
    return False


class Keyword:
    """One keyword from the config, ready for matching."""

    def __init__(self, raw, min_squash_len):
        self.raw = raw
        self.words = split_words(raw) or [raw.lower()]
        self.squashed = squash(raw)
        # Matching 'alexachung' inside 'alexachungnyfw2019' is handy, but short
        # keywords like 'hm' or 'cos' would hit random words, so substring
        # matching is only used for long keywords.
        self.allow_substring = len(self.squashed) >= min_squash_len

    def matches(self, words, squashed_name):
        n = len(self.words)
        for i in range(len(words) - n + 1):
            if words[i:i + n] == self.words:
                return True
        if self.allow_substring and self.squashed and \
                self.squashed in squashed_name:
            return True
        return False


# --------------------------------------------------------------------------
# Config and file discovery
# --------------------------------------------------------------------------

def load_config(folder):
    path = os.path.join(folder, CONFIG_NAME)
    if not os.path.exists(path):
        sys.exit(f"No {CONFIG_NAME} in {folder}. Run 'scan' first to create one.")
    with open(path, encoding="utf-8") as f:
        try:
            cfg = json.load(f, object_pairs_hook=collections.OrderedDict)
        except json.JSONDecodeError as e:
            sys.exit(f"{CONFIG_NAME} is not valid JSON: {e}\n"
                     "Tip: every keyword needs quotes and a comma between items.")
    cfg.setdefault("rules", collections.OrderedDict())
    cfg.setdefault("ignore_words", [])
    cfg.setdefault("leftovers_folder", "_to sort")
    cfg.setdefault("min_group_size", 3)
    cfg.setdefault("min_substring_length", 6)
    return cfg


def ignore_set(cfg):
    return DEFAULT_IGNORE | {w.lower() for w in cfg.get("ignore_words", [])}


SYSTEM_DIRS = {"$recycle.bin", "system volume information", "__pycache__",
               "node_modules"}


def find_images(folder, top_only=False):
    """Yield paths (relative to folder, with '/') of all images, including
    every subfolder unless top_only is set. Hidden and system folders are
    skipped."""
    for root, dirs, files in os.walk(folder):
        rel_root = os.path.relpath(root, folder)
        rel_root = "" if rel_root == "." else rel_root.replace(os.sep, "/")
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                yield f"{rel_root}/{name}" if rel_root else name
        if top_only:
            break
        dirs[:] = sorted(d for d in dirs
                         if not d.startswith((".", "$"))
                         and d.lower() not in SYSTEM_DIRS)


def folder_parts(rel):
    """'a/b/c.jpg' -> ['a', 'b']"""
    return rel.split("/")[:-1]


def under(path, base):
    """True if folder path is base or inside it (case-insensitive)."""
    p, b = path.lower().strip("/"), base.lower().strip("/")
    return p == b or p.startswith(b + "/")


def already_sorted(rel, cfg):
    """An image counts as sorted when it sits in a rule's destination folder
    or in any subfolder you made inside one (e.g. people/Alexa Chung/2019)."""
    current = "/".join(folder_parts(rel))
    return any(under(current, dest) for dest in cfg["rules"])


def in_leftovers(rel, cfg):
    return under("/".join(folder_parts(rel)), cfg["leftovers_folder"])


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def cmd_scan(args):
    folder = os.path.abspath(args.folder)
    cfg_path = os.path.join(folder, CONFIG_NAME)
    existing = None
    if os.path.exists(cfg_path):
        existing = load_config(folder)
    ignore = ignore_set(existing) if existing else set(DEFAULT_IGNORE)
    files = list(find_images(folder, args.top_only))
    if not files:
        sys.exit(f"No images found in {folder}.")
    n_folders = len({"/".join(folder_parts(r)) for r in files})

    word_count = collections.Counter()
    pair_count = collections.Counter()
    examples = {}
    for rel in files:
        # Words from the filename and from every folder it sits in, so a
        # folder called "Alexa Chung" counts for all images inside it.
        names = [os.path.splitext(os.path.basename(rel))[0]] + folder_parts(rel)
        singles, pairs = set(), set()
        for name in names:
            words = [w for w in split_words(name) if not is_noise(w, ignore)]
            singles.update(words)
            pairs.update(f"{a} {b}" for a, b in zip(words, words[1:]))
        for w in singles:
            word_count[w] += 1
            examples.setdefault(w, rel)
        for pr in pairs:
            pair_count[pr] += 1
            examples.setdefault(pr, rel)

    rules = existing["rules"] if existing else STARTER_RULES
    min_sq = existing["min_substring_length"] if existing else 6
    used = [Keyword(k, min_sq) for kws in rules.values() for k in kws]

    def covered(term):
        ws = term.split()
        for kw in used:
            if kw.matches(ws, squash(term)):
                return True
            # 'alexa' alone is covered by the keyword 'alexa chung'
            n = len(ws)
            if any(kw.words[i:i + n] == ws for i in range(len(kw.words) - n + 1)):
                return True
        return False

    # Report: every word or word pair seen in at least 2 files.
    rows = []
    for term, n in list(word_count.items()) + list(pair_count.items()):
        if n >= 2:
            rows.append((n, term, "yes" if covered(term) else "", examples[term]))
    rows.sort(key=lambda r: (-r[0], r[1]))
    report_path = os.path.join(folder, REPORT_NAME)
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv_writer(f)
        w.writerow(["files", "word", "already_in_a_rule", "example_file"])
        w.writerows(rows)

    suggestions = [r[1] for r in rows if not r[2]][:args.suggestions]

    if existing:
        existing["suggestions"] = suggestions
        cfg = existing
        action = "Updated the suggestions in"
    else:
        cfg = collections.OrderedDict([
            ("_help", STARTER_CONFIG_HELP),
            ("rules", STARTER_RULES),
            ("suggestions", suggestions),
            ("ignore_words", []),
            ("leftovers_folder", "_to sort"),
            ("min_group_size", 3),
            ("min_substring_length", 6),
        ])
        action = "Created"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Scanned {len(files)} images in {n_folders} folders under {folder}")
    print(f"{action} {CONFIG_NAME}")
    print(f"Wrote {REPORT_NAME} ({len(rows)} recurring words and word pairs)")
    print("\nMost frequent words that no rule uses yet:")
    for term in suggestions[:25]:
        print(f"  {word_count.get(term) or pair_count.get(term):>5}  {term}")
    print(f"\nNext: add useful words to the rules in {CONFIG_NAME}, "
          "then run 'plan' to preview.")


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def group_leftovers(leftovers, ignore, min_size):
    """
    Group leftover files by a shared recurring word, prefix or infix.

    Returns {file: group_name}. Files that share nothing stay unassigned.
    Bigger, more specific groups are formed first; each file joins only one.
    """
    file_terms = {}
    for rel in leftovers:
        stem = os.path.splitext(os.path.basename(rel))[0]
        words = split_words(stem)
        terms = set()
        clean = [w for w in words if not is_noise(w, ignore)]
        terms.update(clean)
        terms.update(f"{a} {b}" for a, b in zip(clean, clean[1:]))
        # Prefix: the text before the first run of digits, e.g. 'IMG_' is
        # ignored, but 'paris_trip_' or 'SS23-look' are kept.
        m = re.match(r"([^\d]+)", stem)
        if m:
            pre = " ".join(w for w in split_words(m.group(1))
                           if not is_noise(w, ignore))
            if pre:
                terms.add(pre)
        file_terms[rel] = terms

    counts = collections.Counter(t for ts in file_terms.values() for t in ts)
    # Prefer more files, then more words (more specific), then alphabetical.
    candidates = sorted((t for t, n in counts.items() if n >= min_size),
                        key=lambda t: (-counts[t], -len(t.split()), t))
    assigned = {}
    for term in candidates:
        members = [f for f, ts in file_terms.items()
                   if term in ts and f not in assigned]
        if len(members) >= min_size:
            for f in members:
                assigned[f] = term
    return assigned


def safe_folder_name(text):
    text = re.sub(r'[<>:"/\\|?*]+', " ", text).strip(" .")
    return text or "group"


def cmd_plan(args):
    folder = os.path.abspath(args.folder)
    cfg = load_config(folder)
    ignore = ignore_set(cfg)
    min_sq = int(cfg["min_substring_length"])
    rules = [(dest, [Keyword(k, min_sq) for k in kws])
             for dest, kws in cfg["rules"].items()]

    all_files = list(find_images(folder, args.top_only))
    # Images already in a destination folder stay where they are, unless
    # --resort is given. Images in the leftovers folder are always re-checked,
    # so a re-run with new keywords pulls them out of "_to sort".
    files = all_files if args.resort else \
        [f for f in all_files if not already_sorted(f, cfg)]
    if not files:
        sys.exit(f"No images to sort ({len(all_files)} are already sorted).")

    plan = []          # (file, destination folder, reason)
    leftovers = []
    for rel in files:
        stem = os.path.splitext(os.path.basename(rel))[0]
        # Try the filename first, then the folders it sits in, innermost first,
        # so "Alexa Chung/IMG_0001.jpg" still goes to people/Alexa Chung.
        # The leftovers folder's own name is not a keyword source.
        parents = folder_parts(rel)
        if in_leftovers(rel, cfg):
            parents = parents[len(cfg["leftovers_folder"].strip("/").split("/")):]
        # A folder match keeps the subfolders below the matched folder, so
        # "Alexa Chung/2019/x.jpg" goes to "people/Alexa Chung/2019".
        sources = [("keyword", stem, [])] + \
            [("folder keyword", parents[i], parents[i + 1:])
             for i in reversed(range(len(parents)))]
        hit = None
        for label, name, below in sources:
            words, sq = split_words(name), squash(name)
            for dest, kws in rules:
                for kw in kws:
                    if kw.matches(words, sq):
                        hit = ("/".join([dest] + below), f"{label}: {kw.raw}")
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            plan.append([rel, hit[0], hit[1]])
        else:
            leftovers.append(rel)

    groups = {} if args.no_groups else \
        group_leftovers(leftovers, ignore, int(cfg["min_group_size"]))
    base = cfg["leftovers_folder"].rstrip("/")
    for rel in leftovers:
        if rel in groups:
            g = groups[rel]
            plan.append([rel, f"{base}/{safe_folder_name(g)}",
                         f"shared word: {g}"])
        else:
            # Keep images from the same original folder together, so the
            # context of a folder like "Paris 2019" is not lost.
            parents = folder_parts(rel)
            if in_leftovers(rel, cfg):
                parents = parents[len(base.split("/")):]
                if parents and parents[0] == "_no pattern":
                    parents = parents[1:]
            if parents:
                plan.append([rel, f"{base}/" + "/".join(parents),
                             "no keyword, kept with its folder"])
            else:
                plan.append([rel, f"{base}/_no pattern",
                             "no keyword or pattern"])

    # Files already in their destination need no move.
    rows = []
    for rel, dest, reason in plan:
        current = os.path.dirname(rel)
        if current.lower() == dest.lower():
            continue
        rows.append([rel, dest, reason])

    plan_path = os.path.join(folder, PLAN_NAME)
    with open(plan_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv_writer(f)
        w.writerow(["file", "move_to", "reason"])
        w.writerows(rows)

    by_dest = collections.Counter(r[1] for r in rows)
    matched = sum(1 for r in rows if r[2].startswith("keyword"))
    by_folder = sum(1 for r in rows if r[2].startswith("folder keyword"))
    grouped = sum(1 for r in rows if r[2].startswith("shared"))
    kept = sum(1 for r in rows if r[2].endswith("kept with its folder"))
    loose = sum(1 for r in rows if r[2] == "no keyword or pattern")
    print(f"Preview for {len(all_files)} images in {folder}  "
          "(nothing was moved)\n")
    print(f"  {len(all_files) - len(files):>5}  already sorted, left alone")
    print(f"  {len(files) - len(rows):>5}  already where the plan puts them")
    print(f"  {matched:>5}  keyword in the filename")
    print(f"  {by_folder:>5}  keyword in a folder name")
    print(f"  {grouped:>5}  leftovers grouped by a shared word or prefix")
    print(f"  {kept:>5}  leftovers kept together with their original folder")
    print(f"  {loose:>5}  leftovers with no pattern\n")
    for dest, n in sorted(by_dest.items(), key=lambda x: x[0].lower()):
        print(f"  {n:>5}  {dest}")
    print(f"\nWrote {PLAN_NAME}. Open it in Excel to check or edit the "
          "'move_to' column, then run 'apply'.")


# --------------------------------------------------------------------------
# apply / undo
# --------------------------------------------------------------------------

def unique_target(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(f"{stem} ({i}){ext}"):
        i += 1
    return f"{stem} ({i}){ext}"


def remove_empty_dirs(dirs, folder):
    """Remove folders left empty by a move, walking up but never past folder."""
    for d in sorted(dirs, key=len, reverse=True):
        while os.path.abspath(d) != folder:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


def cmd_apply(args):
    folder = os.path.abspath(args.folder)
    plan_path = os.path.join(folder, PLAN_NAME)
    if not os.path.exists(plan_path):
        sys.exit(f"No {PLAN_NAME}. Run 'plan' first.")
    with open(plan_path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv_dict_reader(f) if r.get("file") and r.get("move_to")]
    if not rows:
        sys.exit("The plan is empty, nothing to move.")

    print(f"About to move {len(rows)} files inside {folder}.")
    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer not in ("yes", "y", "ja", "j"):
            sys.exit("Cancelled, nothing was moved.")

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    undo_path = os.path.join(folder, f"{UNDO_PREFIX}{stamp}.csv")
    moved = missing = failed = 0
    emptied = set()
    with open(undo_path, "w", newline="", encoding="utf-8-sig") as uf:
        uw = csv_writer(uf)
        uw.writerow(["moved_from", "moved_to"])
        for r in rows:
            src = os.path.join(folder, *r["file"].split("/"))
            dest_dir = os.path.join(folder, *r["move_to"].strip("/").split("/"))
            if not os.path.exists(src):
                missing += 1
                continue
            try:
                os.makedirs(dest_dir, exist_ok=True)
                dst = unique_target(os.path.join(dest_dir, os.path.basename(src)))
                shutil.move(src, dst)
                emptied.add(os.path.dirname(src))
                uw.writerow([os.path.relpath(src, folder).replace(os.sep, "/"),
                             os.path.relpath(dst, folder).replace(os.sep, "/")])
                uf.flush()
                moved += 1
            except OSError as e:
                failed += 1
                print(f"  could not move {r['file']}: {e}")

    remove_empty_dirs(emptied, folder)
    print(f"Moved {moved} files.")
    if missing:
        print(f"Skipped {missing} files that no longer exist.")
    if failed:
        print(f"{failed} files could not be moved (see above).")
    print(f"Undo log: {os.path.basename(undo_path)}  (run 'undo' to reverse)")


def cmd_undo(args):
    folder = os.path.abspath(args.folder)
    if args.log:
        log = os.path.join(folder, args.log)
    else:
        logs = sorted(n for n in os.listdir(folder)
                      if n.startswith(UNDO_PREFIX) and n.endswith(".csv")
                      and not n.endswith("_undone.csv"))
        if not logs:
            sys.exit("No undo log found.")
        log = os.path.join(folder, logs[-1])
    with open(log, newline="", encoding="utf-8-sig") as f:
        rows = list(csv_dict_reader(f))

    print(f"About to move {len(rows)} files back, using {os.path.basename(log)}.")
    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer not in ("yes", "y", "ja", "j"):
            sys.exit("Cancelled.")

    restored = 0
    touched_dirs = set()
    for r in reversed(rows):
        cur = os.path.join(folder, *r["moved_to"].split("/"))
        orig = os.path.join(folder, *r["moved_from"].split("/"))
        if not os.path.exists(cur):
            print(f"  missing, skipped: {r['moved_to']}")
            continue
        os.makedirs(os.path.dirname(orig), exist_ok=True)
        shutil.move(cur, unique_target(orig))
        touched_dirs.add(os.path.dirname(cur))
        restored += 1

    remove_empty_dirs(touched_dirs, folder)

    os.replace(log, log[:-4] + "_undone.csv")
    print(f"Moved {restored} files back.")


# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Sort images into folders by keywords in their filenames.",
        epilog="Run the steps in order: scan, plan, apply. 'undo' reverses apply.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("folder", nargs="?", default=".",
                        help="image folder (default: the current folder); "
                             "all subfolders are included")
        sp.add_argument("--top-only", action="store_true",
                        help="only look at images directly in the folder, "
                             "not in subfolders")
        # Subfolders are always included now; -r is accepted for old habits.
        sp.add_argument("-r", "--recursive", action="store_true",
                        help=argparse.SUPPRESS)

    s = sub.add_parser("scan", help="count filename words, create keywords.json")
    add_common(s)
    s.add_argument("--suggestions", type=int, default=150,
                   help="how many unused frequent words to list (default 150)")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("plan", help="preview where every image would go")
    add_common(s)
    s.add_argument("--resort", action="store_true",
                   help="also re-check images already in sorted folders")
    s.add_argument("--no-groups", action="store_true",
                   help="do not group leftovers by shared words")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("apply", help="move files as written in sort_plan.csv")
    s.add_argument("folder", nargs="?", default=".")
    s.add_argument("-y", "--yes", action="store_true",
                   help="do not ask for confirmation")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("undo", help="reverse the last apply")
    s.add_argument("folder", nargs="?", default=".")
    s.add_argument("--log", help="a specific undo_log_*.csv to use")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_undo)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
