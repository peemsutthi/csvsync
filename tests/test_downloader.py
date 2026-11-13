"""Runs under pytest, or standalone: python3 tests/test_downloader.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from main.downloader import (DownloadError, download, list_tabs, sheet_id_from,
                             sheet_url, tab_names, target_path)

# What the public htmlview page holds for a sheet with one tab, "Sheet1".
TABS_PAGE = 'items.push({name: "Sheet1", pageUrl: "x", gid: "0",initialSheet: ("0" == gid)});'


class FakeResponse:
    def __init__(self, status_code=200, content=b"a,b\n1,2\n", content_type="text/csv"):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type}
        self.text = content.decode("utf-8")


class FakeSession:
    """Stands in for `requests`; records the call or raises what it was given."""

    def __init__(self, response=None, error=None, tabs_page=TABS_PAGE):
        self.response, self.error, self.calls = response or FakeResponse(), error, []
        self.tabs_page = tabs_page

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        if url.endswith("/htmlview"):
            return FakeResponse(content=self.tabs_page.encode(), content_type="text/html")
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
    assert "/spreadsheets/d/abc123/gviz" in session.calls[0][0]


def test_sheet_name_is_url_encoded():
    url = sheet_url("abc123", "Sheet 1 & 2/Q3")
    assert "sheet=Sheet%201%20%26%202%2FQ3" in url
    assert " " not in url


def test_sheet_id_is_encoded_defensively():
    assert "/gviz" in sheet_url("a/../b", "T")
    assert sheet_url("a/../b", "T").count("/gviz") == 1


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
    assert "sheet=Data%20" in session.calls[0][0]


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
    assert tab_names(page) == ["Q3 & Q4", "a/b", 'say "hi"', "ยอดขาย", "ยอด"], tab_names(page)
    assert tab_names("<html>sign in</html>") == []


def test_list_tabs_reads_the_pasted_links_sheet():
    session = FakeSession()
    assert list_tabs("https://docs.google.com/spreadsheets/d/abc/edit#gid=0",
                     session=session) == ["Sheet1"]
    assert session.calls[0][0].endswith("/d/abc/htmlview"), session.calls


def test_unwritable_destination_is_a_write_error():
    with tempfile.TemporaryDirectory() as folder:
        blocker = Path(folder) / "blocker"
        blocker.write_text("not a directory")
        try:
            download("abc", "Sheet1", blocker / "sub", "out", session=FakeSession())
            raise AssertionError("expected DownloadError")
        except DownloadError as exc:
            assert exc.kind == "write"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print("\n{} passed".format(len(tests)))
