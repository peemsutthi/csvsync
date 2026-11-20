"""Shared by the test files: a fake `requests`, an error-kind check, and the
standalone runner (so the tests need no pytest)."""
import tempfile
from pathlib import Path

from main import config
from main.downloader import DownloadError

# Never touch the real settings file. Here, so no test file can forget it.
config.SETTINGS_PATH = Path(tempfile.mkdtemp()) / "settings.json"

# What the public htmlview page holds for a sheet with one tab, "Sheet1".
TABS_PAGE = 'items.push({name: "Sheet1", pageUrl: "x", gid: "0",initialSheet: ("0" == gid)});'
CSV = b"a,b\n1,2\n"
HTML = "text/html; charset=utf-8"   # what a private sheet's export answers with


class FakeResponse:
    def __init__(self, status_code=200, content=CSV, content_type="text/csv", url=""):
        self.status_code, self.content, self.url = status_code, content, url
        self.headers = {"content-type": content_type}
        self.text = content.decode("utf-8")


class FakeSession:
    """Stands in for `requests` and records every (url, timeout).

    Export requests get `answers` in order, the last one repeating; an exception
    among them is raised. `error` is raised for every request, tab list included.
    The tab list (htmlview) answers `tabs_page`, landing on `tabs_url` if given.
    """

    def __init__(self, *answers, error=None, tabs_page=TABS_PAGE, tabs_url=None):
        self.answers, self.error = list(answers) or [FakeResponse()], error
        self.tabs_page, self.tabs_url, self.calls = tabs_page, tabs_url, []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        if url.endswith("/htmlview"):
            return FakeResponse(content=self.tabs_page.encode(), content_type="text/html",
                                url=self.tabs_url or url)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def tab_reads(self):
        return sum(url.endswith("/htmlview") for url, _ in self.calls)


def raises(kind, fn, *args, **kwargs):
    """Call fn, assert it raises a DownloadError of `kind`, and return that error."""
    try:
        fn(*args, **kwargs)
    except DownloadError as exc:
        assert exc.kind == kind, (exc.kind, kind, str(exc))
        return exc
    raise AssertionError("expected DownloadError " + kind)


def run_all(namespace):
    tests = [v for k, v in sorted(namespace.items()) if k.startswith("test_")]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print("\n{} passed".format(len(tests)))
