"""Fetch one tab of a link-shared Google Sheet as CSV.

Pure logic: no Tk, no globals, no module-level side effects. Everything the
download needs arrives as an argument, which is what makes this testable.
"""
import html
import json
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

# Not gviz/tq?tqx=out:csv (v1): it gives each column one type, by majority, and
# blanks every cell of another type, so "TBD" in a column of numbers comes out empty.
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
TABS_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview"
DEFAULT_FILENAME = "downloaded_google_sheet"
DEFAULT_TIMEOUT = 30
MIRROR_DIRNAME = "data"
PRIVATE_MESSAGE = "That sheet isn't public. Set sharing to 'Anyone with the link can view'."
SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
# items.push({name: "2026", pageUrl: "…", gid: "569181446", …}): name, string fields, gid.
TAB_RE = re.compile(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)"(?:, \w+: "(?:[^"\\]|\\.)*")*, gid: "(\d+)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
# " - Google Sheets", but localised by Google (seen live: " - Google ไดรฟ์"). Only the
# last " - Google …" goes, so a title like "Ads - Google Ads export" survives.
TITLE_SUFFIX_RE = re.compile(r"\s+-\s+Google(?:\s[^-]*)?$")
SIGN_IN_HOST = "accounts.google.com"


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


def sheet_url(sheet_id: str, gid: str) -> str:
    """Build the CSV export URL for one tab, by its gid."""
    return EXPORT_URL.format(sheet_id=quote(sheet_id, safe=""), gid=quote(gid, safe=""))


def tab_gids(page: str) -> dict:
    """{tab name: gid}, in sheet order, from the sheet's public htmlview page,
    where each name sits in a JS string literal such as `name: "Q3 \\x26 Q4"`."""
    gids = {}
    for raw, gid in TAB_RE.findall(page):
        try:
            name = json.loads('"' + re.sub(r"\\x([0-9a-fA-F]{2})", r"\\u00\1", raw) + '"')
        except ValueError:      # an escape JSON doesn't know: compare it as-is
            name = raw
        gids[name] = gid
    return gids


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


def sheet_info(link: str, timeout: float = DEFAULT_TIMEOUT, session: Any = requests) -> dict:
    """{"title", "tabs", "gids"} of a link-shared sheet, from one htmlview request.

    tabs are the names in sheet order, gids maps each to its gid; both are empty
    if Google sent a page without a tab list.
    A private sheet redirects to Google's sign-in page, which still answers 200.
    """
    url = TABS_URL.format(sheet_id=quote(sheet_id_from(link), safe=""))
    response = _get(session, url, timeout)
    if SIGN_IN_HOST in (getattr(response, "url", "") or ""):
        raise DownloadError("private", PRIVATE_MESSAGE)
    found = TITLE_RE.search(response.text)
    title = html.unescape(found.group(1)).strip() if found else ""
    gids = tab_gids(response.text)
    return {"title": TITLE_SUFFIX_RE.sub("", title), "tabs": list(gids), "gids": gids}


def list_tabs(sheet_id: str, timeout: float = DEFAULT_TIMEOUT, session: Any = requests) -> dict:
    """{tab name: gid} of a link-shared sheet, in sheet order (see sheet_info)."""
    return sheet_info(sheet_id, timeout, session)["gids"]


def target_path(folder: str, filename: str) -> Path:
    """Resolve <folder>/<filename>.csv without doubling the extension."""
    name = (filename or "").strip() or DEFAULT_FILENAME
    if name.lower().endswith(".csv"):
        name = name[:-4]
    return Path(folder or ".").expanduser() / (name + ".csv")


def download(sheet_id: str, tab: str, folder: str = ".", filename: str = DEFAULT_FILENAME,
             timeout: float = DEFAULT_TIMEOUT, session: Any = requests,
             known_tabs: dict = None) -> Path:
    """Download the sheet, write it, mirror it. Returns the live Path.

    known_tabs, if given, is a list_tabs() answer the caller fetched recently; the
    tab is looked up in it instead of spending a request on the htmlview page.

    Raises DownloadError for every expected failure, tagged by kind so the
    caller can say what actually went wrong instead of "Error: <something>".
    """
    # The tab is not stripped: it must match exactly, and real names can end in a space.
    sheet_id, tab = sheet_id_from(sheet_id), tab or ""
    if not sheet_id or not tab.strip():
        raise DownloadError("input", "Enter both a Sheet ID and a tab name.")

    dest = target_path(folder, filename)
    # The export is by gid, so the name is looked up here; a typo or a renamed
    # tab fails loudly instead of fetching some other tab.
    tabs = list_tabs(sheet_id, timeout, session) if known_tabs is None else known_tabs
    if tab not in tabs:
        raise DownloadError("input", "No tab named '{}'. Tabs in this sheet: {}.".format(
            tab, ", ".join(tabs) or "none found"))
    response = _get(session, sheet_url(sheet_id, tabs[tab]), timeout)

    # A sheet that isn't link-shared redirects to a sign-in page and still
    # answers 200, so v1 happily wrote HTML into a .csv. Catch that.
    if "text/html" in response.headers.get("content-type", ""):
        raise DownloadError("private", PRIVATE_MESSAGE)

    # The live file, then a mirror under <folder>/data/. Same bytes, same name:
    # a plain second copy, overwritten every run, with no history kept.
    mirror = dest.parent / MIRROR_DIRNAME / dest.name
    for path in (dest, mirror):
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(response.content)
            os.replace(tmp, path)   # a reader sees the old file or the new one, never half
        except OSError as exc:
            with suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise DownloadError("write", f"Could not write {path}: {exc}") from exc
    return dest
