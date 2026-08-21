# SheetSync

Keeps one tab of a Google Sheet mirrored to a CSV file on your computer, once or
on a timer.

## Download

Grab the file for your computer from the
**[Releases page](https://github.com/peemsutthi/csvsync/releases/latest)**:

| Your computer | Download | Then |
|---|---|---|
| **Mac** | `SheetSync-macos-arm64.zip` | Unzip it, drag `SheetSync` into Applications |
| **Windows** | `SheetSync-windows-x64.exe` | Save it anywhere and double-click it |

Nothing to install — no Python, no setup. About 13 MB.

### Your computer will warn you the first time

Both downloads are unsigned, so each operating system blocks them **once**. The
file is fine; this is what unsigned means. You only do this on first launch.

- **Mac** — you may see *"SheetSync is damaged and can't be opened."* It isn't.
  **Right-click** the app → **Open** → **Open** in the box that appears.
- **Windows** — *"Windows protected your PC"* → **More info** → **Run anyway**.

## Using it

**First, let the sheet be readable.** SheetSync never asks you to sign in, so the
sheet has to be link-shared or it cannot see anything:

> In your sheet: **Share** → under *General access* pick **Anyone with the link**
> → leave the role as **Viewer** → **Done**.

Then open SheetSync and fill in four things:

| Field | What to put |
|---|---|
| **Sheet link or ID** | Copy your sheet's web address and paste the whole thing in |
| **Tab name** | The name on the tab at the bottom of your sheet — often `Sheet1` |
| **File name** | What to call the CSV, e.g. `sales` |
| **Folder** | **Choose…** where it should be saved |

Press **Start**. The dot at the bottom turns blue while it works and green when
the file has been written.

To keep it updating by itself, tick **Repeat every _N_ seconds** before starting.
It keeps going until you press **Stop** or close the window. Your settings are
remembered for next time.

You'll also find a second copy of the CSV in a `data` folder alongside it. That's
a deliberate backup, overwritten each run.

### If something goes wrong

| It says | What it means |
|---|---|
| *"That sheet isn't public"* | The sharing step above hasn't been done, or was set to a specific person rather than *Anyone with the link* |
| *"Google returned HTTP 400/404"* | The tab name doesn't match a tab in the sheet — check the spelling at the bottom of your sheet |
| *"Network timed out"* | No internet, or Google is slow. Press Start again |

---

# For developers

Refactor of `CSVExtractor.exe` — see `legacy/CSVExtractor_reconstructed.py` for the v1
behavioural baseline.

## Run from source

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m main
```

## Test

```bash
.venv/bin/python tests/test_downloader.py   # standalone, no pytest needed
.venv/bin/python -m pytest tests            # same file, if you install pytest
```

## Ship it

Tag a version. GitHub Actions builds both platforms and attaches them to a Release:

```bash
git tag v1.0 && git push --tags
```

You get `SheetSync-macos-arm64.zip` (unzip → drag `SheetSync.app` to Applications)
and `SheetSync-windows-x64.exe` (single file, no installer). ~13 MB each; the bulk
is the bundled Tcl/Tk runtime.

CI exists because **PyInstaller cannot cross-compile** — the `.exe` has to be built
on Windows. To build locally instead, note the two targets need different flags:

```bash
pip install pyinstaller

# macOS — onedir. --onefile is deprecated with .app bundles and errors in v7.
pyinstaller --windowed --name SheetSync --paths . main/__main__.py

# Windows — onefile, so it stays one double-clickable icon.
pyinstaller --onefile --windowed --name SheetSync --paths . main/__main__.py
```

macOS CI builds **arm64 only**; Intel Macs won't run it. GitHub retired its Intel
runners, so an Intel build means running the macOS command above on an Intel Mac.

Both builds are unsigned, so both operating systems block the first launch —
see [Your computer will warn you](#your-computer-will-warn-you-the-first-time).
Signing is ~$99/yr from Apple plus a few hundred for a Windows certificate,
which is hard to justify for an internal tool.

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
