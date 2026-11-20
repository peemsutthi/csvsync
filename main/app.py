"""The bridge between the page (web/) and downloader.py: the Api the page calls,
and the sync worker. No network or filesystem logic of its own lives here
beyond opening what was saved."""
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests
import webview

from . import config
from .downloader import (DEFAULT_FILENAME, DownloadError, download, list_tabs, sheet_id_from,
                         sheet_info, target_path)

WEB_DIR = Path(__file__).parent / "web"     # main/web, from source and from PyInstaller
SHEET_EDIT_URL = "https://docs.google.com/spreadsheets/d/{}/edit"
TAB_RECHECK = 60    # seconds; the tab list is re-read at most this often while looping
# Once a run has saved, these log and retry. "write" too: on Windows a file open
# in Excel (or a reader mid-read) refuses the write until it is let go.
TRANSIENT = {"timeout", "network", "http", "write"}


# --- helpers -------------------------------------------------------------
def short_path(folder):
    """Display form of a folder: `~/Desktop` beats `/Users/someone/Desktop`."""
    folder = (folder or "").strip()
    if not folder:
        return "no folder chosen"
    try:
        return str(Path("~") / Path(folder).relative_to(Path.home()))
    except ValueError:
        return folder


FOLDER_CHARS = 30   # keeps the summary inside a minimum-width window


def summary_text(tab, filename, folder):
    """One line standing in for the whole setup pane: what goes where.

    A folder too long to fit is elided from the *left*: the tail is the part
    that identifies it, and a hard clip at the label's edge just looks broken.
    """
    name = (filename or "").strip() or DEFAULT_FILENAME
    if name.lower().endswith(".csv"):
        name = name[:-4]
    where = short_path(folder)
    if len(where) > FOLDER_CHARS:
        where = "…" + where[-(FOLDER_CHARS - 1):]
    return "{} → {}.csv · {}".format((tab or "").strip() or "—", name, where)


def tape_line(when, verb, detail):
    """One ledger row. Column widths live here so the mono grid stays aligned."""
    return "{}  {:<8}{}\n".format(when.strftime("%H:%M:%S"), verb, detail)


def _now():
    return datetime.now().strftime("%H:%M:%S")


class Api:
    """Every public method is callable from the page as pywebview.api.<name>.
    Everything else is underscored: pywebview exposes public attributes too."""

    def __init__(self, window=None, session=requests, log=None):
        self._window = window       # None: the app's one window, looked up when needed
        self._session = session     # the seam tests inject a fake through
        self._log = log or config.get_logger()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._worker = None
        self._last_path = None

    def _win(self):
        return self._window or webview.windows[0]

    def _emit(self, event):
        """The only way to reach the page. json.dumps, always: tab names and
        sheet titles come from Google and must never be spliced in raw."""
        try:
            self._win().evaluate_js("onEvent(" + json.dumps(event) + ")")
        except Exception:   # window closing: the worker must still finish
            self._log.warning("could not post %s", event.get("type"))

    # --- called from the page -------------------------------------------------
    def load_settings(self):
        settings = config.load()
        settings["folder_display"] = short_path(settings["folder"])
        return settings

    def save_settings(self, settings):
        """Persist edits as they happen, so closing the window keeps them. Each page
        call runs on its own thread; the lock keeps two writes from interleaving."""
        with self._lock:
            config.save(config.clean(settings))

    def sheet_info(self, link):
        try:
            return sheet_info(link, session=self._session)
        except DownloadError as exc:
            return {"kind": exc.kind, "message": str(exc)}
        except Exception as exc:    # the page's spinner must always get an answer
            return {"kind": "unexpected", "message": "Unexpected error: {}".format(exc)}

    def choose_folder(self):
        chosen = self._win().create_file_dialog(webview.FileDialog.FOLDER)
        if not chosen:
            return None
        path = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        return {"path": path, "display": short_path(path)}

    def start(self, settings):
        """Validate, persist, and start the worker. Returns what the page shows."""
        settings = config.clean(settings)
        for field, key, message in (("link", "sheet_id", "Paste the sheet link or ID."),
                                    ("tab", "tab", "Pick a tab."),
                                    ("folder", "folder", "Choose a folder to save into.")):
            if not settings[key].strip():
                return {"ok": False, "field": field, "message": message}
        with self._lock:
            if self._worker:
                return {"ok": False, "field": None, "message": "Already running."}
            config.save(settings)
            self._stop.clear()
            self._worker = threading.Thread(target=self._run, args=(settings,), daemon=True)
            self._worker.start()
        return {"ok": True,
                "file": target_path(settings["folder"], settings["filename"]).name,
                "folder": short_path(settings["folder"]),
                "summary": summary_text(settings["tab"], settings["filename"],
                                        settings["folder"])}

    def stop(self):
        """Ends the wait immediately; an in-flight request is bounded by its timeout."""
        self._stop.set()

    def open_file(self):
        path = self._saved()
        if path:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open", path])
        return bool(path)

    def show_in_folder(self):
        path = self._saved()
        if path:
            if sys.platform == "win32":
                # explorer wants the quotes after the comma, and exits 1 on success
                subprocess.Popen('explorer /select,"{}"'.format(path))
            else:
                subprocess.Popen(["open", "-R", path])
        return bool(path)

    def open_sheet(self, link):
        """Open the sheet in the browser. Built from the ID, so only ever a Sheets URL."""
        sheet_id = sheet_id_from(link)
        if sheet_id:
            webbrowser.open(SHEET_EDIT_URL.format(quote(sheet_id, safe="")))

    def _saved(self):
        path = self._last_path
        return str(path) if path and path.exists() else None

    # --- worker thread: reaches the page only through _emit ---------------------
    def _run(self, settings):
        tabs, checked, saved = None, 0.0, False
        try:
            while True:
                self._emit({"type": "downloading"})
                try:
                    if tabs is None or time.monotonic() - checked >= TAB_RECHECK:
                        tabs = list_tabs(settings["sheet_id"], session=self._session)
                        checked = time.monotonic()
                    dest = download(settings["sheet_id"], settings["tab"], settings["folder"],
                                    settings["filename"], session=self._session,
                                    known_tabs=tabs)
                    self._last_path, saved = dest, True
                    self._log.info("saved %s", dest)
                    self._emit({"type": "saved", "at": _now(), "path": str(dest)})
                except Exception as exc:
                    if isinstance(exc, DownloadError):
                        kind, message = exc.kind, str(exc)
                        self._log.error("%s: %s", kind, message)
                    else:   # e.g. folder "~Desktop": a bug or an odd path, never a hang
                        kind, message = "unexpected", "Unexpected error: {}".format(exc)
                        self._log.exception("unexpected error")
                    self._emit({"type": "failed", "at": _now(), "kind": kind,
                                "message": message})
                    # Before anything has saved, every failure ends the run: the
                    # user just pressed Start and needs to see why.
                    if not saved or kind not in TRANSIENT:
                        break
                # Check the event before announcing a wait, or stopping mid-download
                # flashes a countdown that is already cancelled.
                if not settings["interval"] or self._stop.is_set():
                    break
                self._emit({"type": "wait", "interval": settings["interval"],
                            "deadline_ms": int((time.time() + settings["interval"]) * 1000)})
                if self._stop.wait(settings["interval"]):
                    break
        finally:
            with self._lock:
                self._worker = None     # before "done", so an instant re-Start isn't refused
            self._emit({"type": "done"})
