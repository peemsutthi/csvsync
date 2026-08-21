"""Runs under pytest, or standalone: python3 tests/test_gui.py

Only the pure helpers — importing main.gui needs tkinter but no display, and
nothing here builds a Tk root.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main.gui import (FOLDER_CHARS, countdown, short_path, summary_text,
                      tape_line)


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


def test_countdown_rounds_and_never_goes_negative():
    assert countdown(12.4) == "next in 12s"
    assert countdown(12.6) == "next in 13s"
    assert countdown(0.0) == "next in 0s"
    assert countdown(-3.0) == "next in 0s"      # a late tick must not read "-3s"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print("\n{} passed".format(len(tests)))
