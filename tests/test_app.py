"""Runs under pytest, or standalone: python3 tests/test_app.py

The Api and its worker, driven through a fake window (records evaluate_js) and
the fake session from test_downloader. Nothing here opens a real window.
"""
import json
import logging
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests

from main import app, config
from main.app import FOLDER_CHARS, Api, short_path, summary_text, tape_line
from test_downloader import TABS_PAGE, FakeResponse, FakeSession

# Never touch the real settings file or log.
_TMP = tempfile.mkdtemp()
config.SETTINGS_PATH = Path(_TMP) / "settings.json"
LOG = logging.getLogger("csvsync-test")
LOG.addHandler(logging.NullHandler())
LOG.propagate = False


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


class SequenceSession(FakeSession):
    """gviz answers come from a list in order: a FakeResponse, or an exception to raise."""

    def __init__(self, answers):
        super().__init__()
        self.answers = list(answers)

    def get(self, url, timeout=None):
        if url.endswith("/htmlview"):
            return super().get(url, timeout)
        self.calls.append((url, timeout))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def settings(folder, interval=0, tab="Sheet1"):
    return {"sheet_id": "abc", "tab": tab, "filename": "out", "folder": folder,
            "interval": interval}


def run(session, folder, interval=0, tab="Sheet1", hook=None):
    """Start through the public API and wait for the worker to finish."""
    window = FakeWindow(hook)
    api = Api(window, session=session, log=LOG)
    answer = api.start(settings(folder, interval, tab))
    assert answer["ok"], answer
    window.wait_done()
    return api, window


# --- event order -----------------------------------------------------------------
def test_success_once():
    with tempfile.TemporaryDirectory() as folder:
        api, window = run(FakeSession(), folder)
        assert window.types() == ["downloading", "saved", "done"], window.types()
        saved = window.events[1]
        assert saved["path"] == str(Path(folder) / "out.csv")
        assert datetime.strptime(saved["at"], "%H:%M:%S")
        assert (Path(folder) / "data" / "out.csv").exists()     # mirror still written
        assert api._saved() == saved["path"]


def test_private_sheet_ends_even_a_loop():
    session = FakeSession(FakeResponse(content_type="text/html; charset=utf-8"))
    with tempfile.TemporaryDirectory() as folder:
        _, window = run(session, folder, interval=3)
        assert window.types() == ["downloading", "failed", "done"], window.types()
        assert window.events[1]["kind"] == "private"
        assert not (Path(folder) / "out.csv").exists()


def test_timeout_before_any_save_ends_the_run():
    with tempfile.TemporaryDirectory() as folder:
        _, window = run(FakeSession(error=requests.Timeout()), folder, interval=3)
        assert window.types() == ["downloading", "failed", "done"], window.types()
        assert window.events[1]["kind"] == "timeout"


def test_unknown_tab_is_refused():
    with tempfile.TemporaryDirectory() as folder:
        _, window = run(FakeSession(), folder, interval=3, tab="sheet1")
        assert window.types() == ["downloading", "failed", "done"], window.types()
        assert window.events[1]["kind"] == "input" and "Sheet1" in window.events[1]["message"]
        assert not (Path(folder) / "out.csv").exists()


def test_stop_mid_wait_is_immediate():
    api_box = []

    def stop_on_wait(event):
        if event["type"] == "wait":
            api_box[0].stop()

    with tempfile.TemporaryDirectory() as folder:
        window = FakeWindow(stop_on_wait)
        api = Api(window, session=FakeSession(), log=LOG)
        api_box.append(api)
        assert api.start(settings(folder, interval=10))["ok"]
        window.wait_done(2)     # a 10 s wait that ignored Stop would fail here
        assert window.types() == ["downloading", "saved", "wait", "done"], window.types()
        wait = window.events[2]
        assert wait["interval"] == 10 and wait["deadline_ms"] > 0


def test_transient_failure_after_a_save_keeps_going():
    session = SequenceSession([FakeResponse(), requests.Timeout(), FakeResponse()])
    window, api = FakeWindow(), None

    def stop_after_third_download(event):
        if window.types().count("downloading") == 3 and event["type"] == "wait":
            api.stop()

    window.hook = stop_after_third_download
    with tempfile.TemporaryDirectory() as folder:
        api = Api(window, session=session, log=LOG)
        api._run(settings(folder, interval=0.01))   # direct: 3 s is the shortest real choice
        assert window.types() == ["downloading", "saved", "wait", "downloading", "failed",
                                  "wait", "downloading", "saved", "wait", "done"], window.types()
        assert window.events[4]["kind"] == "timeout"
        # One tab-list request for the whole run: it is rechecked at most every TAB_RECHECK.
        assert sum(url.endswith("/htmlview") for url, _ in session.calls) == 1, session.calls


def test_write_failure_after_a_save_keeps_going():
    """On Windows a CSV open in Excel refuses writes; that must not end a long run."""
    window, api = FakeWindow(), None
    with tempfile.TemporaryDirectory() as folder:
        live = Path(folder) / "out.csv"

        def lock_once(event):
            if event["type"] == "saved" and window.types().count("saved") == 1:
                live.unlink()
                live.mkdir()            # stands in for a locked file: the replace fails
            elif event["type"] == "failed":
                live.rmdir()
            elif event["type"] == "wait" and window.types().count("wait") == 3:
                api.stop()

        window.hook = lock_once
        api = Api(window, session=FakeSession(), log=LOG)
        api._run(settings(folder, interval=0.01))
        assert window.types() == ["downloading", "saved", "wait", "downloading", "failed",
                                  "wait", "downloading", "saved", "wait", "done"], window.types()
        assert window.events[4]["kind"] == "write"
        assert live.read_bytes() == b"a,b\n1,2\n"


def test_tab_list_is_rechecked_once_stale():
    session = SequenceSession([FakeResponse()])
    window, api = FakeWindow(), None
    window.hook = lambda e: e["type"] == "wait" and window.types().count("wait") == 2 and api.stop()
    saved_recheck, app.TAB_RECHECK = app.TAB_RECHECK, 0
    try:
        with tempfile.TemporaryDirectory() as folder:
            api = Api(window, session=session, log=LOG)
            api._run(settings(folder, interval=0.01))
    finally:
        app.TAB_RECHECK = saved_recheck
    assert sum(url.endswith("/htmlview") for url, _ in session.calls) == 2, session.calls


def test_events_are_json_so_names_from_google_cannot_break_out():
    tab = 'x"); alert(1); ("</script> '
    with tempfile.TemporaryDirectory() as folder:
        _, window = run(FakeSession(), folder, tab=tab)
        failed = window.events[1]
        assert failed["type"] == "failed" and tab in failed["message"]
        assert window.scripts[1] == "onEvent(" + json.dumps(failed) + ")"


def test_unexpected_error_still_posts_done():
    """A non-DownloadError must not leave the page stuck in "downloading"."""
    class Broken(FakeSession):
        def get(self, url, timeout=None):
            raise RuntimeError("boom")

    with tempfile.TemporaryDirectory() as folder:
        _, window = run(Broken(), folder, interval=3)
        assert window.types() == ["downloading", "failed", "done"], window.types()
        assert window.events[1]["kind"] == "unexpected"


def test_a_closed_window_does_not_kill_the_worker():
    class Gone(FakeWindow):
        def evaluate_js(self, script):
            raise RuntimeError("window destroyed")

    with tempfile.TemporaryDirectory() as folder:
        api = Api(Gone(), session=FakeSession(), log=LOG)
        assert api.start(settings(folder))["ok"]
        for _ in range(500):
            if api._worker is None:
                break
            threading.Event().wait(0.01)
        assert api._worker is None and api._saved()


# --- the rest of the Api -----------------------------------------------------------
def test_start_refuses_missing_fields_and_a_second_run():
    api = Api(FakeWindow(), session=FakeSession(), log=LOG)
    for key, field in (("sheet_id", "link"), ("tab", "tab"), ("folder", "folder")):
        answer = api.start(dict(settings("/tmp"), **{key: "  "}))
        assert answer == {"ok": False, "field": field, "message": answer["message"]}, answer
    assert api._worker is None

    gate = threading.Event()
    slow = FakeWindow(lambda e: gate.wait(5))
    api = Api(slow, session=FakeSession(), log=LOG)
    with tempfile.TemporaryDirectory() as folder:
        first = api.start(settings(folder))
        second = api.start(settings(folder))
        gate.set()
        slow.wait_done()
    assert first["ok"] and first["file"] == "out.csv", first
    assert not second["ok"] and second["field"] is None, second


def test_start_answers_with_what_goes_where():
    home = str(Path.home() / "Desktop")
    window = FakeWindow()
    api = Api(window, session=FakeSession(error=requests.Timeout()), log=LOG)
    answer = api.start(dict(settings(home), filename="sales.csv"))
    window.wait_done()
    assert answer["file"] == "sales.csv" and answer["folder"] == str(Path("~") / "Desktop")
    assert answer["summary"] == summary_text("Sheet1", "sales.csv", home)


def test_sheet_info_answers_rather_than_raises():
    api = Api(FakeWindow(), log=LOG,
              session=FakeSession(tabs_page="<title>Plan - Google Sheets</title>" + TABS_PAGE))
    assert api.sheet_info("abc") == {"title": "Plan", "tabs": ["Sheet1"], "gids": {"Sheet1": "0"}}
    api = Api(FakeWindow(), log=LOG, session=FakeSession(
        tabs_url="https://accounts.google.com/ServiceLogin?continue=x", tabs_page="sign in"))
    assert api.sheet_info("abc")["kind"] == "private"
    api = Api(FakeWindow(), log=LOG, session=FakeSession(error=ValueError("odd")))
    assert api.sheet_info("abc")["kind"] == "unexpected"


def test_choose_folder_returns_path_and_display():
    desktop = str(Path.home() / "Desktop")
    api = Api(FakeWindow(folder=desktop), log=LOG)
    assert api.choose_folder() == {"path": desktop, "display": str(Path("~") / "Desktop")}
    assert Api(FakeWindow(), log=LOG).choose_folder() is None     # cancelled


def test_nothing_to_open_before_a_save():
    api = Api(FakeWindow(), log=LOG)
    assert api.open_file() is False and api.show_in_folder() is False


def test_settings_round_trip_and_old_files_migrate():
    api = Api(FakeWindow(), log=LOG)
    api.save_settings({"sheet_id": " abc ", "tab": "Data ", "filename": "out",
                       "folder": "/tmp", "interval": 5, "evil": 1})
    loaded = api.load_settings()
    assert loaded["sheet_id"] == "abc" and loaded["tab"] == "Data " and loaded["interval"] == 5
    assert "evil" not in loaded and loaded["folder_display"] == "/tmp"
    assert config.clean({"interval": 30, "loop": False})["interval"] == 0     # 1.x "Repeat" off
    assert config.clean({"interval": 1, "loop": True})["interval"] == 10      # not a choice now
    assert config.clean({"interval": True})["interval"] == 10
    assert config.clean(["not", "a", "dict"]) == config.clean({})
    config.SETTINGS_PATH.write_text("{not json", encoding="utf-8")
    assert config.load() == config.clean({})


# --- pure helpers, ported from test_gui.py -----------------------------------------
def test_home_folders_are_shown_relative_to_home():
    assert short_path(str(Path.home() / "Desktop")) == str(Path("~") / "Desktop")
    assert short_path(str(Path.home())) == "~"
    assert short_path("/opt/data") == "/opt/data"      # outside home, shown whole
    assert short_path("") == "no folder chosen"
    assert short_path(None) == "no folder chosen"


def test_summary_says_what_goes_where():
    home = str(Path.home() / "Desktop")
    assert summary_text("Sheet1", "sales", home) == "Sheet1 → sales.csv · ~/Desktop"
    # The same extension handling as downloader.target_path, so the summary
    # names the file that actually gets written.
    assert summary_text("Sheet1", "sales.csv", home) == "Sheet1 → sales.csv · ~/Desktop"
    assert "downloaded_google_sheet.csv" in summary_text("Sheet1", "  ", home)
    assert summary_text("", "sales", home).startswith("— →")


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
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print("\n{} passed".format(len(tests)))
