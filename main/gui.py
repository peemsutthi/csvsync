"""Tk front end: theme, widgets, wiring. No network or filesystem logic lives here."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, font, ttk

from . import config
from .downloader import DownloadError, download

# --- design tokens: the entire visual identity -------------------------------
BG = "#F4F2ED"      # kinari, unbleached paper
FIELD = "#FCFBF9"
INK = "#1F1D1A"     # sumi
MUTED = "#8C8880"
LINE = "#DFDBD2"    # hairline
ACCENT = "#2E4A62"  # ai, muted indigo
OK = "#5E7A5A"
ERR = "#A85A4A"
PAD, GAP = 28, 18

STATUS_COLOR = {"idle": MUTED, "busy": ACCENT, "ok": OK, "error": ERR}


def apply_theme(root):
    """clam honours colours; aqua and vista draw natively and ignore them."""
    fams = set(font.families())
    fam = next((f for f in ("Helvetica Neue", "Segoe UI", "Noto Sans") if f in fams),
               font.nametofont("TkDefaultFont").cget("family"))
    f_title, f_sect, f_label, f_field = (fam, 13), (fam, 9), (fam, 10), (fam, 12)

    root.configure(bg=BG)
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=INK, font=f_field, borderwidth=0)
    style.configure("TEntry", fieldbackground=FIELD, bordercolor=LINE, lightcolor=LINE,
                    darkcolor=LINE, borderwidth=1, relief="flat", padding=7,
                    insertcolor=INK, foreground=INK)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])
    style.configure("Title.TLabel", font=f_title, foreground=INK)
    style.configure("Sect.TLabel", font=f_sect, foreground=MUTED)
    style.configure("Label.TLabel", font=f_label, foreground=MUTED)
    style.configure("Muted.TLabel", font=f_label, foreground=MUTED)
    style.configure("TSeparator", background=LINE)
    style.configure("TCheckbutton", font=f_label, foreground=INK, indicatorbackground=FIELD,
                    indicatorforeground=INK, focuscolor=BG, padding=0)
    style.map("TCheckbutton", indicatorbackground=[("selected", ACCENT)],
              indicatorforeground=[("selected", BG)], background=[("active", BG)])
    style.configure("TButton", font=f_label, borderwidth=1, relief="flat", padding=(16, 8),
                    background=BG, foreground=INK, bordercolor=LINE, focuscolor=BG,
                    lightcolor=BG, darkcolor=BG)
    style.map("TButton", background=[("active", "#EAE7E0")],
              bordercolor=[("active", MUTED)], foreground=[("disabled", MUTED)])
    style.configure("Primary.TButton", background=INK, foreground=BG, bordercolor=INK,
                    lightcolor=INK, darkcolor=INK)
    style.map("Primary.TButton", background=[("active", ACCENT), ("disabled", LINE)],
              bordercolor=[("active", ACCENT), ("disabled", LINE)],
              foreground=[("disabled", MUTED)])
    style.configure("Quiet.TButton", background=BG, foreground=ACCENT, bordercolor=BG,
                    padding=(8, 8))
    style.map("Quiet.TButton", background=[("active", BG)], foreground=[("active", INK)])


def _tracked(text):
    """Fake letterspacing for section markers; Tk has no tracking option."""
    return " ".join(text.upper())


class App:
    def __init__(self, root):
        self.root = root
        self.log = config.get_logger()
        self.stop_event = threading.Event()
        self.worker = None
        self.messages = queue.Queue()   # worker -> UI; Tk is not thread-safe
        self._last_state = "idle"

        settings = config.load()
        self.sheet_id = tk.StringVar(value=settings["sheet_id"])
        self.tab = tk.StringVar(value=settings["tab"])
        self.filename = tk.StringVar(value=settings["filename"])
        self.folder = tk.StringVar(value=settings["folder"])
        self.interval = tk.StringVar(value=str(settings["interval"]))
        self.loop = tk.BooleanVar(value=settings["loop"])

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain)

    # --- layout --------------------------------------------------------------
    def _build(self):
        self.root.title("SheetSync")
        frame = ttk.Frame(self.root, padding=(PAD, PAD - 4, PAD, PAD - 8))
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._frame, self._row = frame, 0

        ttk.Label(frame, text="SheetSync", style="Title.TLabel").grid(
            row=self._next(), column=0, sticky="w")
        ttk.Label(frame, text="Keeps a published Google Sheet mirrored to a local CSV.",
                  style="Muted.TLabel").grid(row=self._next(), column=0, sticky="w",
                                             pady=(2, 0))

        self._section("source")
        self._field("Sheet ID", self.sheet_id)
        self._field("Tab name", self.tab)

        self._section("output")
        self._field("File name", self.filename, suffix=".csv")
        self._field("Folder", self.folder, button=("Choose…", self.browse))

        self._section("schedule")
        row = ttk.Frame(frame)
        row.grid(row=self._next(), column=0, sticky="w")
        ttk.Checkbutton(row, text="Repeat every", variable=self.loop).grid(row=0, column=0)
        ttk.Entry(row, width=4, justify="center", textvariable=self.interval).grid(
            row=0, column=1, padx=8)
        ttk.Label(row, text="seconds", style="Label.TLabel").grid(row=0, column=2)

        ttk.Separator(frame).grid(row=self._next(), column=0, sticky="ew",
                                  pady=(GAP + 4, 12))

        foot = ttk.Frame(frame)
        foot.grid(row=self._next(), column=0, sticky="ew")
        foot.columnconfigure(1, weight=1)
        self.dot = tk.Canvas(foot, width=7, height=7, bg=BG, highlightthickness=0)
        self.dot.grid(row=0, column=0, padx=(0, 8))
        self.dot_id = self.dot.create_rectangle(0, 0, 6, 6, fill=MUTED, outline="")
        self.status = ttk.Label(foot, text="Idle", style="Muted.TLabel")
        self.status.grid(row=0, column=1, sticky="w")
        self.stop_button = ttk.Button(foot, text="Stop", state="disabled", command=self.stop)
        self.stop_button.grid(row=0, column=2, padx=(0, 8))
        self.start_button = ttk.Button(foot, text="Start", style="Primary.TButton",
                                       command=self.start)
        self.start_button.grid(row=0, column=3)

        self.root.update_idletasks()
        self.root.minsize(420, self.root.winfo_reqheight())
        self.root.resizable(True, False)

    def _next(self):
        self._row += 1
        return self._row - 1

    def _section(self, text):
        ttk.Label(self._frame, text=_tracked(text), style="Sect.TLabel").grid(
            row=self._next(), column=0, sticky="w", pady=(GAP, 6))

    def _field(self, label, variable, suffix=None, button=None):
        ttk.Label(self._frame, text=label, style="Label.TLabel").grid(
            row=self._next(), column=0, sticky="w")
        row = ttk.Frame(self._frame)
        row.grid(row=self._next(), column=0, sticky="ew", pady=(3, 10))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=variable).grid(row=0, column=0, sticky="ew")
        if suffix:
            ttk.Label(row, text=suffix, style="Muted.TLabel").grid(row=0, column=1,
                                                                  padx=(8, 0))
        if button:
            text, command = button
            ttk.Button(row, text=text, style="Quiet.TButton", command=command).grid(
                row=0, column=1, padx=(6, 0))

    # --- actions -------------------------------------------------------------
    def browse(self):
        chosen = filedialog.askdirectory()
        if chosen:
            self.folder.set(chosen)

    def settings_dict(self, interval):
        return {"sheet_id": self.sheet_id.get().strip(), "tab": self.tab.get().strip(),
                "filename": self.filename.get().strip(), "folder": self.folder.get().strip(),
                "interval": interval, "loop": bool(self.loop.get())}

    def start(self):
        if self.worker and self.worker.is_alive():
            self._show("busy", "Already running.")
            return
        try:
            interval = int(self.interval.get().strip())
            if interval < 1:
                raise ValueError
        except ValueError:
            self._show("error", "Repeat interval must be a whole number of seconds, 1 or more.")
            return
        if not (self.sheet_id.get().strip() and self.tab.get().strip()):
            self._show("error", "Enter both a Sheet ID and a tab name.")
            return

        settings = self.settings_dict(interval)
        config.save(settings)
        self.stop_event.clear()
        self.start_button.state(["disabled"])
        self.stop_button.state(["!disabled"])
        self._show("busy", "Downloading…")
        self.worker = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()   # ends the wait immediately; an in-flight request
        self._show("busy", "Stopping…")  # is bounded by the download timeout

    def close(self):
        self.stop_event.set()
        config.save(self.settings_dict(self._interval_or_default()))
        self.root.destroy()

    def _interval_or_default(self):
        try:
            return max(1, int(self.interval.get().strip()))
        except ValueError:
            return config.DEFAULTS["interval"]

    # --- worker thread: posts to the queue, never touches a widget -----------
    def _run(self, settings):
        while True:
            try:
                dest = download(settings["sheet_id"], settings["tab"],
                                settings["folder"], settings["filename"])
                self.log.info("saved %s", dest)
                self.messages.put(("ok", f"Saved {dest}"))
            except DownloadError as exc:
                self.log.error("%s: %s", exc.kind, exc)
                self.messages.put(("error", str(exc)))
            if not settings["loop"] or self.stop_event.wait(settings["interval"]):
                break
        self.messages.put(("done", None))

    def _drain(self):
        try:
            while True:
                state, text = self.messages.get_nowait()
                if state == "done":
                    self.start_button.state(["!disabled"])
                    self.stop_button.state(["disabled"])
                    if self._last_state == "busy":   # stopped before any result
                        self._show("idle", "Stopped.")
                else:
                    self._show(state, text)
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def _show(self, state, text):
        self._last_state = state
        self.status.configure(text=text)
        self.dot.itemconfigure(self.dot_id, fill=STATUS_COLOR[state])


def main():
    root = tk.Tk()
    apply_theme(root)
    App(root)
    root.mainloop()
