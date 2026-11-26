# Keyword sorter for the image folder

`sortimages.py` sorts images into folders based on words in their filenames.
It needs only Python 3.8 or newer (no extra packages). On Windows, install
Python from python.org or the Microsoft Store if `py --version` does not work.

Nothing is moved until you run `apply`, and every `apply` can be reversed with `undo`.

## Setup

Open a terminal in the `image-organizer` folder (in Explorer, click the
address bar, type `cmd` and press Enter) and run the script from there:

```
py keyword-sorter\sortimages.py scan C:\Users\Administrator\Documents\image-collection
```

**Where the files go.** If there is a `logs` folder next to `keyword-sorter`
(as in this project), `keywords.json`, the reports, the plan and the undo logs
are written there. `logs/` is in `.gitignore`, so none of it is ever uploaded
to GitHub. Without a `logs` folder they go into the image folder, as before.
`--data <folder>` picks another place.

`keywords.json` remembers the image folder, so after the first run you can
leave the folder path out: `py keyword-sorter\sortimages.py plan`.

## The steps

| Step | Command | What it does |
|---|---|---|
| 1 | `scan` | Counts words in the filenames of everything not sorted yet. Creates `keywords.json` (starter rules) the first time, `keyword_report.csv` (every recurring filename word and word pair, with how many files and folders have it) and `folder_report.csv`. |
| 2 | `learn` | Goes through the best suggested words one by one and asks what each is. Every answer becomes a rule. See below. |
| 3 | `plan` | Preview only. Decides a destination for every image in `_to sort` (and anything new) and writes `sort_plan.csv`. Prints a summary per folder. |
| 4 | `apply` | Moves the files as written in `sort_plan.csv`, after you type `yes`. Writes `undo_log_<time>.csv`. |
| 5 | `undo` | Moves everything from the most recent apply back. Run it again to undo the one before. |

`update-rules` adds the built-in rules of a newer version of the script to
your `keywords.json`; your own rules stay. A copy of the old file is kept.

A round after the first one is: `learn`, `plan`, `apply`, `scan` (to refresh
the counts), and again.

## Turning suggestions into rules (`learn`)

`learn` reads the counts in `keyword_report.csv`; it does not scan the images
again. It shows one word at a time, the most useful first:

```
[312 left]  massimo dutti   (267 files in 28 folders)
    e.g. avif/avivi/001-massimo-dutti-reversible-suede-napa-jacket.jpg
    what is it? b
    match both terms (massimo / dutti) on their own too? y/n [n = only 'dutti'] y
    -> fashion/brands/Massimo Dutti: massimo dutti, massimo, dutti
```

| Answer | Meaning | Folder |
|---|---|---|
| `p` | person | `people/<Name>` |
| `b` | brand | `fashion/brands/<Name>` |
| `e` | editorial / magazine | `fashion/editorial/<Name>` |
| `w` | street style / fashion week | `fashion/street style/<Name>` |
| `i` | fashion item without a brand | `fashion/fashion misc` |
| `s` | social media | `fashion/social media` |
| `g` | AI generated | `fashion/generated` |
| `c` | collage | `fashion/collages` |
| `m` | movie still | `misc/screenshots/movies` |
| `x` | other screenshot | `misc/screenshots` |
| `f <folder>` | any other folder, e.g. `f misc/wallpapers` | |
| Enter | skip for now (it comes back next time) | |
| `n` | never suggest this word again | |
| `u` | undo the last answer | |
| `q` | save and quit | |

- Type a name after the letter to choose the folder name: `b ASOS`, or
  `i Leather Jacket` for `fashion/fashion misc/Leather Jacket`.
- **Two-word names** ask "match both terms?". `y`: each word alone matches too
  (right for `massimo dutti`). `n`: only the second word alone, so
  `olivia palermo` matches `palermo` but `olivia` does not catch Olivia Wilde.
  `1` keeps only the first word, `0` only the full name.
- **What is suggested.** Words a rule already catches, words you answered `n`
  to, and words of 3 letters or less (`oip`) are left out, as are common words
  like `black` or `product`. Word pairs that nearly always appear together
  (`massimo dutti`, `olivia palermo`) come first, before their single words.
  After each answer the list is worked out again, so the next best word moves
  up.
- Everything is saved after every answer, so you can stop any time.
  `keywords_backup_<time>.json` is a copy from before the session and
  `learn_log.csv` lists every answer.
- `learn --show 50` only lists the next 50 suggestions.

## Subfolders

Every step looks through all subfolders of the image folder, however deep.
Add `--top-only` to look only at images directly in the folder.

- **Folder names count as keywords.** An image with no keyword in its filename
  is matched on the folders it sits in, innermost first. So
  `Alexa Chung/2019/IMG_0001.jpg` goes to `people/Alexa Chung/2019`: the
  subfolders below the matched folder are kept.
- **Only what is unsorted is looked at.** The top folders your rules sort
  into (`people`, `fashion`, `misc`) are not even opened by `plan` and `scan`,
  so a rule that already did its job costs no time, and the rule stays to
  catch new images later. Folders you made there by hand (like
  `people/Some Name`) are safe. Add `--resort` to `plan`, or `--all` to
  `scan`, to include them.
- **`_trash` is never touched.** Folders in `skip_folders` in `keywords.json`
  are skipped by every step.
- **Leftovers keep their folder.** An image with no keyword that sits in a
  subfolder, like `Paris 2019/IMG_10.jpg`, moves to `_to sort/Paris 2019`, so
  photos that belonged together stay together.
- **Re-running is safe.** `_to sort` is always re-checked, so after adding new
  keywords, run `plan` and `apply` again to pull images out of it.
- Hidden folders and system folders like `$RECYCLE.BIN` are skipped. Folders
  that end up empty after `apply` are removed, and `undo` brings them back.

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
  so AI images, collages and movie stills come first, then people, specific
  shows, magazines and brands, then the general `fashion/street style` and
  `fashion/editorial` folders, social media, fashion items, and screenshots.
  `learn` puts new rules in the right place in this order.
- Matching ignores case and separators: `alexa chung` matches `Alexa_Chung_01.jpg`,
  `alexa-chung.jpg` and `AlexaChung2019.jpg`. Keywords of 6+ letters also match
  inside longer words (`alexachungnyfw.jpg`); short ones like `cos` or `hm` only
  match as a whole word, so `cosmos.jpg` is not sent to COS.
- `suggestions` lists the best candidates for new rules (the same order
  `learn` uses). Folder names are not counted here (see `folder_report.csv`), and random
  ids like `3f9a2c7e` are skipped. Move useful ones into a rule. Running `scan` again refreshes this list and
  keeps your rules.
- `ignore_words` adds words that should never count (camera prefixes like `IMG`
  and `DSC` are already ignored).

## Leftovers

Images that match no keyword in their filename or folder names go into `_to sort`:

- `_to sort/<word>/` when at least 3 leftovers share a word, word pair or filename
  prefix (for example `pinterest_8812.jpg`, `pinterest_9001.jpg`). The group size
  is `min_group_size` in `keywords.json`.
- `_to sort/<original folder>/` for the rest that came from a subfolder.
- `_to sort/_no pattern/` for loose images from the top of the image folder,
  ready for visual sorting in the image app.

If a group turns out to be a real category, add its word to a rule and run
`plan` and `apply` again.

## If some files could not be moved

`apply` keeps going when a file can't be moved, lists every failure in
`apply_errors.csv` and prints the first few. Everything that did move is in the
undo log, so `undo` still works. Run `plan` and `apply` again to retry the rest.

Folder names are cleaned for Windows before anything is created: trailing spaces
and dots, characters like `:` or `?`, and reserved names like `CON` are fixed.
Very long paths (over 260 characters) are supported too.

## Editing the plan by hand

`sort_plan.csv` opens in Excel. You can change the `move_to` column or delete
rows before running `apply`; `apply` does exactly what the file says. Files that
already exist in a destination are not overwritten: the moved one gets ` (1)`
added to its name.
