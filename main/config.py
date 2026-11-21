"""Persisted settings and the log file, both in one per-user directory."""
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from os import environ
from pathlib import Path

DEFAULTS = {
    "sheet_id": "",
    "tab": "",          # filled with the first tab once the sheet link is read
    "filename": "downloaded_google_sheet",
    "folder": "",
    "interval": 10,     # seconds between syncs; 0 = fetch once
}
INTERVALS = (3, 5, 10, 0)   # the Schedule control's presets, in display order
MAX_INTERVAL = 86400        # Custom accepts 1…this many seconds (keep app.js in step)


def config_dir() -> Path:
    """Per-user data dir. Not "next to the app": a PyInstaller one-file build
    unpacks to a temp dir that is deleted on exit, so there is no such place."""
    base = environ.get("APPDATA") or (Path.home() / ".config")
    return Path(base) / "csvsync"


SETTINGS_PATH = config_dir() / "settings.json"
LOG_PATH = config_dir() / "csvsync.log"


def clean(raw) -> dict:
    """DEFAULTS' keys with DEFAULTS' types. Settings come from a JSON file or
    from the page, so anything may be in them. The tab is not stripped: it must
    match exactly, and real tab names can end in a space."""
    raw = raw if isinstance(raw, dict) else {}
    settings = {k: raw[k] if type(raw.get(k)) is type(v) else v for k, v in DEFAULTS.items()}
    for key in ("sheet_id", "filename", "folder"):
        settings[key] = settings[key].strip()
    if raw.get("loop") is False:    # a 1.x file: Repeat unticked is now "Once"
        settings["interval"] = 0
    if not (settings["interval"] == 0 or 1 <= settings["interval"] <= MAX_INTERVAL):
        settings["interval"] = DEFAULTS["interval"]
    return settings


def load() -> dict:
    """Saved settings over DEFAULTS. A missing or unreadable file means defaults."""
    try:
        return clean(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return clean({})


def save(settings: dict) -> None:
    """Best effort: failing to persist settings must never kill a download."""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
        tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_PATH)  # a crash mid-write can't leave half a file
    except OSError:
        logging.getLogger("csvsync").warning("could not write %s", SETTINGS_PATH)


def get_logger() -> logging.Logger:
    """Rotating file log so unattended loop runs leave a trace."""
    log = logging.getLogger("csvsync")
    if not log.handlers:
        log.setLevel(logging.INFO)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=2,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        log.addHandler(handler)
    return log
