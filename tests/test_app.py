"""Runs under pytest, or standalone: python3 tests/test_app.py

The Api and its worker, driven through a fake window (records evaluate_js) and
the fake session. Nothing here opens a real window.
"""
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from helpers import CSV, HTML, TABS_PAGE, FakeResponse, FakeSession, run_all
from main import app
from main.app import FOLDER_CHARS, Api, short_path, summary_text, tape_line

# Never touch the real log.
LOG = logging.getLogger("csvsync-test")
LOG.addHandler(logging.NullHandler())
LOG.propagate = False
DESKTOP = str(Path.home() / "Desktop")


class FakeWindow:
    """Records every event pushed to the page; `hook` may react to each one."""

    def __init__(self, hook=None, folder=None):
        self.scripts, self.events, self.hook, self.folder = [], [], hook, folder
        self.done = threading.Event()

    def evaluate_js(self, script):
        assert script.startswith("onEvent(") and script.endswith(")"), script
        self.scripts.append(script)
        self.events.append(json.loads(script[len("onEvent("):-1]))
        if self.hook:
            self.hook(self.events[-1])
        if self.events[-1]["type"] == "done":
            self.done.set()

    def wait_done(self, seconds=5):
        assert self.done.wait(seconds), "no done event: " + repr(self.types())

    def create_file_dialog(self, dialog_type):
        return (self.folder,) if self.folder else None

    def types(self):
        return [e["type"] for e in self.events]

    def count(self, kind):
        return self.types().count(kind)


def make_api(window=None, session=None):
    return Api(window or FakeWindow(), session=session or FakeSession(), log=LOG)


def settings(folder, interval=0, tab="Sheet1"):
    return {"sheet_id": "abc", "tab": tab, "filename": "out", "folder": folder,
            "interval": interval}


def run(session, folder, interval=0, tab="Sheet1"):
    """Start through the public API and wait for the worker to finish."""
    window = FakeWindow()
    assert make_api(window, session).start(settings(folder, interval, tab))["ok"]
    window.wait_done()
    return window


def loop(session, folder, stop_at_wait, hook=None):
    """Run the worker on this thread at 0.01 s (3 s is the shortest real choice)
    and press Stop on the `stop_at_wait`-th wait."""
    window = FakeWindow()
    api = make_api(window, session)

    def on_event(event):
        if hook:
            hook(event, window)
        if event["type"] == "wait" and window.count("wait") == stop_at_wait:
            api.stop()

    window.hook = on_event
    api._run(settings(folder, interval=0.01))
    return window


# --- the worker: which events, in which order ------------------------------------------
def test_success_once():
    window = FakeWindow()
    api = make_api(window)
    with TemporaryDirectory() as folder:
        assert api.start(settings(folder))["ok"]
        window.wait_done()
        assert window.types() == ["downloading", "saved", "done"], window.types()
        saved = window.events[1]
        assert saved["path"] == str(Path(folder) / "out.csv") == api._saved()
        assert datetime.strptime(saved["at"], "%H:%M:%S")
        assert (Path(folder) / "data" / "out.csv").exists()     # mirror still written


def test_before_the_first_save_every_failure_ends_even_a_loop():
    with TemporaryDirectory() as folder:
        for session, kind, tab in (
            (FakeSession(FakeResponse(content_type=HTML)), "private", "Sheet1"),
            (FakeSession(error=requests.Timeout()), "timeout", "Sheet1"),
            (FakeSession(), "input", "sheet1"),                 # no such tab
        ):
            window = run(session, folder, interval=3, tab=tab)
            assert window.types() == ["downloading", "failed", "done"], (kind, window.types())
            assert window.events[1]["kind"] == kind, window.events[1]
            assert not (Path(folder) / "out.csv").exists()
    assert "Sheet1" in window.events[1]["message"]      # the unknown tab names the real one


def test_unexpected_error_still_posts_done():
    """A non-DownloadError must not leave the page stuck in "downloading"."""
    with TemporaryDirectory() as folder:
        window = run(FakeSession(error=RuntimeError("boom")), folder, interval=3)
    assert window.types() == ["downloading", "failed", "done"], window.types()
    assert window.events[1]["kind"] == "unexpected"


def test_stop_mid_wait_is_immediate():
    window = FakeWindow()
    api = make_api(window)
    window.hook = lambda e: e["type"] == "wait" and api.stop()
    with TemporaryDirectory() as folder:
        assert api.start(settings(folder, interval=10))["ok"]
        window.wait_done(2)     # a 10 s wait that ignored Stop would fail here
    assert window.types() == ["downloading", "saved", "wait", "done"], window.types()
    assert window.events[2]["interval"] == 10 and window.events[2]["deadline_ms"] > 0


AFTER_ONE_FAILURE = ["downloading", "saved", "wait", "downloading", "failed",
                     "wait", "downloading", "saved", "wait", "done"]


def test_transient_failure_after_a_save_keeps_going():
    session = FakeSession(FakeResponse(), requests.Timeout(), FakeResponse())
    with TemporaryDirectory() as folder:
        window = loop(session, folder, stop_at_wait=3)
    assert window.types() == AFTER_ONE_FAILURE, window.types()
    assert window.events[4]["kind"] == "timeout"
    assert session.tab_reads() == 1, session.calls      # rechecked at most every TAB_RECHECK


def test_write_failure_after_a_save_keeps_going():
    """On Windows a CSV open in Excel refuses writes; that must not end a long run."""
    with TemporaryDirectory() as folder:
        live = Path(folder) / "out.csv"

        def lock_once(event, window):
            if event["type"] == "saved" and window.count("saved") == 1:
                live.unlink()
                live.mkdir()            # stands in for a locked file: the replace fails
            elif event["type"] == "failed":
                live.rmdir()

        window = loop(FakeSession(), folder, stop_at_wait=3, hook=lock_once)
        assert window.types() == AFTER_ONE_FAILURE, window.types()
        assert window.events[4]["kind"] == "write"
        assert live.read_bytes() == CSV


def test_tab_list_is_rechecked_once_stale():
    session = FakeSession()
    saved_recheck, app.TAB_RECHECK = app.TAB_RECHECK, 0
    try:
        with TemporaryDirectory() as folder:
            loop(session, folder, stop_at_wait=2)
    finally:
        app.TAB_RECHECK = saved_recheck
    assert session.tab_reads() == 2, session.calls


def test_events_are_json_so_names_from_google_cannot_break_out():
    tab = 'x"); alert(1); ("</script>'
    with TemporaryDirectory() as folder:
        window = run(FakeSession(), folder, tab=tab)
    failed = window.events[1]
    assert failed["type"] == "failed" and tab in failed["message"]
    assert window.scripts[1] == "onEvent(" + json.dumps(failed) + ")"


def test_a_closed_window_does_not_kill_the_worker():
    class Gone(FakeWindow):
        def evaluate_js(self, script):
            raise RuntimeError("window destroyed")

    api = make_api(Gone())
    with TemporaryDirectory() as folder:
        assert api.start(settings(folder))["ok"]
        worker = api._worker
        if worker:                      # None: already finished
            worker.join(5)
        assert api._worker is None and api._saved()


# --- the rest of the Api -----------------------------------------------------------------
def test_start_refuses_missing_fields_and_a_second_run():
    api = make_api()
    for key, field in (("sheet_id", "link"), ("tab", "tab"), ("folder", "folder")):
        answer = api.start(dict(settings("/tmp"), **{key: "  "}))
        assert answer == {"ok": False, "field": field, "message": answer["message"]}, answer
    assert api._worker is None

    gate = threading.Event()
    slow = FakeWindow(lambda e: gate.wait(5))
    api = make_api(slow)
    with TemporaryDirectory() as folder:
        first = api.start(settings(folder))
        second = api.start(settings(folder))
        gate.set()
        slow.wait_done()
    assert first["ok"] and first["file"] == "out.csv", first
    assert not second["ok"] and second["field"] is None, second


def test_start_answers_with_what_goes_where():
    window = FakeWindow()
    api = make_api(window, FakeSession(error=requests.Timeout()))   # so nothing is written
    answer = api.start(dict(settings(DESKTOP), filename="sales.csv"))
    window.wait_done()
    assert answer["file"] == "sales.csv" and answer["folder"] == str(Path("~") / "Desktop")
    assert answer["summary"] == summary_text("Sheet1", "sales.csv", DESKTOP)


def test_sheet_info_answers_rather_than_raises():
    page = "<title>Plan - Google Sheets</title>" + TABS_PAGE
    assert make_api(session=FakeSession(tabs_page=page)).sheet_info("abc") == {
        "title": "Plan", "tabs": ["Sheet1"], "gids": {"Sheet1": "0"}}
    private = FakeSession(tabs_url="https://accounts.google.com/ServiceLogin?continue=x",
                          tabs_page="sign in")
    assert make_api(session=private).sheet_info("abc")["kind"] == "private"
    odd = FakeSession(error=ValueError("odd"))
    assert make_api(session=odd).sheet_info("abc")["kind"] == "unexpected"


def test_choose_folder_returns_path_and_display():
    api = make_api(FakeWindow(folder=DESKTOP))
    assert api.choose_folder() == {"path": DESKTOP, "display": str(Path("~") / "Desktop")}
    assert make_api().choose_folder() is None       # cancelled


def test_nothing_to_open_before_a_save():
    api = make_api()
    assert api.open_file() is False and api.show_in_folder() is False


def test_settings_round_trip_through_the_page():
    api = make_api()
    api.save_settings({"sheet_id": " abc ", "tab": "Data ", "filename": "out",
                       "folder": DESKTOP, "interval": 5, "evil": 1})
    loaded = api.load_settings()
    assert loaded["sheet_id"] == "abc" and loaded["interval"] == 5 and "evil" not in loaded
    assert loaded["folder_display"] == str(Path("~") / "Desktop")


# --- pure helpers ---------------------------------------------------------------------------
def test_home_folders_are_shown_relative_to_home():
    assert short_path(DESKTOP) == str(Path("~") / "Desktop")
    assert short_path(str(Path.home())) == "~"
    assert short_path("/opt/data") == "/opt/data"      # outside home, shown whole
    assert short_path("") == short_path(None) == "no folder chosen"


def test_summary_says_what_goes_where():
    # The same extension handling as downloader.target_path, so the summary
    # names the file that actually gets written.
    for filename in ("sales", "sales.csv"):
        assert summary_text("Sheet1", filename, DESKTOP) == "Sheet1 → sales.csv · ~/Desktop"
    assert "downloaded_google_sheet.csv" in summary_text("Sheet1", "  ", DESKTOP)
    assert summary_text("", "sales", DESKTOP).startswith("— →")


def test_long_folders_are_elided_from_the_left():
    deep = "/opt/" + "/".join(["verylongsegment"] * 5)
    where = summary_text("Sheet1", "sales", deep).split(" · ")[1]
    assert len(where) == FOLDER_CHARS, where
    assert where.startswith("…") and deep.endswith(where[1:])   # tail preserved
    assert " · " not in short_path(deep)     # separator stays unambiguous


def test_tape_rows_share_one_column_grid():
    when = datetime(2026, 8, 21, 14, 32, 7)
    rows = [tape_line(when, "saved", "sales.csv"),
            tape_line(when, "failed", "That sheet isn't public.")]
    assert rows[0] == "14:32:07  saved   sales.csv\n"
    # Both verbs are padded to the same width, or the detail column zig-zags.
    assert len({row.index(row.split()[2]) for row in rows}) == 1
    assert all(row.endswith("\n") for row in rows)


if __name__ == "__main__":
    run_all(globals())
