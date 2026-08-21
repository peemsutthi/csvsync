"""Tk front end: theme, widgets, wiring. No network or filesystem logic lives here."""
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, font, ttk

from . import config
from .downloader import DownloadError, download

# --- design tokens: the entire visual identity -------------------------------
BG = "#FFFFFF"      
FIELD = "#FFFFFF"
INK = "#1F1D1A"     # sumi
MUTED = "#8C8880"
LINE = "#DFDBD2"    # hairline
ACCENT = "#2E4A62"  # ai, muted indigo
OK = "#5E7A5A"
ERR = "#A85A4A"
PAD, GAP = 28, 18

STATUS_COLOR = {"idle": MUTED, "busy": ACCENT, "ok": OK, "error": ERR}
STATUS_WORD = {"idle": "idle", "busy": "live", "ok": "live", "error": "live"}
TAPE_LINES = 500    # a week-long loop must not grow the buffer without bound
TAPE_SHORT, TAPE_TALL = 3, 10   # rows before Start, and once running


def _pick(families, *names, default):
    return next((n for n in names if n in families), default)


def apply_theme(root):
    """clam honours colours; aqua and vista draw natively and ignore them.

    Two type roles. Prose — labels, buttons, the state word — is set in a
    humanist sans. Everything the user *types* is set in mono, because a Sheet
    ID, a tab name, a filename and a path are all literals that have to match
    something exactly; a proportional face was always a small lie about them.
    """
    fams = set(font.families())
    ui = _pick(fams, "Avenir Next", "Segoe UI", "Noto Sans",
               default=font.nametofont("TkDefaultFont").cget("family"))
    mono = _pick(fams, "Menlo", "Consolas", "DejaVu Sans Mono",
                 default=font.nametofont("TkFixedFont").cget("family"))
    f_mark, f_sect = (mono, 24, "bold"), (mono, 9, "bold")
    f_label, f_field, f_tape = (ui, 10), (mono, 11), (mono, 10)

    root.configure(bg=BG)
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=INK, font=f_label, borderwidth=0)
    style.configure("TEntry", fieldbackground=FIELD, bordercolor=LINE, lightcolor=LINE,
                    darkcolor=LINE, borderwidth=1, relief="flat", padding=7,
                    insertcolor=INK, foreground=INK)
    style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)],
              foreground=[("disabled", MUTED)], fieldbackground=[("disabled", BG)])
    style.configure("Mark.TLabel", font=f_mark, foreground=INK)
    style.configure("Sect.TLabel", font=f_sect, foreground=MUTED)
    style.configure("Label.TLabel", font=f_label, foreground=MUTED)
    style.configure("Muted.TLabel", font=f_label, foreground=MUTED)
    style.configure("Mono.TLabel", font=f_tape, foreground=MUTED)
    # "Toolbutton" layout has no indicator element (only clam's TCheckbutton
    # layout does, and its indicator draws an X) — reused here flattened back
    # down to a plain label so the drawn ☑/☐ text is the only mark shown.
    style.configure("Check.Toolbutton", font=(ui, 15), padding=(0, 2), relief="flat",
                    borderwidth=0, background=BG, foreground=INK, focuscolor=ACCENT)
    style.map("Check.Toolbutton", background=[("selected", BG), ("active", BG)],
              foreground=[("active", ACCENT)])
    style.configure("TButton", font=f_label, borderwidth=1, relief="solid", padding=(16, 8),
                    background=BG, foreground=INK, bordercolor=LINE, focuscolor=ACCENT,
                    lightcolor=LINE, darkcolor=LINE)
    style.map("TButton", background=[("active", "#EAE7E0")],
              bordercolor=[("active", MUTED)], foreground=[("disabled", MUTED)])
    style.configure("Primary.TButton", background=INK, foreground=BG, bordercolor=INK,
                    lightcolor=INK, darkcolor=INK, focuscolor=BG)
    style.map("Primary.TButton", background=[("active", ACCENT), ("disabled", BG)],
              bordercolor=[("active", ACCENT), ("disabled", LINE)],
              lightcolor=[("active", ACCENT), ("disabled", LINE)],
              darkcolor=[("active", ACCENT), ("disabled", LINE)],
              foreground=[("disabled", MUTED)])
    style.configure("Quiet.TButton", background=BG, foreground=ACCENT, bordercolor=BG,
                    lightcolor=BG, darkcolor=BG, padding=(8, 8))
    style.map("Quiet.TButton", background=[("active", BG)], foreground=[("active", INK)])
    style.configure("Summary.TLabel", font=f_tape, foreground=INK)
    return f_field, f_tape      # clam ignores TEntry -font, so it goes on the widget


# --- pure helpers: no Tk, so tests/test_gui.py can check them ----------------
def short_path(folder):
    """Display form of a folder: `~/Desktop` beats `/Users/someone/Desktop`."""
    folder = (folder or "").strip()
    if not folder:
        return "no folder chosen"
    try:
        return str(Path("~") / Path(folder).relative_to(Path.home()))
    except ValueError:
        return folder


FOLDER_CHARS = 30   # keeps the summary inside a minimum-width window


def summary_text(tab, filename, folder):
    """One line standing in for the whole setup pane: what goes where.

    A folder too long to fit is elided from the *left*: the tail is the part
    that identifies it, and a hard clip at the label's edge just looks broken.
    """
    name = (filename or "").strip() or "downloaded_google_sheet"
    if name.lower().endswith(".csv"):
        name = name[:-4]
    where = short_path(folder)
    if len(where) > FOLDER_CHARS:
        where = "…" + where[-(FOLDER_CHARS - 1):]
    return "{} → {}.csv · {}".format((tab or "").strip() or "—", name, where)


def tape_line(when, verb, detail):
    """One ledger row. Column widths live here so the mono grid stays aligned."""
    return "{}  {:<8}{}\n".format(when.strftime("%H:%M:%S"), verb, detail)


def countdown(seconds_left):
    return "next in {}s".format(max(0, int(seconds_left + 0.5)))


class App:
    def __init__(self, root):
        self.root = root
        self.log = config.get_logger()
        self.stop_event = threading.Event()
        self.worker = None
        self.messages = queue.Queue()   # worker -> UI; Tk is not thread-safe
        self._deadline = None           # monotonic time of the next fetch
        self._interval = 0

        settings = config.load()
        self.sheet_id = tk.StringVar(value=settings["sheet_id"])
        self.tab = tk.StringVar(value=settings["tab"])
        self.filename = tk.StringVar(value=settings["filename"])
        self.folder = tk.StringVar(value=settings["folder"])
        self.interval = tk.StringVar(value=str(settings["interval"]))
        self.loop = tk.BooleanVar(value=settings["loop"])

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Return>", lambda _event: self.start())
        self.root.after(100, self._drain)

    # --- layout --------------------------------------------------------------
    def _build(self):
        self.root.title("csvSync")
        self.f_field, f_tape = apply_theme(self.root)
        frame = ttk.Frame(self.root, padding=(PAD, PAD - 4, PAD, PAD - 8))
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)     # the tape takes the slack

        self._header(frame)
        self._setup_pane(frame)
        self._summary(frame)
        self._tape_pane(frame, f_tape)
        self._rule(frame)
        self._foot(frame)

        self._state("idle")
        self.root.update_idletasks()
        self.root.minsize(440, 300)

    def _header(self, parent):
        head = ttk.Frame(parent)
        head.grid(row=0, column=0, sticky="ew", pady=(0, GAP))
        head.columnconfigure(1, weight=1)
        ttk.Label(head, text="csvSync", style="Mark.TLabel").grid(row=0, column=0, sticky="w")
        self.dot = tk.Canvas(head, width=7, height=7, bg=BG, highlightthickness=0)
        self.dot.grid(row=0, column=2, padx=(0, 7))
        self.dot_id = self.dot.create_rectangle(0, 0, 6, 6, fill=MUTED, outline="")
        self.state_word = ttk.Label(head, text="idle", style="Label.TLabel")
        self.state_word.grid(row=0, column=3, sticky="e")

    def _setup_pane(self, parent):
        self.setup = ttk.Frame(parent)
        self.setup.grid(row=1, column=0, sticky="ew")
        self.setup.columnconfigure(0, weight=1)
        self._frame, self._row, self._tails = self.setup, 0, []

        self._section("source")
        self._field("Sheet link or ID", self.sheet_id)
        self._field("Tab name", self.tab)

        self._section("output")
        self._field("File name", self.filename, suffix=".csv")
        self.folder_entry = self._field("Folder", self.folder,
                                        button=("Choose…", self.browse))

        row = ttk.Frame(self.setup)
        row.grid(row=self._next(), column=0, sticky="w", pady=(GAP - 8, GAP))
        self.repeat_chk = ttk.Checkbutton(row, style="Check.Toolbutton", variable=self.loop,
                                          command=self._sync_repeat_mark)
        self.repeat_chk.grid(row=0, column=0)
        self._sync_repeat_mark()
        repeat_label = ttk.Label(row, text="Repeat")
        repeat_label.grid(row=0, column=1, padx=(4, 10))
        repeat_label.bind("<Button-1>", lambda _e: self.repeat_chk.invoke())
        ttk.Label(row, text="every", style="Label.TLabel").grid(row=0, column=2, padx=(0, 8))
        interval = ttk.Entry(row, width=4, justify="center",
                             textvariable=self.interval, font=self.f_field)
        interval.grid(row=0, column=3)
        ttk.Label(row, text="seconds", style="Label.TLabel").grid(row=0, column=4, padx=(8, 0))
        self._align_tails()

    def _sync_repeat_mark(self):
        """clam's own indicator draws an X for "checked" — reads as "no" on a
        control that means "yes" — so the mark is drawn as text instead, at a
        larger size (Check.Toolbutton) than the "Repeat" label next to it."""
        self.repeat_chk.configure(text="☑" if self.loop.get() else "☐")

    def _align_tails(self):
        """One right edge for every entry. Without this the Folder row stops
        ~170px short of the others, because its trailing widget is a button and
        the File name row's is the word ".csv"."""
        self.setup.update_idletasks()
        tails = [row.grid_slaves(row=0, column=1) for row in self._tails]
        widest = max(tail[0].winfo_reqwidth() for tail in tails if tail)
        for row in self._tails:
            # Reserved on every row, including the two with nothing to put
            # there — an empty column is what keeps their entries in line.
            row.columnconfigure(1, minsize=widest + 6)

    def _summary(self, parent):
        """Stands in for the setup pane while running. A label plus a real
        button, rather than one clickable block: the button can say what it
        does, and it stays reachable from the keyboard."""
        self.summary = ttk.Frame(parent)
        self.summary.grid(row=2, column=0, sticky="ew", pady=(0, GAP))
        self.summary.columnconfigure(0, weight=1)
        self.summary_label = ttk.Label(self.summary, style="Summary.TLabel", width=1)
        self.summary_label.grid(row=0, column=0, sticky="ew")
        ttk.Button(self.summary, text="Edit", style="Quiet.TButton",
                   command=self.expand).grid(row=0, column=1, sticky="e")
        self.summary.grid_remove()

    def _tape_pane(self, parent, f_tape):
        """The run ledger: what this app is for, given the room to say it."""
        self.tape = tk.Text(parent, height=TAPE_SHORT, width=1, font=f_tape, wrap="word",
                            bg=BG, fg=INK, relief="flat", borderwidth=0,
                            cursor="arrow", spacing1=2, padx=0, pady=0,
                            # focusable, so keyboard users can reach scrollback;
                            # the ring only shows once it has focus
                            highlightthickness=1, highlightbackground=BG,
                            highlightcolor=ACCENT)
        self.tape.grid(row=3, column=0, sticky="nsew", pady=(0, 10))
        # Wrapped error text hangs under the message column, not the timestamp.
        indent = font.Font(font=f_tape).measure("00:00:00  " + " " * 8)
        self.tape.tag_configure("time", foreground=MUTED, lmargin2=indent)
        self.tape.tag_configure("ok", foreground=INK, lmargin2=indent)
        self.tape.tag_configure("error", foreground=ERR, lmargin2=indent)
        self.tape.tag_configure("empty", foreground=MUTED)
        self.tape.insert("end", "press Start to fetch the sheet", "empty")
        self.tape.configure(state="disabled")

    def _rule(self, parent):
        """The hairline under the tape is also the countdown: it fills as the
        interval elapses, and reaching the right edge is what prints the next
        line above it."""
        self.rule = tk.Canvas(parent, height=2, bg=LINE, highlightthickness=0)
        self.rule.grid(row=4, column=0, sticky="ew")
        self.rule_id = self.rule.create_rectangle(0, 0, 0, 2, fill=ACCENT, outline="")

    def _foot(self, parent):
        foot = ttk.Frame(parent)
        foot.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        foot.columnconfigure(0, weight=1)
        self.next_label = ttk.Label(foot, text="", style="Mono.TLabel")
        self.next_label.grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(foot, text="Stop", state="disabled", command=self.stop)
        self.stop_button.grid(row=0, column=1, padx=(0, 8))
        self.start_button = ttk.Button(foot, text="Start", style="Primary.TButton",
                                       command=self.start)
        self.start_button.grid(row=0, column=2)

    def _next(self):
        self._row += 1
        return self._row - 1

    def _section(self, text):
        ttk.Label(self._frame, text=text.upper(), style="Sect.TLabel").grid(
            row=self._next(), column=0, sticky="w", pady=(GAP, 6))

    def _field(self, label, variable, suffix=None, button=None):
        ttk.Label(self._frame, text=label, style="Label.TLabel").grid(
            row=self._next(), column=0, sticky="w")
        row = ttk.Frame(self._frame)
        row.grid(row=self._next(), column=0, sticky="ew", pady=(3, 10))
        row.columnconfigure(0, weight=1)
        entry = ttk.Entry(row, textvariable=variable, font=self.f_field)
        entry.grid(row=0, column=0, sticky="ew")
        if suffix:
            ttk.Label(row, text=suffix, style="Muted.TLabel").grid(
                row=0, column=1, sticky="w", padx=(8, 0))
        if button:
            text, command = button
            ttk.Button(row, text=text, style="Quiet.TButton", command=command).grid(
                row=0, column=1, sticky="w", padx=(6, 0))
        self._tails.append(row)
        return entry

    # --- collapsing ----------------------------------------------------------
    def collapse(self):
        """Fold setup away behind a summary of what the run is actually using.

        The fields stay enabled: Start is disabled while running, so the only
        way to apply an edit is Stop then Start, which re-reads them anyway.
        """
        self.summary_label.configure(text=summary_text(
            self.tab.get(), self.filename.get(), self.folder.get()))
        self.setup.grid_remove()
        self.summary.grid()
        self.tape.configure(height=TAPE_TALL)
        self._refit()

    def expand(self):
        self.summary.grid_remove()
        self.setup.grid()
        self.tape.configure(height=TAPE_SHORT)
        self._refit()

    def _refit(self):
        """Re-fit the height only. geometry("") would also reset the width,
        yanking the window narrower on Start and discarding a width the user
        chose by dragging."""
        self.root.update_idletasks()
        width = max(self.root.winfo_width(), self.root.winfo_reqwidth())
        self.root.geometry("{}x{}".format(width, self.root.winfo_reqheight()))

    # --- actions -------------------------------------------------------------
    def browse(self):
        chosen = filedialog.askdirectory()
        if chosen:
            self.folder.set(chosen)
            self.folder_entry.xview_moveto(1.0)   # show the tail, not the root

    def settings_dict(self, interval):
        return {"sheet_id": self.sheet_id.get().strip(), "tab": self.tab.get().strip(),
                "filename": self.filename.get().strip(), "folder": self.folder.get().strip(),
                "interval": interval, "loop": bool(self.loop.get())}

    def start(self):
        if self.start_button.instate(["disabled"]):
            return
        try:
            interval = int(self.interval.get().strip())
            if interval < 1:
                raise ValueError
        except ValueError:
            self._tape("error", "failed", "Repeat interval must be a whole number "
                                          "of seconds, 1 or more.")
            return
        if not (self.sheet_id.get().strip() and self.tab.get().strip()):
            self._tape("error", "failed", "Enter both a Sheet ID and a tab name.")
            return

        settings = self.settings_dict(interval)
        config.save(settings)
        self.stop_event.clear()
        self.start_button.state(["disabled"])
        self.stop_button.state(["!disabled"])
        self.collapse()
        self._state("busy")
        self.worker = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()   # ends the wait immediately; an in-flight request
        self._clear_countdown()  # is bounded by the download timeout
        self.stop_button.state(["disabled"])
        self.state_word.configure(text="stopping")

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
                self.messages.put(("ok", dest.name))
            except DownloadError as exc:
                self.log.error("%s: %s", exc.kind, exc)
                self.messages.put(("error", str(exc)))
            # Check the event before announcing a wait, or stopping mid-download
            # flashes a countdown that is already cancelled.
            if not settings["loop"] or self.stop_event.is_set():
                break
            self.messages.put(("wait", (time.monotonic() + settings["interval"],
                                        settings["interval"])))
            if self.stop_event.wait(settings["interval"]):
                break
        self.messages.put(("done", None))

    def _drain(self):
        try:
            while True:
                state, text = self.messages.get_nowait()
                if state == "wait":
                    self._deadline, self._interval = text
                elif state == "done":
                    self.start_button.state(["!disabled"])
                    self.stop_button.state(["disabled"])
                    self._clear_countdown()
                    self._state("idle")
                    self.expand()
                else:
                    self._state(state)
                    self._tape(state, "failed" if state == "error" else "saved", text)
        except queue.Empty:
            pass
        self._tick()
        self.root.after(100, self._drain)

    # --- display -------------------------------------------------------------
    def _state(self, state):
        self.state_word.configure(text=STATUS_WORD[state])
        self.dot.itemconfigure(self.dot_id, fill=STATUS_COLOR[state])

    def _tape(self, kind, verb, detail):
        self.tape.configure(state="normal")
        if self.tape.tag_ranges("empty"):
            self.tape.delete("1.0", "end")
        row = tape_line(datetime.now(), verb, detail)
        self.tape.insert("end", row[:10], "time")
        self.tape.insert("end", row[10:], "error" if kind == "error" else "ok")
        excess = int(self.tape.index("end-1c").split(".")[0]) - TAPE_LINES
        if excess > 0:
            self.tape.delete("1.0", "{}.0".format(excess + 1))
        self.tape.configure(state="disabled")
        self.tape.see("end")

    def _tick(self):
        """Advance the countdown rule. Rides _drain's existing 100ms timer."""
        if self._deadline is None:
            return
        left = self._deadline - time.monotonic()
        self.next_label.configure(text=countdown(left))
        done = 1 - max(0.0, min(1.0, left / self._interval)) if self._interval else 0
        self.rule.coords(self.rule_id, 0, 0, done * self.rule.winfo_width(), 2)

    def _clear_countdown(self):
        self._deadline = None
        self.next_label.configure(text="")
        self.rule.coords(self.rule_id, 0, 0, 0, 2)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
