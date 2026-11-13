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
  from the worker**. `_run` posts `done` in a `finally`: without it, any
  non-`DownloadError` (folder `~Desktop`) left Start disabled for good.
  Tab name is a `ttk.Combobox`: editing the Sheet field schedules (600 ms
  debounce) a background `list_tabs()` whose answer `_show_tabs()` drops if
  the link changed meanwhile, and it only fills an **empty** tab field — never
  swaps a saved name that went missing, which would sync an unpicked tab. Stop
  is a `threading.Event` whose `wait(interval)` doubles as the loop sleep, so
  stopping is immediate.

### Visual style

Restrained, quiet, generous whitespace — a fixed paper palette rather than
native chrome. All of it lives in the token block at the top of `gui.py`
(`BG`/`INK`/`MUTED`/`EDGE`/`LINE`/`ACCENT`, `PAD`, `GAP`) plus `apply_theme()`.
Contrast floors are measured, not eyeballed: `MUTED` text 5.38:1 (needs 4.5),
`EDGE` control borders 3.43:1 (fields are white on white, so the border is
their only edge); `LINE` is decorative only (countdown track, disabled
buttons, which should recede). The theme is
`clam` on purpose: `aqua` and `vista` draw natively and ignore colour options.
Consequence: the app does not follow OS dark mode. Adding it means a second
token set, not new widgets.

Two type roles, and the split is a rule rather than a preference: **prose is
sans, anything the user types is mono.** A Sheet ID, tab name, filename and
path are literals that have to match something exactly. Both roles use the
OS's current system fonts: SF Pro / SF Mono on macOS (reachable only as the
dot-names `.AppleSystemUIFont` / `.AppleSystemUIFontMonospaced`, which
`font.families()` doesn't list — so `_pick()` keeps the first name Tk actually
*resolves*), Segoe UI Variable / Cascadia Mono on Windows 11, then Avenir Next /
Segoe UI and Menlo / Consolas as fallbacks. No font is bundled, because Tk has
no font-loading API and registering one is per-platform `ctypes`. Font sizes are **negative = pixels**: points go through
`tk scaling`, which is 1.0 px/pt on older macOS Tk and 1.33 on Tk 9, so a
point size rendered 25% smaller depending on the build. Section markers
(`SOURCE`, `OUTPUT`) are plain `text.upper()` in
`Sect.TLabel`, mono at a small size and muted color — no letterspacing (Tk has
no tracking option, and a hand-rolled space-join read heavier than intended).

The top slot is the **status readout**, not a wordmark (the title bar already
names the app): mono bold 32 px, `idle` / `syncing…` / `saved HH:MM:SS` /
`failed HH:MM:SS`, so state never rests on colour alone. Beside it a square
tally mark; failed draws it **hollow**, because a solid red light reads as "on
air" in a control room. The readout and the tape row share one timestamp.

The window has two states. Idle shows the setup pane; Start calls `collapse()`,
which `grid_remove()`s it behind a one-line summary of what the run is actually
using. The fields stay enabled — Start is disabled while running, so the only
way to apply an edit is Stop then Start, which re-reads them anyway.
`_refit()` rewrites the **height only**; `geometry("")` would also reset a
width the user dragged.

Text fields and the tab dropdown share one look: a square `EDGE` line, `MUTED`
under the pointer, a 2 px `ACCENT` ring on focus. Both use a custom layout of
**alt-theme** parts (`Box.border` + `Ring.focus`), not clam's field: clam's
border skips its corner pixels (a fake rounding that reads as gaps at the
corners), and a 2 px border leaves a hole at the inner corners, so focus is two
1 px rectangles instead. The idle focus ring still holds its pixel, so text
never shifts. The dropdown's arrow is clam's `Menubutton.indicator`, a bare
triangle; clam's own combobox arrow is boxed in a bevelled button.
On macOS Tk 9 the open list is a **native menu**, so the listbox option-db
styling only reaches Windows and older Tk.

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
- gviz answers an **unknown tab name with the first tab** (200, valid CSV, no
  error). `download()` checks the name against the tab list on the public
  `htmlview` page. That page is undocumented: if Google changes it, every run
  fails with "No tab named …" — loud, never silently wrong.
- PyInstaller cannot cross-compile. Windows `.exe` builds on Windows, macOS
  `.app` on macOS, same source. `.github/workflows/build.yml` does both on a `v*`
  tag, which is the only way to get an `.exe` without a Windows machine.
- The two platforms need **different PyInstaller flags**. macOS is onedir
  (`--windowed`): `--onefile` with a `.app` is deprecated, "clashes with macOS's
  security", and becomes an error in PyInstaller 7 — and it zips to the same 13 MB
  anyway. Windows is `--onefile --windowed`, since it has no bundle format.
- Builds are unsigned on purpose, so both OSes block the first launch. Not a broken
  build — see the README. Signing is ~$99/yr Apple plus a Windows cert.
