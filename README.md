# csvsync

Keeps one tab of a Google Sheet mirrored to a CSV file on your computer, once or
on a timer.

## Download

download the file from the
**[Releases page](https://github.com/peemsutthi/csvsync/releases/latest)**:

| OS | Download
|---|---|
| **Mac** | `csvSync-macos-arm64.zip` |
| **Windows** | `csvSync-windows-x64.exe` |

### The computer will warn you the first time

Both downloads are unsigned, so each operating system blocks them **once**. You only need to do this on first launch.

- **Mac** — you need to enable the app by going to **Settings** → **Privacy & Security**
- **Windows** — *"Windows protected your PC"* → **More info** → **Run anyway**.

## Using it

**Share the sheet to Anyone with the link can view and edit**

> In your sheet: **Share** → under *General access* pick **Anyone with the link**
> → leave the role as **Editor** → **Done**.

Then open csvSync and fill in four things:

| Field | What to put |
|---|---|
| **Sheet link or ID** | Copy your sheet's web address and paste the link or just sheet ID |
| **Tab name** | The name on the tab at the bottom of your sheet — often `Sheet1` |
| **File name** | What to call the CSV, e.g. `test` |
| **Folder** | **Choose…** where it should be saved on the computer|

Press **Start**.

To keep it updating by itself, tick **Repeat every _N_ seconds** before starting.
It keeps going until you press **Stop** or close the window. Your settings are
remembered for next time.

You'll also find a second copy of the CSV in a `data` folder alongside it as a backup.

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