# csvsync

Keeps one tab of a Google Sheet mirrored to a CSV file on your computer, once or
on a timer.

## Download

download the app from the
**[Releases page](https://github.com/peemsutthi/csvsync/releases/latest)**:

| OS | Download
|---|---|
| **Mac** | `csvSync-macos-arm64.zip` |
| **Windows** | `csvSync-windows-x64.exe` |

### The computer will warn you the first time

Both downloads are unsigned, so each operating system blocks them **once**. You only need to do this on first launch.

- **Mac:** you need to enable the app by going to **Settings** → **Privacy & Security**
- **Windows:** *"Windows protected your PC"* → **More info** → **Run anyway**.

## Using it

**Share the sheet so anyone with the link can view it**

> In your sheet: **Share** → under *General access* pick **Anyone with the link**
> → set the role to **Viewer** → **Done**.

Then open csvSync and fill in four things:

| Field | Descriptions |
|---|---|
| **Google Sheet link** | Copy your sheet's web address and paste it |
| **Tab** | Pick it from the list after pasting the link |
| **File name** | CSV file on your computer |
| **Folder** | **Choose…** where it should be saved on the computer (required) |

Pick a **Schedule**: **3 s**, **5 s**, **10 s**, or **Once**, then press **Start Sync** (**Fetch Now** for Once).

It keeps going until you press **Stop** or close the window. If it fails, the app tells you why; fix it and press **Try Again**. The settings are remembered for next time.

You'll also find a second copy of the CSV in a `data` folder alongside it as a backup.

# For developers

## Run from source

Needs Python 3.12+.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m main
```