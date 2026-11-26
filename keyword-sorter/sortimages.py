#!/usr/bin/env python3
"""
sortimages.py - sort an image folder into folders by keywords in the filenames.

Only needs Python 3.8+ (no extra packages). Works on Windows, macOS and Linux.

Workflow (pass the image folder the first time; keywords.json remembers it):

  1. py sortimages.py scan      Count the words in the filenames of everything
                                not sorted yet and write keywords.json (starter
                                rules), a word report and a folder list.
  2. py sortimages.py learn     Go through the best suggested words one by one
                                and say what each is (b = brand, p = person,
                                ...). Each answer becomes a rule.
  3. py sortimages.py plan      Preview: decide a destination for every image
                                in _to sort and anything new, and write
                                sort_plan.csv. Nothing is moved.
  4. py sortimages.py apply     Move the files exactly as sort_plan.csv says
                                (you may edit the CSV first). Writes an undo log.
  5. py sortimages.py undo      Put everything back using the newest undo log.

  update-rules adds the built-in rules of a new version to your keywords.json.

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
FOLDER_REPORT_NAME = "folder_report.csv"
PLAN_NAME = "sort_plan.csv"
ERRORS_NAME = "apply_errors.csv"
UNDO_PREFIX = "undo_log_"
LEARN_LOG_NAME = "learn_log.csv"

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

# Folders as they are in the image collection (paths use "/").
GENERATED = "fashion/generated"
COLLAGES = "fashion/collages"
SOCIAL = "fashion/social media"
ITEMS = "fashion/fashion misc"
MOVIES = "misc/screenshots/movies"
SCREENSHOTS = "misc/screenshots"

# Starter rules. Folder paths use "/" and are created inside the image folder.
# The FIRST matching rule wins:
#   AI images and collages first (whatever they show), then movie stills,
#   then people, specific fashion weeks, magazines and brands, then the
#   general street style and editorial folders, social media, fashion items
#   without a brand, and last other screenshots.
STARTER_RULES = collections.OrderedDict([
    # Sora's images are named like "..._remix_01k0as..." or "..._simple_compose_..".
    # Bing Image Creator's are named "OIG1.jpg" ("OIP" is Bing image search,
    # not AI, so it is not here).
    (GENERATED, ["grok", "chatgpt", "chat gpt", "gpt", "oig", "dalle",
                 "dall e", "midjourney", "openai", "ai generated",
                 "aigenerated", "stable diffusion", "remix",
                 "simple compose"]),
    (COLLAGES, ["collage", "collages"]),
    (MOVIES, ["strange darling", "strange darlings", "clueless", "the mask",
              "prime video", "vlcsnap"]),

    ("people/Alexa Chung", ["alexa chung", "alexachung"]),
    ("people/Cara Delevingne", ["cara delevingne", "delevingne"]),
    ("people/Hailee Steinfeld", ["hailee steinfeld", "steinfeld", "hailee"]),
    ("people/Kendall Jenner", ["kendall jenner"]),
    ("people/Kristen Stewart", ["kristen stewart"]),
    ("people/Chloe Grace Moretz", ["chloe grace moretz", "chloe moretz",
                                   "moretz"]),
    ("people/Keira Knightley", ["keira knightley", "knightley"]),
    ("people/Ashley Benson", ["ashley benson"]),
    ("people/Helene Bockhorst", ["helene bockhorst", "bockhorst"]),

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
    # hmgoepprod / hmprod is how H&M's own product photos are named.
    ("fashion/brands/H&M", ["h&m", "hm", "hennes", "hmgoepprod", "hmprod"]),
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
    ("fashion/brands/Massimo Dutti", ["massimo dutti", "massimo", "dutti"]),
    ("fashion/brands/ASOS", ["asos"]),
    ("fashion/brands/Madewell", ["madewell"]),
    ("fashion/brands/Whistles", ["whistles"]),
    ("fashion/brands/Zadig & Voltaire", ["zadig voltaire", "zadig"]),
    ("fashion/brands/AllSaints", ["all saints", "allsaints"]),
    ("fashion/brands/Topshop", ["topshop"]),
    ("fashion/brands/Burberry", ["burberry"]),
    ("fashion/brands/Belstaff", ["belstaff"]),
    ("fashion/brands/Mackage", ["mackage"]),
    ("fashion/brands/Anine Bing", ["anine bing"]),
    ("fashion/brands/Rag & Bone", ["rag bone", "rag & bone", "ragandbone"]),
    ("fashion/brands/Free People", ["free people"]),
    ("fashion/brands/Muubaa", ["muubaa"]),
    ("fashion/brands/Balmain", ["balmain"]),
    ("fashion/brands/Bershka", ["bershka"]),
    ("fashion/brands/Isabel Marant", ["isabel marant", "marant"]),
    ("fashion/brands/Vero Moda", ["vero moda"]),
    ("fashion/brands/Ralph Lauren", ["ralph lauren"]),
    ("fashion/brands/Nasty Gal", ["nasty gal"]),
    ("fashion/brands/Schott", ["schott"]),
    ("fashion/brands/Nili Lotan", ["nili lotan"]),
    ("fashion/brands/Pull & Bear", ["pull bear", "pull & bear", "pullandbear"]),
    ("fashion/brands/Maje", ["maje"]),
    ("fashion/brands/Balenciaga", ["balenciaga"]),
    ("fashion/brands/J.Crew", ["jcrew", "j crew"]),
    ("fashion/brands/BlankNYC", ["blanknyc"]),

    # General folders after the specific ones, so a brand or magazine wins.
    ("fashion/street style", ["street style", "streetstyle", "streetwear",
                              "street snap", "fashion week", "fw",
                              "styledumonde"]),
    ("fashion/editorial", ["editorial", "magazine", "cover", "photoshoot",
                           "shoot", "campaign", "lookbook"]),

    (SOCIAL, ["instagram", "insta", "snapinsta", "tumblr", "pinterest",
              "facebook", "twitter", "tiktok", "snapchat"]),

    # Fashion items without a brand, e.g. "leather jacket". Also the German,
    # French, Spanish, Italian and Polish words that are common in filenames.
    (ITEMS, ["leather jacket", "leather", "jacket", "jackets", "coat", "trench",
             "blazer", "bomber", "parka", "puffer", "shearling", "blouson",
             "perfecto", "dress", "skirt", "jeans", "denim", "trousers",
             "pants", "leggings", "shirt", "blouse", "sweater", "knitwear",
             "cardigan", "hoodie", "boots", "loafers", "sneakers", "heels",
             "sandals", "handbag", "scarf", "gloves", "sunglasses", "outfit",
             "ootd", "faux fur", "vinyl", "lederjacke", "jacke", "cuir",
             "chaqueta", "cazadora", "cuero", "piel", "pelle", "kurtka"]),

    (SCREENSHOTS, ["screenshot", "screen shot", "bildschirmfoto",
                   "capture", "snip", "scrnli"]),
])

# Where a new rule goes in the list (lower = checked earlier). 'learn' uses
# this so a new brand lands next to the other brands, before the general
# fashion folders. Exact folders first, then the longest matching start.
RULE_RANKS_EXACT = {
    GENERATED: 0, COLLAGES: 1, MOVIES: 2,
    "fashion/street style": 7, "fashion/editorial": 8,
    SOCIAL: 9, ITEMS: 10, SCREENSHOTS: 12,
}
RULE_RANKS_PREFIX = [
    (GENERATED, 0), (COLLAGES, 1), (MOVIES, 2), ("people", 3),
    ("fashion/street style", 4), ("fashion/editorial", 5),
    ("fashion/brands", 6), (SOCIAL, 9), (ITEMS, 10), ("fashion", 10),
    (SCREENSHOTS, 12), ("misc", 13),
]


def rule_rank(dest):
    d = dest.strip("/").lower()
    for k, v in RULE_RANKS_EXACT.items():
        if d == k.lower():
            return v
    best = None
    for prefix, v in RULE_RANKS_PREFIX:
        p = prefix.lower()
        if (d == p or d.startswith(p + "/")) and \
                (best is None or len(p) > len(best[0])):
            best = (p, v)
    return best[1] if best else 11      # unknown folders: before screenshots


STARTER_CONFIG_HELP = (
    "Edit this file to teach the sorter, or run 'learn' to do it by answering "
    "questions. 'rules' maps a destination folder to the keywords that send an "
    "image there; the first matching rule wins. Keywords are not case "
    "sensitive, and 'alexa chung' also matches alexa_chung, Alexa-Chung and "
    "AlexaChung. 'never_suggest' lists words 'learn' should not offer again. "
    "'ignore_words' are left out of counts and leftover groups. "
    "'skip_folders' are never touched (for example the sorting app's _trash)."
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
    # Drop random ids before splitting, or a hash like '3f9a2c7e' would fall
    # apart into fake words ('f', 'a', 'c', 'e'). An id is a run of hex
    # characters with digits in it, or a long run that keeps switching
    # between letters and digits. 'alexachung2019' or 'SS24' are kept.
    def is_id(tok):
        if len(tok) >= 6 and re.fullmatch(r"[0-9a-fA-F]+", tok) and \
                re.search(r"\d", tok) and re.search(r"[a-fA-F]", tok):
            return True
        return len(tok) >= 8 and \
            len(re.findall(r"[A-Za-z]+|\d+", tok)) >= 5
    s = " ".join(t for t in re.split(r"[^A-Za-z0-9&]+", s) if t and not is_id(t))
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
        if self.allow_substring:
            # The keyword's letters appearing anywhere is the looser test.
            if self.squashed in squashed_name:
                return True
        if self.words[0] not in words:      # quick reject
            return False
        n = len(self.words)
        for i in range(len(words) - n + 1):
            if words[i:i + n] == self.words:
                return True
        return False


# --------------------------------------------------------------------------
# Where things are: the image folder, and the data folder that holds
# keywords.json, the reports, the plan and the undo logs.
#
# If a "logs" folder sits next to the keyword-sorter folder (as in the
# image-organizer project, where logs/ is never uploaded to GitHub), that is
# the data folder. Otherwise the files go into the image folder itself.
# keywords.json remembers the image folder, so after the first run
# "py sortimages.py plan" is enough.
# --------------------------------------------------------------------------

def default_data_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    logs = os.path.join(os.path.dirname(here), "logs")
    return logs if os.path.isdir(logs) else None


def resolve_paths(args, need_config=True, need_folder=True):
    """Return (image_folder, data_dir, cfg or None)."""
    data = getattr(args, "data", None) or default_data_dir()
    given = getattr(args, "folder", None)
    if data is None:
        data = given or "."
    data = os.path.abspath(data)
    cfg = None
    if os.path.exists(os.path.join(data, CONFIG_NAME)):
        cfg = load_config(data)
    elif need_config:
        sys.exit(f"No {CONFIG_NAME} in {data}. Run 'scan' first to create one.")
    folder = given or (cfg or {}).get("image_folder") or "."
    folder = os.path.abspath(folder)
    if need_folder and not os.path.isdir(folder):
        sys.exit(f"Image folder not found: {folder}\n"
                 "Pass the image folder, e.g. "
                 r"py sortimages.py plan C:\Users\me\Pictures\collection")
    if cfg is not None and need_folder:
        cfg["image_folder"] = folder
    return folder, data, cfg


def load_config(data_dir):
    path = os.path.join(data_dir, CONFIG_NAME)
    if not os.path.exists(path):
        sys.exit(f"No {CONFIG_NAME} in {data_dir}. Run 'scan' first to create one.")
    with open(path, encoding="utf-8") as f:
        try:
            cfg = json.load(f, object_pairs_hook=collections.OrderedDict)
        except json.JSONDecodeError as e:
            sys.exit(f"{CONFIG_NAME} is not valid JSON: {e}\n"
                     "Tip: every keyword needs quotes and a comma between items.")
    cfg.setdefault("rules", collections.OrderedDict())
    cfg.setdefault("ignore_words", [])
    cfg.setdefault("never_suggest", [])
    cfg.setdefault("skip_folders", ["_trash"])
    cfg.setdefault("leftovers_folder", "_to sort")
    cfg.setdefault("min_group_size", 3)
    cfg.setdefault("min_substring_length", 6)
    return cfg


def save_config(cfg, data_dir):
    path = os.path.join(data_dir, CONFIG_NAME)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def ignore_set(cfg):
    return DEFAULT_IGNORE | {w.lower() for w in cfg.get("ignore_words", [])}


SYSTEM_DIRS = {"$recycle.bin", "system volume information", "__pycache__",
               "node_modules"}


def find_images(folder, top_only=False, prune=None):
    """Yield paths (relative to folder, with '/') of all images, including
    every subfolder unless top_only is set. Hidden and system folders are
    skipped, and so is every folder for which prune(relative path) is True:
    those are not even opened, which is what makes a re-run fast."""
    for root, dirs, files in os.walk(folder):
        rel_root = os.path.relpath(root, folder)
        rel_root = "" if rel_root == "." else rel_root.replace(os.sep, "/")
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                yield f"{rel_root}/{name}" if rel_root else name
        if top_only:
            break
        keep = []
        for d in sorted(dirs):
            if d.startswith((".", "$")) or d.lower() in SYSTEM_DIRS:
                continue
            if prune and prune(f"{rel_root}/{d}" if rel_root else d):
                continue
            keep.append(d)
        dirs[:] = keep


def folder_parts(rel):
    """'a/b/c.jpg' -> ['a', 'b']"""
    return rel.split("/")[:-1]


def under(path, base):
    """True if folder path is base or inside it (case-insensitive)."""
    p, b = path.lower().strip("/"), base.lower().strip("/")
    return p == b or p.startswith(b + "/")


def sorted_areas(cfg):
    """The top folders your rules sort into, e.g. people, fashion, misc.
    Everything inside them counts as sorted, also folders you made there by
    hand (like people/Some Name) that no rule knows about."""
    left = cfg["leftovers_folder"].strip("/").split("/")[0].lower()
    tops = {d.strip("/").split("/")[0] for d in cfg["rules"]}
    return sorted(t for t in tops if t and t.lower() != left)


def make_pruner(cfg, include_sorted=False):
    """Folders the sorter never needs to open: skip_folders (like _trash)
    always, and the sorted areas unless include_sorted is set. What is left
    is the leftovers folder and anything new you dropped into the image
    folder."""
    skip = [s for s in cfg.get("skip_folders", []) if s.strip("/")]
    areas = [] if include_sorted else sorted_areas(cfg)

    def prune(rel_dir):
        return any(under(rel_dir, s) for s in skip) or \
            any(under(rel_dir, a) for a in areas)
    return prune


def already_sorted(rel, cfg):
    """An image counts as sorted when it sits in a sorted area (see
    sorted_areas), e.g. people/Alexa Chung/2019 or fashion/brands/Zara."""
    current = "/".join(folder_parts(rel))
    return any(under(current, a) for a in sorted_areas(cfg))


def in_leftovers(rel, cfg):
    return under("/".join(folder_parts(rel)), cfg["leftovers_folder"])


# --------------------------------------------------------------------------
# scan
# --------------------------------------------------------------------------

def cmd_scan(args):
    folder, data, existing = resolve_paths(args, need_config=False)
    os.makedirs(data, exist_ok=True)
    ignore = ignore_set(existing) if existing else set(DEFAULT_IGNORE)
    # Once rules exist, only what is still unsorted is counted (the
    # leftovers folder and anything new), unless --all is given. That keeps a
    # re-scan fast and the suggestions about what is left to sort.
    if existing:
        prune = make_pruner(existing, include_sorted=args.all)
    else:
        prune = make_pruner({"skip_folders": ["_trash"], "rules": {},
                             "leftovers_folder": "_to sort"})
    files = list(find_images(folder, args.top_only, prune))
    if not files:
        sys.exit(f"No images found in {folder}.")
    n_folders = len({"/".join(folder_parts(r)) for r in files})

    # Suggestions come from filenames only. Folder names are listed in a
    # separate report: counting them once per image would just rank the
    # biggest folders first.
    word_count = collections.Counter()
    pair_count = collections.Counter()
    word_folders = collections.defaultdict(set)
    examples = {}
    folder_images = collections.Counter()
    for rel in files:
        parent = "/".join(folder_parts(rel))
        folder_images[parent] += 1
        stem = os.path.splitext(os.path.basename(rel))[0]
        words = [w for w in split_words(stem) if not is_noise(w, ignore)]
        for w in set(words):
            word_count[w] += 1
            word_folders[w].add(parent)
            examples.setdefault(w, rel)
        for pr in set(f"{a} {b}" for a, b in zip(words, words[1:])):
            pair_count[pr] += 1
            word_folders[pr].add(parent)
            examples.setdefault(pr, rel)

    rules = existing["rules"] if existing else STARTER_RULES
    min_sq = existing["min_substring_length"] if existing else 6
    used = rule_keywords(rules, min_sq)

    # Report: every word or word pair seen in at least 2 files.
    rows = []
    for term, n in list(word_count.items()) + list(pair_count.items()):
        # Two-letter words alone ('de', 'ss') are too vague to suggest.
        if n >= 2 and (" " in term or len(term) >= 3):
            rows.append((n, len(word_folders[term]), term,
                         "yes" if term_covered(term, used) else "",
                         examples[term]))
    rows.sort(key=lambda r: (-r[0], r[2]))
    with open(os.path.join(data, REPORT_NAME), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv_writer(f)
        w.writerow(["files", "folders", "word", "already_in_a_rule",
                    "example_file"])
        w.writerows(rows)

    with open(os.path.join(data, FOLDER_REPORT_NAME), "w", newline="",
              encoding="utf-8-sig") as f:
        w = csv_writer(f)
        w.writerow(["folder", "images"])
        for name, n in sorted(folder_images.items(), key=lambda x: x[0].lower()):
            w.writerow([name or "(top folder)", n])

    if existing:
        cfg = existing
        action = "Updated the suggestions in"
    else:
        cfg = collections.OrderedDict([
            ("_help", STARTER_CONFIG_HELP),
            ("image_folder", folder),
            ("rules", STARTER_RULES),
            ("suggestions", []),
            ("never_suggest", []),
            ("ignore_words", []),
            ("skip_folders", ["_trash"]),
            ("leftovers_folder", "_to sort"),
            ("min_group_size", 3),
            ("min_substring_length", 6),
        ])
        action = "Created"
    report = [ReportRow(r[2], r[0], r[1], r[4]) for r in rows]
    cands = rank_candidates(report, cfg)[:args.suggestions]
    cfg["suggestions"] = [c.term for c in cands]
    save_config(cfg, data)

    what = "unsorted images" if existing and not args.all else "images"
    print(f"Scanned {len(files)} {what} in {n_folders} folders under {folder}")
    print(f"{action} {CONFIG_NAME} in {data}")
    print(f"Wrote {REPORT_NAME} ({len(rows)} recurring filename words "
          "and word pairs)")
    print(f"Wrote {FOLDER_REPORT_NAME} ({n_folders} folders "
          "with image counts)")
    print("\nBest candidates for new rules (run 'learn' to turn them into rules):")
    print("  files  folders  word")
    for c in cands[:25]:
        print(f"  {c.files:>5}  {c.folders:>7}  {c.term}")
    print("\nNext: 'learn' to add rules by answering questions, "
          "then 'plan' to preview.")


# --------------------------------------------------------------------------
# Suggestions: which words from keyword_report.csv are worth a rule
# --------------------------------------------------------------------------

# Common words that are never a useful folder, even with 4+ letters.
STOP_WORDS = {
    "with", "from", "this", "that", "what", "when", "where", "who", "will",
    "your", "they", "them", "their", "have", "about", "after", "before",
    "into", "over", "just", "like", "more", "most", "best", "some", "here",
    "there", "very", "also", "only", "then", "than", "were", "been", "does",
    "goes", "wears", "wearing", "seen", "look", "looks", "style", "fashion",
    "women", "womens", "woman", "girl", "girls", "lady", "free", "online",
    "shop", "sale", "size", "color", "colour", "black", "white", "blue",
    "brown", "green", "grey", "gray", "pink", "dark", "light", "long",
    "short", "high", "real", "true", "best", "default", "product", "normal",
    "large", "medium", "small", "main", "front", "back", "detail", "details",
    "scaled", "fullsize", "upload", "assets", "asset", "thumb", "media",
    "com", "www", "html", "http", "https", "jpg", "jpeg", "png", "webp",
    "und", "mit", "auf", "ist", "für", "der", "die", "das", "ein",
    "eine", "los", "las", "del", "con", "para", "pour", "avec", "des",
    "les", "une", "dans", "january", "february", "march", "april", "june",
    "july", "august", "september", "october", "november", "december",
    "juni", "juli", "sept", "spring", "summer", "autumn", "winter", "fall",
    "season", "collection", "video", "videos", "photo", "photos", "image",
    "images", "picture", "pictures", "fotos", "bild", "bilder",
}


class ReportRow:
    __slots__ = ("term", "files", "folders", "example")

    def __init__(self, term, files, folders, example):
        self.term, self.files, self.folders, self.example = \
            term, int(files), int(folders), example


class Candidate:
    """A term offered for a new rule. A compound ('massimo dutti') is a word
    pair that mostly appears together."""

    def __init__(self, row, compound=False, score=None):
        self.row = row
        self.term = row.term
        self.files = row.files
        self.folders = row.folders
        self.example = row.example
        self.compound = compound
        self.score = row.files if score is None else score


def read_report(data_dir):
    path = os.path.join(data_dir, REPORT_NAME)
    if not os.path.exists(path):
        sys.exit(f"No {REPORT_NAME} in {data_dir}. Run 'scan' first.")
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv_dict_reader(f):
            try:
                rows.append(ReportRow(r["word"].strip().lower(), r["files"],
                                      r["folders"], r.get("example_file", "")))
            except (KeyError, ValueError, AttributeError):
                continue
    return rows


def rule_keywords(rules, min_sq):
    return [Keyword(k, min_sq) for kws in rules.values() for k in kws]


def term_covered(term, keywords):
    """True if a rule already catches this term, e.g. 'alexa chung', or
    'alexa' alone because it is part of the keyword 'alexa chung'."""
    ws = term.split()
    sq = squash(term)
    n = len(ws)
    for kw in keywords:
        if kw.matches(ws, sq):
            return True
        if any(kw.words[i:i + n] == ws for i in range(len(kw.words) - n + 1)):
            return True
    return False


def useful_word(w, ignore):
    """Words of 3 letters or less (oip, ux, de) are never offered alone."""
    return len(w) >= 4 and not w.isdigit() and w not in STOP_WORDS and \
        not is_noise(w, ignore)


class CoverCache:
    """Remembers which report terms the rules already cover, so 'learn' only
    has to test the keywords added since the last question."""

    def __init__(self):
        self.keys = set()
        self.covered = set()

    def update(self, terms, used):
        keys = {k.raw.lower() for k in used}
        if not self.keys <= keys:          # keywords were removed (undo)
            self.keys, self.covered = set(), set()
        new = [k for k in used if k.raw.lower() not in self.keys]
        if new:
            for t in terms:
                if t not in self.covered and term_covered(t, new):
                    self.covered.add(t)
        self.keys = keys
        return self.covered


def rank_candidates(report, cfg, skipped=(), min_files=5, compound_share=0.5,
                    cache=None):
    """Order the report's terms by how useful a rule for them would be.

    - Terms a rule already covers, terms in never_suggest and terms skipped in
      this session are left out, so the next best ones move up.
    - Single words need 4+ letters and must not be a common word.
    - A word pair counts as a compound when at least compound_share of the
      files with its rarer word have the pair (massimo dutti: 267 of 274).
      Compounds come first: right before their own words, and words that
      almost only appear inside the compound are held back until it is
      decided.
    """
    ignore = ignore_set(cfg)
    used = rule_keywords(cfg["rules"], int(cfg.get("min_substring_length", 6)))
    never = {t.lower() for t in cfg.get("never_suggest", [])} | set(skipped)
    by_term = {r.term: r for r in report}
    big = [r for r in report if r.files >= min_files and r.term not in never]
    covered = (cache or CoverCache()).update([r.term for r in big], used)
    open_rows = [r for r in big if r.term not in covered]

    alone_cache = {}

    def matched_alone(w):
        if w not in alone_cache:
            sq = squash(w)
            alone_cache[w] = any(kw.matches([w], sq) for kw in used)
        return alone_cache[w]

    # A word that nearly always comes with one partner ('tube' in 'you tube')
    # belongs to that pair; it does not form other compounds.
    owner = {}
    for r in report:
        ws = r.term.split()
        if len(ws) != 2:
            continue
        for w in ws:
            s = by_term.get(w)
            if s and r.files >= 0.8 * s.files and \
                    r.files > by_term.get(owner.get(w, ""), ReportRow("", 0, 0, "")).files:
                owner[w] = r.term

    cands, held_back = [], set()
    for r in open_rows:
        ws = r.term.split()
        if len(ws) != 2 or not any(useful_word(w, ignore) for w in ws) or \
                any(is_noise(w, ignore) or w in STOP_WORDS for w in ws):
            continue
        if any(owner.get(w, r.term) != r.term for w in ws):
            continue
        # 'de strange' or 'leather biker': a 1-2 letter word, or a word a
        # rule already matches on its own (those files are sorted anyway).
        if any(len(w) < 3 or matched_alone(w) for w in ws):
            continue
        singles = [by_term.get(w) for w in ws]
        counts = [x.files for x in singles if x]
        if not counts or r.files < compound_share * min(counts):
            continue
        # Preferred over single words: counted double, but never ahead of
        # its own more frequent word.
        score = min(2 * r.files, max(counts) + 0.5)
        cands.append(Candidate(r, compound=True, score=score))
        for w in ws:
            if owner.get(w) == r.term:
                held_back.add(w)
    for r in open_rows:
        if " " in r.term or not useful_word(r.term, ignore):
            continue
        if r.term in held_back:
            continue
        cands.append(Candidate(r))
    cands.sort(key=lambda c: (-c.score, c.term))
    return cands


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def match_rules(rules, name):
    """Return (destination, keyword) of the first rule matching name."""
    words, sq = split_words(name), squash(name)
    for dest, kws in rules:
        for kw in kws:
            if kw.matches(words, sq):
                return dest, kw.raw
    return None


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


WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | \
    {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def safe_folder_name(text):
    """Make one folder name valid on Windows: no <>:"/\\|?* or control
    characters, no trailing spaces or dots (Windows drops them, and then the
    move fails with WinError 267), and no reserved names like CON or AUX."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.split(".")[0].lower() in WINDOWS_RESERVED:
        text += "_"
    return text or "_"


def safe_folder_path(path):
    """'people/Alexa Chung ./2019' -> 'people/Alexa Chung/2019'"""
    parts = [p for p in re.split(r"[/\\]+", path.strip()) if p.strip(" .")]
    return "/".join(safe_folder_name(p) for p in parts)


def long_path(path):
    """On Windows, paths over 260 characters fail unless written as
    \\\\?\\C:\\... . Elsewhere the path is returned unchanged."""
    if os.name != "nt":
        return path
    path = os.path.abspath(path)
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def blocking_file(folder, rel_dir):
    """Return the part of rel_dir that exists as a file instead of a folder."""
    cur = folder
    for part in rel_dir.split("/"):
        cur = os.path.join(cur, part)
        if os.path.isfile(long_path(cur)):
            return os.path.relpath(cur, folder)
    return None


def cmd_plan(args):
    folder, data, cfg = resolve_paths(args)
    save_config(cfg, data)           # remembers the image folder
    ignore = ignore_set(cfg)
    min_sq = int(cfg["min_substring_length"])
    rules = [(dest, [Keyword(k, min_sq) for k in kws])
             for dest, kws in cfg["rules"].items()]

    # Only the leftovers folder and anything new are opened: the sorted
    # folders (people, fashion, misc, ...) are not even listed, and neither
    # are skip_folders like _trash. --resort opens the sorted ones too.
    # So a rule that already did its job costs nothing on the next run, and
    # it still catches new images that show up later.
    files = list(find_images(folder, args.top_only,
                             make_pruner(cfg, include_sorted=args.resort)))
    all_files = files
    if not files:
        sys.exit("No images to sort: everything is in a sorted folder.")

    plan = []          # (file, destination folder, reason)
    leftovers = []
    folder_cache = {}
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
            # Folder names repeat for every image inside, so cache them.
            if label == "keyword" or name not in folder_cache:
                found = match_rules(rules, name)
                if label != "keyword":
                    folder_cache[name] = found
            else:
                found = folder_cache[name]
            if found:
                dest, kw = found
                hit = ("/".join([dest] + below), f"{label}: {kw}")
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
        dest = safe_folder_path(dest)
        current = os.path.dirname(rel)
        if current.lower() == dest.lower():
            continue
        rows.append([rel, dest, reason])

    plan_path = os.path.join(data, PLAN_NAME)
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
    if not args.resort:
        print("  Sorted folders not opened: "
              + ", ".join(sorted_areas(cfg)) + " (use --resort to include them)")
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
    if not os.path.exists(long_path(path)):
        return path
    stem, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(long_path(f"{stem} ({i}){ext}")):
        i += 1
    return f"{stem} ({i}){ext}"


def remove_empty_dirs(dirs, folder):
    """Remove folders left empty by a move, walking up but never past folder."""
    for d in sorted(dirs, key=len, reverse=True):
        while os.path.abspath(d) != folder:
            try:
                os.rmdir(long_path(d))
            except OSError:
                break
            d = os.path.dirname(d)


def cmd_apply(args):
    folder, data, _ = resolve_paths(args, need_config=False)
    plan_path = os.path.join(data, PLAN_NAME)
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
    undo_path = os.path.join(data, f"{UNDO_PREFIX}{stamp}.csv")
    moved = missing = 0
    errors = []        # (file, move_to, error)
    emptied = set()
    # Every move is written to the undo log right away, so 'undo' also works
    # after an apply that stopped halfway or had errors.
    with open(undo_path, "w", newline="", encoding="utf-8-sig") as uf:
        uw = csv_writer(uf)
        uw.writerow(["moved_from", "moved_to"])
        for r in rows:
            rel_dest = safe_folder_path(r["move_to"])
            src = os.path.join(folder, *r["file"].strip().split("/"))
            dest_dir = os.path.join(folder, *rel_dest.split("/"))
            if not os.path.exists(long_path(src)):
                missing += 1
                continue
            blocker = blocking_file(folder, rel_dest)
            if blocker:
                errors.append((r["file"], rel_dest,
                               f"a file is in the way: {blocker}"))
                continue
            try:
                os.makedirs(long_path(dest_dir), exist_ok=True)
                dst = unique_target(os.path.join(dest_dir, os.path.basename(src)))
                shutil.move(long_path(src), long_path(dst))
                emptied.add(os.path.dirname(src))
                uw.writerow([os.path.relpath(src, folder).replace(os.sep, "/"),
                             os.path.relpath(dst, folder).replace(os.sep, "/")])
                uf.flush()
                moved += 1
            except OSError as e:
                errors.append((r["file"], rel_dest,
                               f"{type(e).__name__}: {e.strerror or e}"
                               + (f" (WinError {e.winerror})"
                                  if getattr(e, "winerror", None) else "")))

    remove_empty_dirs(emptied, folder)
    print(f"Moved {moved} files.")
    if missing:
        print(f"Skipped {missing} files that no longer exist.")
    err_path = os.path.join(data, ERRORS_NAME)
    if not errors and os.path.exists(err_path):
        os.remove(err_path)    # left over from an earlier run
    if errors:
        with open(err_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv_writer(f)
            w.writerow(["file", "move_to", "error"])
            w.writerows(errors)
        print(f"{len(errors)} files could not be moved. All of them are listed "
              f"in {ERRORS_NAME}. The first few:")
        for file, dest, err in errors[:5]:
            print(f"  {file}\n    -> {dest}\n    {err}")
        print("Everything that did move can still be reversed with 'undo'. "
              "Run 'plan' and 'apply' again to retry the rest.")
    print(f"Undo log: {os.path.basename(undo_path)}  (run 'undo' to reverse)")


def cmd_undo(args):
    folder, data, _ = resolve_paths(args, need_config=False)
    if args.log:
        log = os.path.join(data, args.log)
    else:
        logs = sorted(n for n in os.listdir(data)
                      if n.startswith(UNDO_PREFIX) and n.endswith(".csv")
                      and not n.endswith("_undone.csv"))
        if not logs:
            sys.exit("No undo log found.")
        log = os.path.join(data, logs[-1])
    with open(log, newline="", encoding="utf-8-sig") as f:
        rows = list(csv_dict_reader(f))

    print(f"About to move {len(rows)} files back, using {os.path.basename(log)}.")
    if not args.yes:
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer not in ("yes", "y", "ja", "j"):
            sys.exit("Cancelled.")

    restored = 0
    failed = []
    touched_dirs = set()
    for r in reversed(rows):
        cur = os.path.join(folder, *r["moved_to"].split("/"))
        orig = os.path.join(folder, *r["moved_from"].split("/"))
        if not os.path.exists(long_path(cur)):
            print(f"  missing, skipped: {r['moved_to']}")
            continue
        try:
            os.makedirs(long_path(os.path.dirname(orig)), exist_ok=True)
            shutil.move(long_path(cur), long_path(unique_target(orig)))
        except OSError as e:
            failed.append(r)
            print(f"  could not move back {r['moved_to']}: {e}")
            continue
        touched_dirs.add(os.path.dirname(cur))
        restored += 1

    remove_empty_dirs(touched_dirs, folder)
    print(f"Moved {restored} files back.")
    if failed:
        # Keep only the failed rows, so running 'undo' again retries them.
        with open(log, "w", newline="", encoding="utf-8-sig") as f:
            w = csv_writer(f)
            w.writerow(["moved_from", "moved_to"])
            w.writerows([r["moved_from"], r["moved_to"]] for r in reversed(failed))
        print(f"{len(failed)} files could not be moved back. "
              "Run 'undo' again to retry them.")
    else:
        os.replace(log, log[:-4] + "_undone.csv")


# --------------------------------------------------------------------------
# learn: turn suggestions into rules by answering questions
# --------------------------------------------------------------------------

# letter: (what it is, folder). "{}" is replaced by the name, e.g.
# fashion/brands/Massimo Dutti. Folders without "{}" take everything as is;
# type a name after the letter ("i Leather Jacket") to get a subfolder.
CATEGORIES = collections.OrderedDict([
    ("p", ("person", "people/{}")),
    ("b", ("brand", "fashion/brands/{}")),
    ("e", ("editorial / magazine", "fashion/editorial/{}")),
    ("w", ("street style / fashion week", "fashion/street style/{}")),
    ("i", ("fashion item without a brand", ITEMS)),
    ("s", ("social media", SOCIAL)),
    ("g", ("AI generated", GENERATED)),
    ("c", ("collage", COLLAGES)),
    ("m", ("movie still", MOVIES)),
    ("x", ("other screenshot", SCREENSHOTS)),
])

LEARN_HELP = """
For each suggested word, type what it is and press Enter:
""" + "\n".join(f"  {k}  {v[0]:<30} -> {v[1].replace('{}', '<name>')}"
                for k, v in CATEGORIES.items()) + """

  Add a name after the letter to choose the folder name yourself:
    b ASOS            -> fashion/brands/ASOS
    i Leather Jacket  -> fashion/fashion misc/Leather Jacket
  f <folder>   any other folder, e.g.  f misc/wallpapers
  Enter        skip for now (it comes back next time)
  n            never suggest this word again
  u            undo the last answer
  ?            show this help
  q            save and quit

For two-word names like "olivia palermo" you are asked whether each word on
its own should match too:
  y  "olivia" and "palermo" alone also match (good for "massimo dutti")
  n  only the second word alone: "palermo" (good when there is also an
     "olivia wilde"). The full "olivia palermo" always matches.
  1  only the first word alone      0  only the full name

Everything is saved after every answer. Run 'plan' and 'apply' afterwards.
"""


def nice_name(term):
    small = {"and", "of", "the", "de", "la", "le", "von", "van", "der", "&"}
    out = []
    for i, w in enumerate(term.split()):
        out.append(w if (i and w in small) else w[:1].upper() + w[1:])
    return " ".join(out)


def add_rule(cfg, dest, keywords):
    """Add keywords to the rule for dest, creating the rule at the right
    place in the list if it is new. Returns the keywords really added."""
    rules = cfg["rules"]
    for d in rules:
        if d.lower() == dest.lower():
            have = {k.lower() for k in rules[d]}
            new = [k for k in keywords if k.lower() not in have]
            rules[d].extend(new)
            return d, new
    rank = rule_rank(dest)
    out = collections.OrderedDict()
    placed = False
    for d, kws in rules.items():
        if not placed and rule_rank(d) > rank:
            out[dest] = list(keywords)
            placed = True
        out[d] = kws
    if not placed:
        out[dest] = list(keywords)
    cfg["rules"] = out
    return dest, list(keywords)


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def cmd_learn(args):
    _, data, cfg = resolve_paths(args, need_folder=False)
    report = read_report(data)
    ignore = ignore_set(cfg)

    if args.show:
        cands = rank_candidates(report, cfg, min_files=args.min_files)
        print("  files  folders  word")
        for c in cands[:args.show]:
            mark = "  (compound)" if c.compound else ""
            print(f"  {c.files:>5}  {c.folders:>7}  {c.term}{mark}")
        return

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(data, f"keywords_backup_{stamp}.json")
    shutil.copyfile(os.path.join(data, CONFIG_NAME), backup)
    log_path = os.path.join(data, LEARN_LOG_NAME)
    new_log = not os.path.exists(log_path)

    print(LEARN_HELP)
    print(f"(A copy of your rules from before this session: "
          f"{os.path.basename(backup)})\n")

    skipped = set()
    cover = CoverCache()
    history = []        # snapshots for 'u'
    added_total = 0
    with open(log_path, "a", newline="", encoding="utf-8-sig") as lf:
        lw = csv_writer(lf)
        if new_log:
            lw.writerow(["time", "word", "answer", "folder", "keywords"])
        while True:
            cands = rank_candidates(report, cfg, skipped,
                                    min_files=args.min_files, cache=cover)
            if not cands:
                print("No more suggestions. Run 'plan' to preview.")
                break
            c = cands[0]
            print(f"[{len(cands)} left]  {c.term}   "
                  f"({c.files} files in {c.folders} folders)")
            if c.example:
                print(f"    e.g. {c.example}")
            answer = ask("    what is it? ")
            low = answer.lower()

            if low in ("q", "quit", "exit"):
                break
            if low in ("?", "h", "help"):
                print(LEARN_HELP)
                continue
            if low == "u":
                if not history:
                    print("    nothing to undo")
                    continue
                cfg["rules"], cfg["never_suggest"], skipped = history.pop()
                save_config(cfg, data)
                lw.writerow([_dt.datetime.now().isoformat(" ", "seconds"),
                             "", "undo", "", ""])
                print("    undone")
                continue

            snapshot = (json.loads(json.dumps(cfg["rules"]),
                                   object_pairs_hook=collections.OrderedDict),
                        list(cfg["never_suggest"]), set(skipped))
            if low == "":
                history.append(snapshot)
                skipped.add(c.term)
                continue
            if low == "n":
                history.append(snapshot)
                cfg["never_suggest"].append(c.term)
                save_config(cfg, data)
                lw.writerow([_dt.datetime.now().isoformat(" ", "seconds"),
                             c.term, "never", "", ""])
                lf.flush()
                continue

            letter, _, name = answer.partition(" ")
            letter, name = letter.lower(), name.strip()
            if letter == "f" and name:
                dest = name.replace("\\", "/").strip("/")
            elif "/" in answer:
                dest = answer.replace("\\", "/").strip("/")
            elif letter in CATEGORIES:
                pattern = CATEGORIES[letter][1]
                if "{}" in pattern:
                    dest = pattern.format(name or nice_name(c.term))
                else:
                    dest = f"{pattern}/{name}" if name else pattern
            else:
                print("    not understood, type ? for help")
                continue
            dest = safe_folder_path(dest)

            keywords = [c.term]
            words = c.term.split()
            if len(words) == 2:
                ok = [w for w in words if useful_word(w, ignore)]
                if ok:
                    shown = " / ".join(words)
                    yn = ask(f"    match both terms ({shown}) on their own "
                             f"too? y/n [n = only '{words[1]}'] ").lower()
                    if yn in ("y", "yes", "j", "ja"):
                        alone = words
                    elif yn == "1":
                        alone = words[:1]
                    elif yn in ("0", "p", "pair"):
                        alone = []
                    else:
                        alone = words[1:]
                    for w in alone:
                        if w in ok:
                            keywords.append(w)
                        else:
                            print(f"    '{w}' is too short or too common "
                                  "to match on its own, left out")
            history.append(snapshot)
            dest, new = add_rule(cfg, dest, keywords)
            save_config(cfg, data)
            added_total += len(new)
            lw.writerow([_dt.datetime.now().isoformat(" ", "seconds"),
                         c.term, answer, dest, ", ".join(keywords)])
            lf.flush()
            print(f"    -> {dest}: {', '.join(keywords)}\n")

    print(f"\nSaved {CONFIG_NAME}: {added_total} new keywords this session.")
    print("Next: 'plan' to preview, then 'apply'. After that, 'scan' counts "
          "only what is still in _to sort, so 'learn' suggests from what is left.")


def cmd_update_rules(args):
    """Add the built-in rules of this version to an existing keywords.json.
    Your own rules and keywords stay; new folders are put at the right place
    in the order; nothing you removed from a rule is added back unless it is
    new in this version."""
    _, data, cfg = resolve_paths(args, need_folder=False)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(data, f"keywords_backup_{stamp}.json")
    shutil.copyfile(os.path.join(data, CONFIG_NAME), backup)
    for k in ("never_suggest", "skip_folders"):
        cfg.setdefault(k, [])
    if "_trash" not in [x.lower() for x in cfg["skip_folders"]]:
        cfg["skip_folders"].append("_trash")
    cfg["_help"] = STARTER_CONFIG_HELP
    n_rules = n_kw = 0
    for dest, kws in STARTER_RULES.items():
        existed = any(d.lower() == dest.lower() for d in cfg["rules"])
        d, new = add_rule(cfg, dest, kws)
        if new:
            n_kw += len(new)
            if not existed:
                n_rules += 1
                print(f"  new rule  {d}: {', '.join(new)}")
            else:
                print(f"  added to  {d}: {', '.join(new)}")
    save_config(cfg, data)
    print(f"\n{n_rules} new rules, {n_kw} new keywords. Your old rules are in "
          f"{os.path.basename(backup)}.")


# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Sort images into folders by keywords in their filenames.",
        epilog="Run the steps in order: scan, learn, plan, apply. "
               "'undo' reverses apply.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_data(sp):
        sp.add_argument("--data", metavar="FOLDER",
                        help="where keywords.json, the reports, the plan and "
                             "the undo logs are (default: the logs folder "
                             "next to keyword-sorter if there is one, else "
                             "the image folder)")

    def add_common(sp):
        sp.add_argument("folder", nargs="?", default=None,
                        help="image folder (default: the one remembered in "
                             "keywords.json, else the current folder); "
                             "all subfolders are included")
        sp.add_argument("--top-only", action="store_true",
                        help="only look at images directly in the folder, "
                             "not in subfolders")
        # Subfolders are always included now; -r is accepted for old habits.
        sp.add_argument("-r", "--recursive", action="store_true",
                        help=argparse.SUPPRESS)
        add_data(sp)

    s = sub.add_parser("scan", help="count filename words, create keywords.json")
    add_common(s)
    s.add_argument("--suggestions", type=int, default=150,
                   help="how many candidates to list (default 150)")
    s.add_argument("--all", action="store_true",
                   help="count every image, also those in sorted folders "
                        "(default once rules exist: only what is unsorted)")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("learn", help="turn suggested words into rules by "
                                     "answering questions")
    add_data(s)
    s.add_argument("--min-files", type=int, default=5,
                   help="only suggest words in at least this many files "
                        "(default 5)")
    s.add_argument("--show", type=int, metavar="N",
                   help="just list the next N suggestions, ask nothing")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("update-rules", help="add this version's built-in "
                                            "rules to your keywords.json")
    add_data(s)
    s.set_defaults(func=cmd_update_rules)

    s = sub.add_parser("plan", help="preview where every image would go")
    add_common(s)
    s.add_argument("--resort", action="store_true",
                   help="also re-check images already in sorted folders")
    s.add_argument("--no-groups", action="store_true",
                   help="do not group leftovers by shared words")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("apply", help="move files as written in sort_plan.csv")
    s.add_argument("folder", nargs="?", default=None)
    add_data(s)
    s.add_argument("-y", "--yes", action="store_true",
                   help="do not ask for confirmation")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("undo", help="reverse the last apply")
    s.add_argument("folder", nargs="?", default=None)
    add_data(s)
    s.add_argument("--log", help="a specific undo_log_*.csv to use")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_undo)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
