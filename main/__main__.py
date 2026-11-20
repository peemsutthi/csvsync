"""Entry point: `python -m main`, and the PyInstaller build target."""
import json
import sys

import webview
from webview.menu import Menu, MenuAction, MenuSeparator

from main.app import WEB_DIR, Api

MAC = sys.platform == "darwin"
REVEAL = "Show in Finder" if MAC else "Show in Folder"
# Cocoa key equivalents: lowercase is ⌘key, uppercase adds ⇧. pywebview's MenuAction
# has no shortcut field; on Windows the page handles Ctrl+key itself (web/app.js).
MAC_KEYS = {"Settings…": ",", "Start Sync": "r", "Stop": ".", "Open File": "o",
            REVEAL: "R", "Choose Folder…": "O"}


def build_menu(window):
    def item(title, name):
        # The page owns state (is a run going? is there a file yet?), so it decides.
        return MenuAction(title, lambda: window.evaluate_js("onMenu(%s)" % json.dumps(name)))

    settings = item("Settings…", "settings")
    file_items = [item("Start Sync", "start"), item("Stop", "stop"), MenuSeparator(),
                  item("Open File", "open"), item(REVEAL, "reveal"), MenuSeparator(),
                  item("Choose Folder…", "folder")]
    if MAC:
        return [Menu("__app__", [settings]), Menu("File", file_items)]
    return [Menu("File", [settings, MenuSeparator()] + file_items)]   # no app menu on Windows


def add_mac_shortcuts():
    """Set the key equivalents on the menu items pywebview built. Runs on page load:
    by then pywebview has set its final main menu."""
    import AppKit
    from PyObjCTools import AppHelper

    def apply():
        for top in AppKit.NSApp.mainMenu().itemArray():
            for entry in (top.submenu().itemArray() if top.submenu() else ()):
                if entry.title() in MAC_KEYS:
                    entry.setKeyEquivalent_(MAC_KEYS[entry.title()])

    AppHelper.callAfter(apply)


def main():
    api = Api()
    # A file:// URL, not a path: a bare path makes pywebview start a localhost HTTP server.
    window = webview.create_window("csvSync", (WEB_DIR / "index.html").as_uri(), js_api=api,
                                   width=440, height=720, min_size=(400, 640),
                                   background_color="#FAF9F6")
    window.events.closing += api.stop
    if MAC:
        window.events.loaded += add_mac_shortcuts
    webview.start(menu=build_menu(window))


if __name__ == "__main__":     # also true for the PyInstaller entry script
    main()
