"""Fetch one tab of a link-shared Google Sheet as CSV.

Pure logic: no Tk, no globals, no module-level side effects. Everything the
download needs arrives as an argument, which is what makes this testable.
"""
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

GVIZ_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab}"
TABS_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview"
DEFAULT_FILENAME = "downloaded_google_sheet"
DEFAULT_TIMEOUT = 30
MIRROR_DIRNAME = "data"
SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
TAB_NAME_RE = re.compile(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)"')


class DownloadError(Exception):
    """A failure the user can act on. `kind` says which category it is.

    kind is one of: input, timeout, network, http, private, write.
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def sheet_id_from(text: str) -> str:
    """Pull the ID out of a pasted Sheet URL; pass a bare ID through unchanged.

    People paste the whole address bar, because that is the thing they have. The
    ID went into the URL verbatim before, so the fetch came back as HTML and got
    reported as "that sheet isn't public" — sending them off to change sharing
    settings that were never the problem.
    """
    text = (text or "").strip()
    found = SHEET_ID_RE.search(text)
    return found.group(1) if found else text


def sheet_url(sheet_id: str, tab: str) -> str:
    """Build the gviz CSV export URL, percent-encoding both halves."""
    return GVIZ_URL.format(sheet_id=quote(sheet_id, safe=""), tab=quote(tab, safe=""))


def tab_names(page: str) -> list:
    """Tab names from the sheet's public htmlview page, where each sits in a JS
    string literal such as `name: "Q3 \\x26 Q4"`."""
    names = []
    for raw in TAB_NAME_RE.findall(page):
        try:
            names.append(json.loads('"' + re.sub(r"\\x([0-9a-fA-F]{2})", r"\\u00\1", raw) + '"'))
        except ValueError:      # an escape JSON doesn't know: compare it as-is
            names.append(raw)
    return names


def _get(session: Any, url: str, timeout: float):
    """GET, with network and HTTP failures turned into DownloadError kinds."""
    try:
        response = session.get(url, timeout=timeout)
    except requests.Timeout as exc:
        raise DownloadError("timeout", f"Network timed out after {timeout}s.") from exc
    except requests.RequestException as exc:
        raise DownloadError("network", f"Network error: {exc}") from exc
    if response.status_code != 200:
        # Only a 400/404 points at the input; a 429 or 5xx is Google's side.
        hint = " Check the Sheet ID and tab name." if response.status_code in (400, 404) else ""
        raise DownloadError("http", f"Google returned HTTP {response.status_code}.{hint}")
    return response


def list_tabs(sheet_id: str, timeout: float = DEFAULT_TIMEOUT, session: Any = requests) -> list:
    """Tab names of a link-shared sheet, in sheet order. Empty if Google sent a
    page without a tab list (e.g. the sign-in page of a private sheet)."""
    url = TABS_URL.format(sheet_id=quote(sheet_id_from(sheet_id), safe=""))
    return tab_names(_get(session, url, timeout).text)


def target_path(folder: str, filename: str) -> Path:
    """Resolve <folder>/<filename>.csv without doubling the extension."""
    name = (filename or "").strip() or DEFAULT_FILENAME
    if name.lower().endswith(".csv"):
        name = name[:-4]
    return Path(folder or ".").expanduser() / (name + ".csv")


def download(sheet_id: str, tab: str, folder: str = ".", filename: str = DEFAULT_FILENAME,
             timeout: float = DEFAULT_TIMEOUT, session: Any = requests) -> Path:
    """Download the sheet, write it, mirror it. Returns the live Path.

    Raises DownloadError for every expected failure, tagged by kind so the
    caller can say what actually went wrong instead of "Error: <something>".
    """
    # The tab is not stripped: it must match exactly, and real names can end in a space.
    sheet_id, tab = sheet_id_from(sheet_id), tab or ""
    if not sheet_id or not tab.strip():
        raise DownloadError("input", "Enter both a Sheet ID and a tab name.")

    dest = target_path(folder, filename)
    response = _get(session, sheet_url(sheet_id, tab), timeout)

    # A sheet that isn't link-shared redirects to a sign-in page and still
    # answers 200, so v1 happily wrote HTML into a .csv. Catch that.
    if "text/html" in response.headers.get("content-type", ""):
        raise DownloadError("private", "That sheet isn't public. Set sharing to "
                                       "'Anyone with the link can view'.")

    # gviz answers an unknown tab name with the *first* tab, as a normal 200 CSV,
    # so a typo or a renamed tab would overwrite the file with the wrong data.
    tabs = list_tabs(sheet_id, timeout, session)
    if tab not in tabs:
        raise DownloadError("input", "No tab named '{}'. Tabs in this sheet: {}.".format(
            tab, ", ".join(tabs) or "none found"))

    # The live file, then a mirror under <folder>/data/. Same bytes, same name:
    # a plain second copy, overwritten every run, with no history kept.
    mirror = dest.parent / MIRROR_DIRNAME / dest.name
    for path in (dest, mirror):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
        except OSError as exc:
            raise DownloadError("write", f"Could not write {path}: {exc}") from exc
    return dest
