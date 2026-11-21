# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Repo state

Post-refactor. The v2 package (`main/`) is built, wired, and tested. The v1
reconstruction (`legacy/CSVExtractor_reconstructed.py`) was removed; it is in
git history if v1 behavior ever needs checking.

- `main/` — the app. See Architecture below.
- Non-functional constraints still bind: single-purpose local utility, one user,
  one public sheet, no server/database/telemetry.

## Commands

```bash
.venv/bin/python -m main                    # run the app
.venv/bin/python tests/test_downloader.py   # tests, standalone (no pytest needed)
.venv/bin/python tests/test_app.py
.venv/bin/python tests/test_config.py
```

The venv must be Python 3.12+ (Homebrew or python.org); `requirements.txt` pulls
in pywebview, which brings pyobjc on macOS and pythonnet (WebView2) on Windows.

## Architecture

pywebview window around one local HTML page. One rule: **network and filesystem
logic stays out of `web/` and the UI glue**, so `downloader.py` is testable with
no window at all.

- `downloader.py` — pure. `download()` takes every input as an argument and
  raises `DownloadError` with a `kind` field (`input`, `timeout`, `network`,
  `http`, `private`, `write`) so callers can report the actual failure. The
  `session` argument is the seam tests inject a fake through. `sheet_id_from()`
  accepts a pasted Sheet URL as well as a bare ID — people paste the address bar,
  and the mangled fetch that followed got misreported as `private`. Each success
  writes twice: the live file, and an overwritten mirror at
  `<folder>/data/<name>.csv` (deliberately no history — that was the choice).
  Each write goes to `<name>.csv.tmp` then `os.replace`, so a program reading
  the CSV never sees half a file (`config.save` does the same).
  `sheet_info()` reads title + tabs + each tab's gid from **one** `htmlview` request; Google
  localises the `<title>` suffix (" - Google Sheets", " - Google ไดรฟ์" …), so
  only the last " - Google …" is cut. A private sheet redirects that request to
  `accounts.google.com`, which is how it reports `private`. `download(known_tabs=)`
  takes a `list_tabs()` answer (`{name: gid}`) and skips the tab-list request.
- `config.py` — JSON settings + rotating log in `%APPDATA%\csvsync` /
  `~/.config/csvsync`. Deliberately not "next to the app": a PyInstaller
  one-file build unpacks to a temp dir that is deleted on exit. `clean()` is the
  trust boundary for both the file and the page: DEFAULTS' keys and types only,
  `interval` is 0 (Once) or 1…`MAX_INTERVAL` (86400) seconds, default 10;
  `INTERVALS` = (3, 5, 10, 0) are the presets, and anything else shows as Custom. A 1.x file's
  `"loop": false` becomes Once. The tab is never stripped (real names end in spaces).
- `app.py` — `Api` (every public method is callable from JS as
  `pywebview.api.<name>`; everything else is `_underscored` because pywebview
  also exposes public *attributes*) and the sync worker. The worker reaches the
  page **only** via `evaluate_js("onEvent(" + json.dumps(evt) + ")")` — always
  json.dumps, since tab names and sheet titles come from Google. Events:
  `downloading`, `saved {at, path}`, `failed {at, kind, message}`,
  `wait {deadline_ms, interval}`, `done`. `done` is posted in a `finally`, after
  `_worker` is cleared, so the page can never be left stuck and an instant
  re-Start isn't refused. Stop is a `threading.Event` whose `wait(interval)`
  doubles as the loop sleep, so stopping is immediate. Tabs are re-read on the
  first pass and then at most every `TAB_RECHECK` (60 s) — at 3 s that halves the
  requests to Google; the cost is that a tab renamed mid-run keeps syncing
  (by gid) for up to 60 s before failing "No tab named …". Failure policy: **before the first save, every failure ends
  the run** (the user just pressed Start); after it, `timeout`/`network`/`http`/`write`
  log a row and retry, anything else ends it (`write`: on Windows a CSV open in
  Excel refuses writes until it is closed). `_emit` swallows errors so a closed
  window can't kill the worker. Also holds the pure helpers `short_path`,
  `summary_text`, `tape_line`.
- `__main__.py` — window (440×720, min 400×640) and menu. The page is loaded
  as a `file://` URI: a bare path makes pywebview start a localhost HTTP server.
  `WEB_DIR` lives in `app.py`, not here, because a PyInstaller entry script's
  `__file__` is the bundle root while a package module's is `…/main/`.
  Menu items just call `onMenu(name)`; the page decides if they apply.
  pywebview's `MenuAction` has no shortcut field, so on macOS
  `add_mac_shortcuts()` sets Cocoa key equivalents on the built items after page
  load; on Windows `app.js` handles Ctrl+key (and `preventDefault`s WebView2's
  Ctrl+R reload) and the menu shows no shortcut text.
- `web/index.html`, `style.css`, `app.js` — one page. State lives on
  `<body data-state="setup|downloading|running|error">` and CSS shows/hides
  blocks by it. The error state keeps every setup card under the alert, so any
  setting can be fixed before Try Again. Ported rules: the tab lookup is debounced
  600 ms after the link changes and its answer is dropped if the link changed
  meanwhile; the tab is auto-filled **only when empty** — a saved tab missing from
  the sheet stays selected as "(not in this sheet)", never swapped for another,
  which would sync an unpicked tab. The chosen tab is its own variable, not the
  select's value, because a private sheet disables the select. `start()` sets up
  `run` *before* awaiting `api.start`: the worker's first events can arrive
  before the call returns. Settings save on every `input` (Python locks the
  write), because nothing on close can ask the page for its fields: a closing
  handler that called `evaluate_js` would deadlock the main thread.
  Strings from Google go in via `textContent` / `new Option()`, never innerHTML.

### Visual style

Quiet, generous whitespace, a fixed paper palette. Every colour is a CSS
variable in `:root` of `style.css` (`--bg --card --card-edge --ink --muted
--field-edge --line --well --accent --accent-tint --ok --err --err-bg --err-edge
--err-text`, plus `--on-accent` and `--ring`), so dark mode is one
`prefers-color-scheme` block. Contrast floors are measured: `--muted` 5.1:1,
`--field-edge` 3.4:1 (white fields on white cards — the border is their only
edge); `--line` is decorative only. Layout: 28 px padding, 18 px between blocks,
cards white / 1 px `--card-edge` / radius 10 / padding 16 / 12 px apart. Setup
fits the default 720 px window with a short folder path; vertical spacing was
tightened to get there, so check `scrollHeight` before adding rows.

Two type roles, a rule rather than a preference: **prose is sans; anything the
user types or the app reads back (link, tab, file name, path, status word, log)
is mono.** Both stacks are system fonts only, nothing bundled.

Header: a 14 px circle + lowercase mono status word (26 px), so state never rests
on colour alone. `ready` hollow; `downloading…` filled accent, pulsing;
`syncing` filled; `saved` (Once finished) filled `--ok`; `failed` hollow
`--err` — a solid red light reads as "on air". "Last saved HH:MM:SS" shows only
while downloading/running.

Every focusable thing has a `:focus-visible` ring (3 px `--ring`, 1 px offset).
Where an inner input drops its outline (the `.csv` affix field, the folder
well) the wrapper carries the ring via `:focus-within`. `prefers-reduced-motion`
stops the pulse and the sliding bar. Return triggers the default button (skipped
during IME composition and on buttons/selects).

To see every state without clicking: drive a real window with `evaluate_js` and
`WKWebView.takeSnapshotWithConfiguration_completionHandler_`. `screencapture`
from the app's own process comes back blank (no screen-recording permission,
and WebKit stops painting occluded windows).

## Constraints worth not relearning

- The fetch is unauthenticated (`export?format=csv&gid=…`), so it only works on
  sheets shared "Anyone with the link can view". OAuth is out of scope.
- **Not gviz** (`gviz/tq?tqx=out:csv`, what v1 used): it types each column by
  majority and blanks every cell of another type, and quotes every field and
  drops blank rows. The export writes the cells as shown, quoting only when needed.
- A non-public sheet answers **200 with an HTML sign-in page**; `downloader.py`
  checks the content type so it never writes HTML into a `.csv`.
- The export is by gid, so `download()` looks the tab name up in the tab list
  on the public `htmlview` page (`items.push({name: …, pageUrl: …, gid: …})`). That page is undocumented: if Google changes it, every run
  fails with "No tab named …" — loud, never silently wrong.
- PyInstaller cannot cross-compile. Windows `.exe` builds on Windows, macOS
  `.app` on macOS, same source. `.github/workflows/build.yml` does both on a `v*`
  tag, which is the only way to get an `.exe` without a Windows machine.
- The two platforms need **different PyInstaller flags**. macOS is onedir
  (`--windowed`): `--onefile` with a `.app` is deprecated, "clashes with macOS's
  security", and becomes an error in PyInstaller 7 — and it zips to the same 13 MB
  anyway. Windows is `--onefile --windowed`, since it has no bundle format. Both
  need `--add-data "main/web:main/web"`; PyInstaller 6 accepts `:` on Windows too.
  In the `.app` the data lands in `Contents/Resources/main/web`, reached through
  the `Contents/Frameworks/main` symlink.
- Builds are unsigned on purpose, so both OSes block the first launch. Not a broken
  build — see the README. Signing is ~$99/yr Apple plus a Windows cert.
