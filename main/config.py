"""Persisted settings and the log file, both in one per-user directory."""
import json
import logging
from logging.handlers import RotatingFileHandler
from os import environ
from pathlib import Path

DEFAULTS = {
    "sheet_id": "",
    "tab": "",          # filled with the first tab once the sheet link is read
    "filename": "downloaded_google_sheet",
    "folder": "",
    "interval": 30,
    "loop": True,
}


def config_dir() -> Path:
    """Per-user data dir. Not "next to the app": a PyInstaller one-file build
    unpacks to a temp dir that is deleted on exit, so there is no such place."""
    base = environ.get("APPDATA") or (Path.home() / ".config")
    return Path(base) / "csvsync"


SETTINGS_PATH = config_dir() / "settings.json"
LOG_PATH = config_dir() / "csvsync.log"


def load() -> dict:
    """Saved settings over DEFAULTS. A missing or unreadable file means defaults."""
    settings = dict(DEFAULTS)
    try:
        stored = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        settings.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    return settings


def save(settings: dict) -> None:
    """Best effort: failing to persist settings must never kill a download."""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
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
