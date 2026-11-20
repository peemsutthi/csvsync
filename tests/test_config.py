"""Runs under pytest, or standalone: python3 tests/test_config.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from helpers import run_all     # also points config at a temp settings file
from main import config


def test_clean_keeps_only_known_keys_and_types():
    """Settings come from a file or the page, so anything may be in them."""
    settings = config.clean({"sheet_id": " abc ", "tab": "Data ", "interval": "5", "evil": 1})
    assert settings["sheet_id"] == "abc"
    assert settings["tab"] == "Data "               # real tab names can end in a space
    assert settings["interval"] == 10               # a string is not a number
    assert "evil" not in settings
    assert config.clean({"interval": True})["interval"] == 10
    assert config.clean(["not", "a", "dict"]) == config.clean({}) == config.DEFAULTS


def test_intervals_outside_the_choices_fall_back():
    for interval in config.INTERVALS:
        assert config.clean({"interval": interval})["interval"] == interval
    assert config.clean({"interval": 1})["interval"] == 10


def test_a_1x_file_migrates():
    assert config.clean({"interval": 30, "loop": False})["interval"] == 0     # "Repeat" off: Once
    assert config.clean({"interval": 30, "loop": True})["interval"] == 10


def test_save_then_load_round_trips():
    saved = config.clean({"sheet_id": "abc", "tab": "Data ", "interval": 3})
    config.save(saved)
    assert config.load() == saved
    assert not list(config.SETTINGS_PATH.parent.glob("*.tmp"))


def test_unreadable_or_missing_file_means_defaults():
    config.SETTINGS_PATH.write_text("{not json", encoding="utf-8")
    assert config.load() == config.DEFAULTS
    config.SETTINGS_PATH.unlink()
    assert config.load() == config.DEFAULTS


if __name__ == "__main__":
    run_all(globals())
