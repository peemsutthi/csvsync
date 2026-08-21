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
- `config.py` — JSON settings + rotating log in `%APPDATA%\csvsync` /
  `~/.config/csvsync`. Deliberately not "next to the app": a PyInstaller
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

Two type roles, and the split is a rule rather than a preference: **prose is
sans, anything the user types is mono.** A Sheet ID, tab name, filename and
path are literals that have to match something exactly. `_pick()` resolves
Avenir Next / Segoe UI and Menlo / Consolas with fallbacks — no font is
bundled, because Tk has no font-loading API and registering one is per-platform
`ctypes`. Section markers (`SOURCE`, `OUTPUT`) are plain `text.upper()` in
`Sect.TLabel`, mono at a small size and muted color — no letterspacing (Tk has
no tracking option, and a hand-rolled space-join read heavier than intended).

The window has two states. Idle shows the setup pane; Start calls `collapse()`,
which `grid_remove()`s it behind a one-line summary of what the run is actually
using. The fields stay enabled — Start is disabled while running, so the only
way to apply an edit is Stop then Start, which re-reads them anyway.
`_refit()` rewrites the **height only**; `geometry("")` would also reset a
width the user dragged.

`Check.Toolbutton` is the Repeat toggle: a real `ttk.Checkbutton` (Space
toggles it) styled on clam's `Toolbutton` layout, which has no indicator
element — clam's own `TCheckbutton` indicator draws an **✗** for "checked",
which reads as "no" on a control that means "yes", and the classic
`tk.Checkbutton` draws no mark at all on macOS. `_sync_repeat_mark()` draws
`☑`/`☐` itself as the widget's text, wired to the `command` callback so it
stays in sync with clicks.

The signature is `_rule`: the hairline between the tape and the footer is also
the countdown, filling in `ACCENT` as the interval elapses. It rides `_drain`'s
existing 100 ms timer via `_tick()` — there is no second `after` loop, and the
deadline arrives from the worker as a `("wait", (deadline, interval))` message
so it tracks the settings the run actually started with.

`self.tape` is a read-only `tk.Text`, not a label: it is the only place results
appear, and one footer label used to clip every path and every long error.
Capped at `TAPE_LINES`.

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
