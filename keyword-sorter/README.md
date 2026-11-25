# Keyword sorter for the image folder

`sortimages.py` sorts images into folders based on words in their filenames.
It needs only Python 3.8 or newer (no extra packages). On Windows, install
Python from python.org or the Microsoft Store if `py --version` does not work.

Nothing is moved until you run `apply`, and every `apply` can be reversed with `undo`.

## Setup

Copy `sortimages.py` into your image folder (or anywhere, and pass the folder
path). Open a terminal in the image folder: in Explorer, click the address bar,
type `cmd` and press Enter.

## The four steps

| Step | Command | What it does |
|---|---|---|
| 1 | `py sortimages.py scan` | Counts words in all filenames. Creates `keywords.json` (starter rules) and `keyword_report.csv` (every recurring word and word pair, with how many files have it). |
| 2 | `py sortimages.py plan` | Preview only. Decides a destination for every image and writes `sort_plan.csv`. Prints a summary per folder. |
| 3 | `py sortimages.py apply` | Moves the files as written in `sort_plan.csv`, after you type `yes`. Writes `undo_log_<time>.csv`. |
| 4 | `py sortimages.py undo` | Moves everything from the most recent apply back. Run it again to undo the one before. |

Add `-r` to `scan` and `plan` to include images in subfolders. Folders the
sorter already created are skipped, except `_to sort`, so after adding new
keywords you can run `plan -r` again to pull images out of the leftovers.

## Teaching it keywords (`keywords.json`)

```json
"rules": {
  "people/Alexa Chung": ["alexa chung", "alexachung"],
  "fashion/street style/New York Fashion Week": ["nyfw", "new york fashion week"],
  "fashion/editorial/Vogue": ["vogue"],
  "fashion/brands/Zara": ["zara"],
  "misc/screenshots": ["screenshot", "bildschirmfoto"]
}
```

- Each rule is `"destination folder": [keywords]`. The **first matching rule wins**,
  so people come first, then specific shows, magazines and brands, then the general
  `fashion/street style` and `fashion/editorial` folders, then misc.
- Matching ignores case and separators: `alexa chung` matches `Alexa_Chung_01.jpg`,
  `alexa-chung.jpg` and `AlexaChung2019.jpg`. Keywords of 6+ letters also match
  inside longer words (`alexachungnyfw.jpg`); short ones like `cos` or `hm` only
  match as a whole word, so `cosmos.jpg` is not sent to COS.
- `suggestions` lists the most frequent words in your filenames that no rule uses
  yet. Move useful ones into a rule. Running `scan` again refreshes this list and
  keeps your rules.
- `ignore_words` adds words that should never count (camera prefixes like `IMG`
  and `DSC` are already ignored).

## Leftovers

Images that match no keyword go into `_to sort`:

- `_to sort/<word>/` when at least 3 leftovers share a word, word pair or filename
  prefix (for example `pinterest_8812.jpg`, `pinterest_9001.jpg`). The group size
  is `min_group_size` in `keywords.json`.
- `_to sort/_no pattern/` for everything else, ready for visual sorting in the image app.

If a group turns out to be a real category, add its word to a rule and run
`plan -r` and `apply` again.

## Editing the plan by hand

`sort_plan.csv` opens in Excel. You can change the `move_to` column or delete
rows before running `apply`; `apply` does exactly what the file says. Files that
already exist in a destination are not overwritten: the moved one gets ` (1)`
added to its name.
