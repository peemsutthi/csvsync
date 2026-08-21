# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Repo state

Post-refactor. The v2 package (`main/`) is built, wired, and tested; v1 is
kept as the behavioral reference.

- `main/` — the app. See Architecture below.
- `legacy/CSVExtractor_reconstructed.py` — manual disassembly-to-source reconstruction
  of the shipped PyInstaller binary (`CSVExtractor.exe`, Python 3.13) whose
  source was lost. It is the **ground-truth spec for v1 behavior**, not code to
  run or evolve. Don't "fix" it; it documents what v2 must keep doing.
- Non-functional constraints still bind: single-purpose local utility, one user,
  one public sheet, no server/database/telemetry.

## Commands

```bash
.venv/bin/python -m main              # run the app
.venv/bin/python tests/test_downloader.py  # tests, standalone (no pytest needed)
```

The venv **must** be built from Python 3.12+ with Tk 8.6+ (Homebrew or
python.org). macOS system Python is 3.9.6 with Tk 8.5.9 and renders the UI
badly. Check with `python3 -c "import tkinter;print(tkinter.Tcl().eval('info patchlevel'))"`.

## Architecture

Three modules with one rule: **network and filesystem logic stays out of
`gui.py`**, so `downloader.py` is testable with no Tk event loop.

- `downloader.py` — pure. `download()` takes every input as an argument and
  raises `DownloadError` with a `kind` field (`input`, `timeout`, `network`,
  `http`, `private`, `write`) so callers can report the actual failure. The
  `session` argument is the seam tests inject a fake through. `sheet_id_from()`
  accepts a pasted Sheet URL as well as a bare ID — people paste the address bar,
  and the mangled fetch that followed got misreported as `private`. Each success
  writes twice: the live file, and an overwritten mirror at
  `<folder>/data/<name>.csv` (deliberately no history — that was the choice).
- `config.py` — JSON settings + rotating log in `%APPDATA%\sheetsync` /
  `~/.config/sheetsync`. Deliberately not "next to the app": a PyInstaller
  one-file build unpacks to a temp dir that is deleted on exit.
- `gui.py` — design tokens, widgets, wiring. The worker thread posts to a
  `queue.Queue` that `_drain()` polls on the Tk thread; **never touch a widget
  from the worker**. Stop is a `threading.Event` whose `wait(interval)` doubles
  as the loop sleep, so stopping is immediate.

### Visual style

Restrained, quiet, generous whitespace — a fixed paper palette rather than
native chrome. All of it lives in the token block at the top of `gui.py`
(`BG`/`INK`/`LINE`/`ACCENT`, `PAD`, `GAP`) plus `apply_theme()`. The theme is
`clam` on purpose: `aqua` and `vista` draw natively and ignore colour options.
Consequence: the app does not follow OS dark mode. Adding it means a second
token set, not new widgets.

## Constraints worth not relearning

- The fetch is unauthenticated (`gviz/tq?tqx=out:csv`), so it only works on
  sheets shared "Anyone with the link can view". OAuth is out of scope.
- A non-public sheet answers **200 with an HTML sign-in page**; `downloader.py`
  checks the content type so it never writes HTML into a `.csv`.
- PyInstaller cannot cross-compile. Windows `.exe` builds on Windows, macOS
  `.app` on macOS, same source. `.github/workflows/build.yml` does both on a `v*`
  tag, which is the only way to get an `.exe` without a Windows machine.
- The two platforms need **different PyInstaller flags**. macOS is onedir
  (`--windowed`): `--onefile` with a `.app` is deprecated, "clashes with macOS's
  security", and becomes an error in PyInstaller 7 — and it zips to the same 13 MB
  anyway. Windows is `--onefile --windowed`, since it has no bundle format.
- Builds are unsigned on purpose, so both OSes block the first launch. Not a broken
  build — see the README. Signing is ~$99/yr Apple plus a Windows cert.
