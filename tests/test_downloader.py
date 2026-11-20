"""Runs under pytest, or standalone: python3 tests/test_downloader.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from main.downloader import (DownloadError, download, list_tabs, sheet_id_from,
                             sheet_info, sheet_url, tab_gids, target_path)

# What the public htmlview page holds for a sheet with one tab, "Sheet1".
TABS_PAGE = 'items.push({name: "Sheet1", pageUrl: "x", gid: "0",initialSheet: ("0" == gid)});'


class FakeResponse:
    def __init__(self, status_code=200, content=b"a,b\n1,2\n", content_type="text/csv",
                 url=""):
        self.status_code, self.url = status_code, url
        self.content = content
        self.headers = {"content-type": content_type}
        self.text = content.decode("utf-8")


class FakeSession:
    """Stands in for `requests`; records the call or raises what it was given."""

    def __init__(self, response=None, error=None, tabs_page=TABS_PAGE, tabs_url=None):
        self.response, self.error, self.calls = response or FakeResponse(), error, []
        self.tabs_page, self.tabs_url = tabs_page, tabs_url     # tabs_url: where htmlview landed

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        if url.endswith("/htmlview"):
            return FakeResponse(content=self.tabs_page.encode(), content_type="text/html",
                                url=self.tabs_url or url)
        return self.response


def test_pasted_url_yields_the_bare_id():
    """The address bar is what people actually copy, in each of its shapes."""
    expected = "1AbC_dEf-GhIjK123"
    for pasted in (
        "https://docs.google.com/spreadsheets/d/1AbC_dEf-GhIjK123/edit#gid=0",
        "https://docs.google.com/spreadsheets/d/1AbC_dEf-GhIjK123/edit?usp=sharing",
        "https://docs.google.com/spreadsheets/d/1AbC_dEf-GhIjK123",
        "  https://docs.google.com/spreadsheets/d/1AbC_dEf-GhIjK123/edit  ",
    ):
        assert sheet_id_from(pasted) == expected, pasted
    assert sheet_id_from(expected) == expected          # bare ID passes through
    assert sheet_id_from("") == ""                      # still caught as "input"


def test_download_accepts_a_pasted_url():
    session = FakeSession()
    with tempfile.TemporaryDirectory() as folder:
        download("https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
                 "Sheet1", folder, "out", session=session)
    assert "/spreadsheets/d/abc123/export" in session.calls[-1][0], session.calls


def test_export_url_is_by_gid():
    assert sheet_url("abc123", "569181446").endswith("/d/abc123/export?format=csv&gid=569181446")


def test_the_chosen_tabs_gid_is_fetched():
    """Not gviz by name: it blanks cells whose type differs from the column's majority."""
    page = TABS_PAGE + 'items.push({name: "Q3 & Q4", pageUrl: "x", gid: "123"});'
    session = FakeSession(tabs_page=page)
    with tempfile.TemporaryDirectory() as folder:
        download("abc", "Q3 & Q4", folder, "out", session=session)
    assert session.calls[-1][0].endswith("/export?format=csv&gid=123"), session.calls


def test_sheet_id_is_encoded_defensively():
    assert "/export" in sheet_url("a/../b", "0")
    assert sheet_url("a/../b", "0").count("/export") == 1


def test_extension_is_not_doubled():
    assert target_path(".", "report.csv").name == "report.csv"
    assert target_path(".", "report").name == "report.csv"
    assert target_path(".", "   ").name == "downloaded_google_sheet.csv"


def test_missing_input_is_its_own_error_kind():
    for sheet_id, tab in (("", "Sheet1"), ("abc", ""), ("  ", " ")):
        try:
            download(sheet_id, tab, session=FakeSession())
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "input"


def test_success_writes_the_csv_and_passes_a_timeout():
    with tempfile.TemporaryDirectory() as folder:
        session = FakeSession()
        dest = download("abc", "Sheet1", folder, "out", timeout=7, session=session)
        assert dest == Path(folder) / "out.csv"
        assert dest.read_bytes() == b"a,b\n1,2\n"
        assert session.calls[0][1] == 7


def test_mirror_copy_is_written_next_to_the_live_file():
    with tempfile.TemporaryDirectory() as folder:
        dest = download("abc", "Sheet1", folder, "out", session=FakeSession())
        mirror = Path(folder) / "data" / "out.csv"
        assert mirror.exists(), "no mirror written"
        assert mirror.read_bytes() == dest.read_bytes()


def test_mirror_is_overwritten_not_versioned():
    with tempfile.TemporaryDirectory() as folder:
        download("abc", "Sheet1", folder, "out", session=FakeSession())
        download("abc", "Sheet1", folder, "out",
                 session=FakeSession(FakeResponse(content=b"x,y\n9,9\n")))
        copies = sorted(p.name for p in (Path(folder) / "data").iterdir())
        assert copies == ["out.csv"], copies
        assert (Path(folder) / "data" / "out.csv").read_bytes() == b"x,y\n9,9\n"


def test_error_kinds_are_distinguished():
    cases = [
        (FakeSession(FakeResponse(status_code=404)), "http"),
        (FakeSession(FakeResponse(content_type="text/html; charset=utf-8")), "private"),
        (FakeSession(error=requests.Timeout()), "timeout"),
        (FakeSession(error=requests.ConnectionError("no route")), "network"),
    ]
    with tempfile.TemporaryDirectory() as folder:
        for session, expected in cases:
            try:
                download("abc", "Sheet1", folder, "out", session=session)
                raise AssertionError("expected DownloadError " + expected)
            except DownloadError as exc:
                assert exc.kind == expected, (exc.kind, expected)


def test_unknown_tab_is_refused_and_nothing_written():
    """gviz answers a mistyped tab with the first tab's data; that must not land."""
    with tempfile.TemporaryDirectory() as folder:
        try:
            download("abc", "sheet1", folder, "out", session=FakeSession())
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "input" and "Sheet1" in str(exc), str(exc)
        assert not (Path(folder) / "out.csv").exists()


def test_tab_with_trailing_space_matches_exactly():
    """The dropdown offers the real name; stripping it made the tab unsyncable."""
    session = FakeSession(tabs_page='items.push({name: "Data ", gid: "0"});')
    with tempfile.TemporaryDirectory() as folder:
        download("abc", "Data ", folder, "out", session=session)
    assert session.calls[-1][0].endswith("gid=0"), session.calls


def test_server_side_http_error_does_not_blame_the_input():
    for status, blames_input in ((429, False), (503, False), (404, True)):
        try:
            download("abc", "Sheet1", session=FakeSession(response=FakeResponse(status_code=status)))
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "http" and ("Check the Sheet ID" in str(exc)) == blames_input, str(exc)


def test_tab_names_are_unescaped():
    page = "".join('items.push({name: "%s", gid: "%d"});' % (raw, i) for i, raw in enumerate(
        [r"Q3 \x26 Q4", r"a\/b", r'say \"hi\"', "ยอดขาย", r"\u0e22\u0e2d\u0e14"]))
    assert tab_gids(page) == {"Q3 & Q4": "0", "a/b": "1", 'say "hi"': "2", "ยอดขาย": "3",
                              "ยอด": "4"}, tab_gids(page)
    assert tab_gids("<html>sign in</html>") == {}


def test_gids_are_read_from_the_live_page_shape():
    """As Google served it (2026-11): the pageUrl between name and gid holds escapes."""
    page = (r'items.push({name: "2026", pageUrl: "https:\/\/docs.google.com\/spreadsheets\/d\/x'
            r'\/htmlview\/sheet?headers\x3dtrue&gid=569181446", gid: "569181446",initialSheet: '
            r'("569181446" == gid)});'
            r'items.push({name: "2025", pageUrl: "https:\/\/x?headers\x3dtrue&gid=0", gid: "0",'
            r'initialSheet: ("0" == gid)});')
    assert tab_gids(page) == {"2026": "569181446", "2025": "0"}, tab_gids(page)
    # A tab without a gid is left out (and so refused), never given the next tab's gid.
    assert tab_gids('items.push({name: "A", pageUrl: "x"});' + TABS_PAGE) == {"Sheet1": "0"}


def test_list_tabs_reads_the_pasted_links_sheet():
    session = FakeSession()
    assert list_tabs("https://docs.google.com/spreadsheets/d/abc/edit#gid=0",
                     session=session) == {"Sheet1": "0"}
    assert session.calls[0][0].endswith("/d/abc/htmlview"), session.calls


def test_sheet_info_reads_title_and_tabs_in_one_request():
    page = ('<html><head><title>Q3 &amp; Q4 budget - Google Sheets</title></head>'
            + TABS_PAGE + TABS_PAGE.replace("Sheet1", "Notes").replace('"0"', '"7"'))
    session = FakeSession(tabs_page=page)
    info = sheet_info("https://docs.google.com/spreadsheets/d/abc/edit#gid=0", session=session)
    assert info == {"title": "Q3 & Q4 budget", "tabs": ["Sheet1", "Notes"],
                    "gids": {"Sheet1": "0", "Notes": "7"}}, info
    assert len(session.calls) == 1 and session.calls[0][0].endswith("/d/abc/htmlview")


def test_sheet_title_suffix_is_stripped_in_any_language():
    """Google localises the suffix (seen live: " - Google ไดรฟ์"); only the last one goes."""
    for raw, title in (("Tracker - Google ไดรฟ์", "Tracker"),
                       ("Ads - Google Ads export - Google Sheets", "Ads - Google Ads export"),
                       ("No suffix", "No suffix")):
        page = "<title>%s</title>%s" % (raw, TABS_PAGE)
        assert sheet_info("abc", session=FakeSession(tabs_page=page))["title"] == title, raw
    assert sheet_info("abc", session=FakeSession())["title"] == ""     # no <title> at all


def test_sheet_info_reports_a_private_sheet():
    """A private sheet redirects to sign-in, which answers 200 with no tab list."""
    session = FakeSession(tabs_page="<title>Sign in - Google Accounts</title>",
                          tabs_url="https://accounts.google.com/v3/signin/identifier?x=1")
    try:
        sheet_info("abc", session=session)
        raise AssertionError("expected DownloadError")
    except DownloadError as exc:
        assert exc.kind == "private", exc.kind


def test_sheet_info_passes_network_errors_through():
    for error, kind in ((requests.Timeout(), "timeout"), (requests.ConnectionError(), "network")):
        try:
            sheet_info("abc", session=FakeSession(error=error))
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == kind, exc.kind


def test_known_tabs_skip_the_tab_list_request():
    session = FakeSession()
    with tempfile.TemporaryDirectory() as folder:
        download("abc", "Sheet1", folder, "out", session=session, known_tabs={"Sheet1": "0"})
    assert len(session.calls) == 1 and "/export" in session.calls[0][0], session.calls


def test_known_tabs_still_refuse_an_unknown_tab():
    """Skipping the request must not skip the check: gviz would send the first tab."""
    session = FakeSession()
    with tempfile.TemporaryDirectory() as folder:
        try:
            download("abc", "Gone", folder, "out", session=session, known_tabs={"Sheet1": "0"})
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "input" and "Sheet1" in str(exc), str(exc)
        assert not (Path(folder) / "out.csv").exists()
    assert not any(url.endswith("/htmlview") for url, _ in session.calls)


def test_private_is_caught_before_known_tabs_are_used():
    session = FakeSession(FakeResponse(content_type="text/html; charset=utf-8"))
    try:
        download("abc", "Sheet1", session=session, known_tabs={"Sheet1": "0"})
        raise AssertionError("expected DownloadError")
    except DownloadError as exc:
        assert exc.kind == "private"


def test_unwritable_destination_is_a_write_error():
    with tempfile.TemporaryDirectory() as folder:
        blocker = Path(folder) / "blocker"
        blocker.write_text("not a directory")
        try:
            download("abc", "Sheet1", blocker / "sub", "out", session=FakeSession())
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "write"


def test_a_refused_write_keeps_the_old_file_and_leaves_no_temp():
    """The new bytes go to a .tmp and replace the file in one step: a reader never
    sees half a file, and a write that fails leaves the old one whole."""
    with tempfile.TemporaryDirectory() as folder:
        download("abc", "Sheet1", folder, "out", session=FakeSession())
        assert sorted(p.name for p in Path(folder).iterdir()) == ["data", "out.csv"]
        mirror = Path(folder) / "data" / "out.csv"
        mirror.unlink()
        mirror.mkdir()                  # the replace onto it now fails
        try:
            download("abc", "Sheet1", folder, "out",
                     session=FakeSession(FakeResponse(content=b"new\n")))
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "write"
        assert not list(Path(folder).rglob("*.tmp")), list(Path(folder).rglob("*"))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print("\n{} passed".format(len(tests)))
