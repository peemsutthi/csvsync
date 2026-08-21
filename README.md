# SheetSync

Mirrors one tab of a link-shared Google Sheet to a local CSV, once or on a timer.
Refactor of `CSVExtractor.exe` — see `legacy/CSVExtractor_reconstructed.py` for
the v1 behavioural baseline.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m main
```

Build the venv from **Python 3.12+ / Tk 8.6+** (Homebrew or python.org). macOS
system Python ships Tk 8.5.9, which renders the UI badly:

```bash
python3 -c "import tkinter; print(tkinter.Tcl().eval('info patchlevel'))"
```

## Test

```bash
.venv/bin/python tests/test_downloader.py   # standalone, no pytest needed
.venv/bin/python -m pytest tests            # same file, if you install pytest
```

## Build a standalone app

PyInstaller cannot cross-compile — build each target on that OS.

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name SheetSync --paths . main/__main__.py
```

## Layout

| Path | What |
|---|---|
| `main/downloader.py` | URL building, fetch, write, mirror. Pure, no Tk, unit-tested. |
| `main/config.py` | JSON settings + rotating log. |
| `main/gui.py` | Theme tokens, widgets, thread wiring. No network or file logic. |
| `main/__main__.py` | Entry point. |
| `legacy/CSVExtractor_reconstructed.py` | v1 reference only — not built, not run. |

Settings and log live in `%APPDATA%\sheetsync` (Windows) or `~/.config/sheetsync`
(macOS/Linux) — not next to the binary, because a PyInstaller one-file build
unpacks to a temp directory that is deleted on exit.

Every successful download also writes a mirror copy to `<folder>/data/<name>.csv`
— same bytes, same name, overwritten each run, no history kept. Turn it off by
deleting `mirror` from the write loop in `downloader.py`.

## Notes

Only works on sheets shared "Anyone with the link can view" — there is no OAuth.
A private sheet answers 200 with a sign-in page, which SheetSync detects and
reports rather than writing HTML into your `.csv`.
