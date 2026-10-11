#!/usr/bin/env python3
"""Karaoke Grabber — Tkinter front-end and workflow state machine.

Paste a YouTube link, Fetch, check the info card, tidy the song title,
trim and fade with the two sliders, listen with the preview buttons, pick
the key, transpose and speed, Save. See docs/product_spec.md §4–§6 and
docs/architecture.md §4, §5.3 and §5.4.

Work runs on one background worker at a time. Workers never touch
widgets: they put messages on ``self._q``, which ``_pump`` drains on the
Tk thread every 50 ms.
"""

from __future__ import annotations

import math
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

from karaokegrab import (cache, download, fetch, keys, naming, proc, render,
                         settings, timecode, tools, transpose, trim)
from karaokegrab.player import Player, slice_wav
from karaokegrab.rangeslider import RangeSlider
from karaokegrab.trim import TrimSpec
from karaokegrab.widgets import HAND, MAGENTA, PURPLE, Button, PencilButton, RoundButton

APP_NAME = "Karaoke Grabber"
KEY_NONE = "none"              # optional: no key leaves it out of the file name
THUMB_W, THUMB_H = 160, 90
PUMP_MS = 50

# Progress-bar stops during Fetch (docs/build_plan.md §7), so a long download never looks stuck.
STEP_LOOKUP = 0.03
STEP_THUMB = 0.08
STEP_DOWNLOAD = (0.10, 0.95)     # the download's own progress is spread over this range
STEP_FINISH = 0.98
TICK_MS = 50          # playback cursor refresh
PREVIEW_DEBOUNCE_MS = 250   # wait for a dragged slider to settle before rendering
TRANSPOSE_DEBOUNCE_MS = 600  # wait for − / + and speed clicks to stop before preparing audio

# --- states (docs/architecture.md §4) ---
IDLE = "idle"
FETCHING = "fetching"
DOWNLOADING = "downloading"
READY = "ready"
SAVING = "saving"
SAVED = "saved"
PREPARING = "preparing"            # making the audio for a new shift or speed
ERROR = "error"
CANCELLED = "cancelled"
BUSY = (FETCHING, DOWNLOADING, SAVING, PREPARING)
# Modifier bits that make a key press a shortcut for something else: Control,
# Command (Mod1) and, on the Mac, Option (Mod2). ⌘+ / ⌘− stay zoom keys.
SHORTCUT_MODS = 0x4 | 0x8 | (0x10 if sys.platform == "darwin" else 0)
TEXT_CLASSES = ("TEntry", "Entry", "TCombobox", "Text", "TSpinbox", "Spinbox")

CARD_BG = "#f6f2f9"
CARD_EDGE = "#e2d8ea"
MUTED = "#76707c"
WARN = MAGENTA
PILL_BG = "#eeebf2"
DARK = "#4d4458"


class TitleSheet(tk.Toplevel):
    """Edit the song title: a small modal window over the main one.
    Return saves, Esc cancels."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        light_appearance(self)
        self.app = app
        self.title("Song title")
        self.transient(app)
        self.resizable(False, False)
        self.value = tk.StringVar(value=app.title_var.get())

        frm = ttk.Frame(self, padding=16)
        frm.grid(sticky="nsew")
        ttk.Label(frm, text="Song title (used in the file name):").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.entry = ttk.Entry(frm, textvariable=self.value, width=48)
        self.entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 12))
        ttk.Button(frm, text="Cancel", command=self.close).grid(row=2, column=1, sticky="e")
        ttk.Button(frm, text="Save", command=self.save, default="active").grid(
            row=2, column=2, sticky="e", padx=(8, 0))
        frm.columnconfigure(0, weight=1)

        self.bind("<Return>", lambda _e: self.save())
        self.bind("<KP_Enter>", lambda _e: self.save())
        self.bind("<Escape>", lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_reqwidth()) // 2
        y = app.winfo_rooty() + 80
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        self.entry.icursor("end")
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def save(self) -> None:
        text = " ".join(self.value.get().split())
        if text:
            self.app.set_title(text)
        self.close()

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.app.title_sheet = None
        self.destroy()


def short_folder(folder: Path) -> str:
    """'~/Music/Karaoke' rather than '/Users/me/Music/Karaoke'."""
    try:
        return "~/" + str(folder.relative_to(Path.home())) if folder != Path.home() else "~"
    except ValueError:
        return str(folder)


def light_appearance(win: tk.Misc) -> None:
    """Keep the light look in Dark Mode: the window uses its own light
    colours (card, sliders, buttons), which aqua's dark text would make
    unreadable."""
    try:
        win.update_idletasks()      # Tk can't set the appearance of a window it hasn't made yet
        win.tk.call("::tk::unsupported::MacWindowStyle", "appearance", win._w, "aqua")
    except tk.TclError:
        pass


class PrereqDialog(tk.Toplevel):
    """F16: which tools are missing and the one command that installs them."""

    def __init__(self, app: App) -> None:
        super().__init__(app)
        light_appearance(self)
        self.app = app
        self.title("Karaoke Grabber needs a few free tools")
        self.transient(app)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.frm = ttk.Frame(self, padding=18)
        self.frm.grid(sticky="nsew")
        self._fill()
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_reqwidth()) // 2
        self.geometry(f"+{max(0, x)}+{app.winfo_rooty() + 60}")

    def _fill(self) -> None:
        for w in self.frm.winfo_children():
            w.destroy()
        found = self.app.tools
        self.command = found.install_command()
        names = ", ".join(found.missing)
        ttk.Label(self.frm, text=f"Missing: {names}", font=self.app.f_head).grid(
            row=0, column=0, columnspan=4, sticky="w")
        if found.brew is None:
            ttk.Label(self.frm, wraplength=420, justify="left", text=(
                "Homebrew isn't installed. It's the free tool that installs the rest. "
                "Install it from brew.sh (the README's Requirements section shows how), "
                "then click Check again.")).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 12))
            ttk.Button(self.frm, text="Open brew.sh",
                       command=lambda: webbrowser.open("https://brew.sh")).grid(row=3, column=0, sticky="w")
        else:
            ttk.Label(self.frm, wraplength=420, justify="left", text=(
                "Run this one command in Terminal, then click Check again:")).grid(
                row=1, column=0, columnspan=4, sticky="w", pady=(8, 6))
            box = ttk.Entry(self.frm, width=44, font="TkFixedFont")
            box.insert(0, self.command)
            box.configure(state="readonly")
            box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 12))
            ttk.Button(self.frm, text="Copy", command=self.copy).grid(row=2, column=3, padx=(8, 0), pady=(0, 12))
        ttk.Button(self.frm, text="Close", command=self.close).grid(row=3, column=2, sticky="e")
        ttk.Button(self.frm, text="Check again", command=self.check, default="active").grid(
            row=3, column=3, sticky="e", padx=(8, 0))

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.command)
        self.app.status_var.set("Copied. Paste it into Terminal and press Return.")

    def check(self) -> None:
        if self.app.recheck_tools():
            self.close()
        else:
            self._fill()

    def close(self) -> None:
        self.app.prereq_dialog = None
        self.destroy()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        light_appearance(self)
        self._closing = False
        self._afters: set[str] = set()
        self._q: queue.Queue = queue.Queue()
        self._token = 0                       # bumps on each Fetch; stale messages are dropped
        self._cancel: proc.Cancel | None = None
        self._worker: threading.Thread | None = None
        self._saving_part: Path | None = None      # deleted on quit if a save is cut short
        self.title_sheet: TitleSheet | None = None
        self.prereq_dialog: PrereqDialog | None = None
        self.source_url = ""
        self.saved_path: Path | None = None
        self._pending = None                        # action to rerun after a re-download
        self._redownloading = False
        self._status_before_preview = ""

        self.cfg = settings.load()
        self.tools = tools.locate()
        self.state = IDLE
        self.info: fetch.VideoInfo | None = None
        self.audio: Path | None = None
        self.details = ""
        self._thumb_img: tk.PhotoImage | None = None

        # Trim, fades and the playback cursor (M3). spec is always clamped.
        self.spec: TrimSpec | None = None
        self.cursor = 0.0
        self.player = Player()
        self._tmp = Path(tempfile.mkdtemp(prefix="karaoke-grabber-"))
        self._preview_token = 0
        self.preview_clip: Path | None = None       # WAV of the whole trimmed range, with fades
        self.preparing = False                      # the preview is being (re)made
        self._preview_cancel: proc.Cancel | None = None
        self._prep_after: str | None = None
        self._prep_status_saved = False
        self._ticking = False

        # Transpose (F17) and speed (F18). shift / speed are what the source
        # audio has now; the *_wanted values are what the controls show, ahead
        # of them while the audio is being prepared.
        self.shift = 0
        self.shift_wanted = 0
        self.speed = 100
        self.speed_wanted = 100
        self._transpose_token = 0
        self._transpose_after: str | None = None

        self.url_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.meta_var = tk.StringVar()
        self.key_var = tk.StringVar(value=KEY_NONE)
        self.shift_var = tk.StringVar(value="0")
        self.speed_var = tk.StringVar(value="100")
        self.heard_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.fetch_error_var = tk.StringVar()
        self.trim_note = tk.StringVar()
        self.fade_note = tk.StringVar()
        self.cursor_note = tk.StringVar()
        self.start_var = tk.StringVar(value="—")
        self.end_var = tk.StringVar(value="—")
        self.length_var = tk.StringVar()
        self.fade_in_var = tk.StringVar(value="—")
        self.fade_out_var = tk.StringVar(value="—")

        self.title(APP_NAME)
        self.minsize(640, 600)
        self._fonts()
        self._build()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # ⌘Q and the app-menu Quit bypass WM_DELETE_WINDOW on macOS.
        try:
            self.createcommand("tk::mac::Quit", self._on_close)
        except tk.TclError:
            pass

        self._bind_shortcuts()
        try:
            cache.prune()
        except OSError:
            pass

        self._set_state(IDLE)
        if not self.tools.ok:
            self._show_error(self.tools.problem(), where="fetch")
            self._after(300, self.show_prereq_dialog)
        else:
            self.status_var.set("Paste a YouTube link and click Fetch.")
        self.url_entry.focus_set()
        self._after(PUMP_MS, self._pump)

    def _bind_shortcuts(self) -> None:
        """F13: Space starts/stops the preview, = / + and − transpose, 0
        resets the transposition, ] / [ change the speed, \\ resets it, ⌘S saves (Return = Fetch is on the URL
        box). ⌘Q is tk::mac::Quit."""
        self.bind("<space>", self._space_key)
        for seq, step in (("<equal>", 1), ("<plus>", 1), ("<KP_Add>", 1),
                          ("<minus>", -1), ("<KP_Subtract>", -1)):
            self.bind(seq, lambda e, s=step: self._transpose_key(e, lambda: self.transpose_by(s)))
        for seq in ("<Key-0>", "<KP_0>"):
            self.bind(seq, lambda e: self._transpose_key(e, self.reset_shift))
        step = transpose.SPEED_STEP
        self.bind("<bracketright>", lambda e: self._transpose_key(e, lambda: self.speed_by(step)))
        self.bind("<bracketleft>", lambda e: self._transpose_key(e, lambda: self.speed_by(-step)))
        self.bind("<backslash>", lambda e: self._transpose_key(e, self.reset_speed))
        mod = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{mod}-s>", lambda _e: (self.save(), "break")[1])
        # A click outside a text field takes keyboard focus out of it, so Space
        # plays and pauses after clicking a slider (Canvas widgets don't take focus).
        self.bind_all("<Button-1>", self._click_focus, add="+")

    def _click_focus(self, e) -> None:
        w = e.widget
        if not hasattr(w, "winfo_class") or w.winfo_class() in TEXT_CLASSES:
            return
        try:
            w.winfo_toplevel().focus_set()
        except tk.TclError:
            pass

    def _space_key(self, e) -> str | None:
        cls = e.widget.winfo_class() if hasattr(e.widget, "winfo_class") else ""
        if cls in TEXT_CLASSES:
            return None                                # typing a space
        self.toggle_play()
        return "break"

    def _transpose_key(self, e, action) -> str | None:
        """The plain-key transpose shortcuts; typing in a text field wins.
        (A read-only dropdown takes no typing, so the keys work there too.)"""
        w = e.widget
        cls = w.winfo_class() if hasattr(w, "winfo_class") else ""
        if cls in TEXT_CLASSES and not (cls == "TCombobox" and str(w.cget("state")) == "readonly"):
            return None
        if (getattr(e, "state", 0) or 0) & SHORTCUT_MODS:
            return None
        action()
        return "break"

    def show_prereq_dialog(self) -> None:
        if self.prereq_dialog is None and not self.tools.ok and not self._closing:
            self.prereq_dialog = PrereqDialog(self)

    def recheck_tools(self) -> bool:
        self.tools = tools.locate()
        if self.tools.ok:
            self.status_var.set("All set. Paste a YouTube link and click Fetch.")
            self._set_state(IDLE if self.info is None else self.state)
            return True
        self.status_var.set(self.tools.problem())
        return False

    # ------------------------------------------------------------ plumbing
    def _after(self, ms: int, fn) -> str:
        """Schedule a callback whose id is tracked so _on_close can cancel it."""
        holder: list[str] = []

        def run() -> None:
            if holder:
                self._afters.discard(holder[0])
            if not self._closing:
                fn()

        tid = self.after(ms, run)
        holder.append(tid)
        self._afters.add(tid)
        return tid

    def _post(self, token: int, kind: str, *payload) -> None:
        """Called from worker threads: queue a message for the Tk thread."""
        self._q.put((token, kind, payload))

    def _pump(self) -> None:
        if self._closing:
            return
        try:
            while True:
                token, kind, payload = self._q.get_nowait()
                if token == self._token:
                    self._dispatch(kind, payload)
        except queue.Empty:
            pass
        self._after(PUMP_MS, self._pump)

    def _start_worker(self, target, *args) -> None:
        self._cancel = proc.Cancel()
        self._worker = threading.Thread(target=target, args=(self._token, self._cancel, *args),
                                        daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ layout
    def _fonts(self) -> None:
        base = tkfont.nametofont("TkDefaultFont").actual()
        fam, size = base["family"], abs(int(base["size"]))
        self.f_title = tkfont.Font(family=fam, size=size + 5, weight="bold")
        self.f_head = tkfont.Font(family=fam, size=size - 1, weight="bold")
        self.f_small = tkfont.Font(family=fam, size=size - 1)
        self.f_save = tkfont.Font(family=fam, size=size + 3, weight="bold")
        self.f_err = tkfont.Font(family=fam, size=size + 1, weight="bold")

    def _section(self, parent, row: int, text: str, note: tk.StringVar | None = None) -> ttk.Frame:
        head = ttk.Frame(parent)
        head.grid(row=row, column=0, sticky="ew", pady=(14, 4))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text=text.upper(), font=self.f_head, fg=MUTED).grid(row=0, column=0, sticky="w")
        if note is not None:
            tk.Label(head, textvariable=note, font=self.f_small, fg=MUTED).grid(row=0, column=1, sticky="e")
        return head

    def _values_row(self, parent, row: int, left: str, left_var: tk.StringVar,
                    middle: tk.StringVar | str, right: str, right_var: tk.StringVar) -> None:
        """'Start [4.5 s]     Trimmed length 5:34.5     End [339.0 s]'"""
        f = ttk.Frame(parent)
        f.grid(row=row, column=0, sticky="ew", pady=(6, 0))
        f.columnconfigure(2, weight=1)
        tk.Label(f, text=left).grid(row=0, column=0, sticky="w")
        tk.Label(f, textvariable=left_var, bg=PILL_BG, width=9, padx=6, pady=2).grid(
            row=0, column=1, sticky="w", padx=(8, 0))
        mid = (tk.Label(f, textvariable=middle, fg=MUTED) if isinstance(middle, tk.StringVar)
               else tk.Label(f, text=middle, fg=MUTED))
        mid.grid(row=0, column=2)
        tk.Label(f, text=right).grid(row=0, column=3, sticky="e")
        tk.Label(f, textvariable=right_var, bg=PILL_BG, width=9, padx=6, pady=2).grid(
            row=0, column=4, sticky="e", padx=(8, 0))

    def _build(self) -> None:
        root = ttk.Frame(self, padding=(20, 16, 20, 16))
        root.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        # URL + Fetch (F1)
        top = ttk.Frame(root)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10), ipady=3)
        self.url_entry.bind("<Return>", lambda _e: self.fetch())
        self.url_entry.bind("<KP_Enter>", lambda _e: self.fetch())
        self.fetch_btn = Button(top, "Fetch", PURPLE, self.fetch)
        self.fetch_btn.grid(row=0, column=1)
        self.url_entry.bind("<Key>", lambda _e: self._clear_fetch_error(), add="+")
        # Fetch problems show right under the link, where you're looking (F1, F11)
        self.fetch_error = tk.Frame(top, bg="#fbeef4", highlightthickness=1,
                                    highlightbackground="#efc3d7")
        self.fetch_error.columnconfigure(0, weight=1)
        self.fetch_error_label = tk.Label(self.fetch_error, textvariable=self.fetch_error_var,
                                          fg=WARN, bg="#fbeef4", font=self.f_err, anchor="w",
                                          justify="left", wraplength=560)
        self.fetch_error_label.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 8))
        self.fetch_details_link = tk.Label(self.fetch_error, text="Details ▸", fg=PURPLE,
                                           bg="#fbeef4", cursor=HAND)
        self.fetch_details_link.bind("<Button-1>", lambda _e: self.toggle_details())

        # Info card: thumbnail, song title + pencil (F15), channel · duration, Key (F7)
        card = tk.Frame(root, bg=CARD_BG, highlightthickness=1, highlightbackground=CARD_EDGE)
        card.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        card.columnconfigure(1, weight=1)
        card.bind("<Configure>", lambda e: self.title_label.configure(
            wraplength=max(240, e.width - THUMB_W - 110)))
        self.thumb = tk.Label(card, bg="#4b3a6b", fg="white", text="♪", font=self.f_title,
                              width=THUMB_W, height=THUMB_H, compound="center",
                              image=self._blank_image())
        self.thumb.grid(row=0, column=0, rowspan=3, padx=14, pady=(14, 8), sticky="nw")

        tk.Label(card, text="SONG TITLE · from YouTube, editable", font=self.f_small,
                 fg=MUTED, bg=CARD_BG).grid(row=0, column=1, sticky="sw", pady=(14, 0))
        trow = tk.Frame(card, bg=CARD_BG)
        trow.grid(row=1, column=1, sticky="ew", padx=(0, 14))
        trow.columnconfigure(0, weight=1)
        self.title_label = tk.Label(trow, textvariable=self.title_var, font=self.f_title,
                                    bg=CARD_BG, anchor="w", justify="left", wraplength=380)
        self.title_label.grid(row=0, column=0, sticky="w")
        self.pencil = PencilButton(trow, PURPLE, self.edit_title, size=30)
        self.pencil.grid(row=0, column=1, sticky="nw", padx=(8, 0), pady=(2, 0))
        tk.Label(card, textvariable=self.meta_var, fg=MUTED, bg=CARD_BG).grid(
            row=2, column=1, sticky="w")

        # Key and Transpose: one row centred across the bottom of the card. Every
        # piece has a fixed width, so changing the shift never resizes the window.
        krow = tk.Frame(card, bg=CARD_BG)
        krow.grid(row=3, column=0, columnspan=2, pady=(4, 14))
        tk.Label(krow, text="♫ Key", font=self.f_head, bg=CARD_BG).grid(row=0, column=0, padx=(0, 8))
        self.key_box = ttk.Combobox(krow, textvariable=self.key_var,
                                    values=[KEY_NONE, *keys.SHORT],
                                    state="disabled", width=5, height=25)
        self.key_box.grid(row=0, column=1)
        self.key_box.bind("<<ComboboxSelected>>", lambda _e: self._key_changed())
        # Transpose (F17): − shift + and the key you'll hear
        tk.Label(krow, text="Transpose", font=self.f_head, bg=CARD_BG).grid(
            row=0, column=2, padx=(18, 8))
        self.shift_down = Button(krow, "−", PURPLE, lambda: self.transpose_by(-1))
        self.shift_up = Button(krow, "+", PURPLE, lambda: self.transpose_by(1))
        for btn in (self.shift_down, self.shift_up):
            btn.configure(padx=9, pady=1)
        self.shift_down.grid(row=0, column=3)
        tk.Label(krow, textvariable=self.shift_var, font=self.f_head, bg=CARD_BG,
                 width=3).grid(row=0, column=4)
        self.shift_up.grid(row=0, column=5)
        # wide enough for the longest key you can hear ("→ C♯m")
        tk.Label(krow, textvariable=self.heard_var, font=self.f_head, bg=CARD_BG,
                 fg=PURPLE, width=6, anchor="w").grid(row=0, column=6, padx=(8, 0))
        # Speed (F18): a number box with arrows, after a gap
        tk.Label(krow, text="Speed", font=self.f_head, bg=CARD_BG).grid(
            row=0, column=7, padx=(20, 8))
        self.speed_box = ttk.Spinbox(krow, textvariable=self.speed_var, width=4,
                                     from_=transpose.MIN_SPEED, to=transpose.MAX_SPEED,
                                     increment=transpose.SPEED_STEP, wrap=False,
                                     command=self._speed_arrow, state="disabled")
        self.speed_box.grid(row=0, column=8)
        self.speed_box.bind("<Return>", self._speed_return)
        self.speed_box.bind("<KP_Enter>", self._speed_return)
        self.speed_box.bind("<FocusOut>", self._speed_typed, add="+")
        tk.Label(krow, text="%", bg=CARD_BG).grid(row=0, column=9, padx=(4, 0))

        # Trim (F4): the whole track
        self._section(root, 2, "Trim", self.trim_note)
        tbox = ttk.Frame(root)
        tbox.grid(row=3, column=0, sticky="ew")
        tbox.columnconfigure(0, weight=1)
        self.trim_slider = RangeSlider(tbox, style="trim", height=56, min_gap=trim.MIN_LENGTH,
                                       on_change=self._trim_changed, on_seek=self._seek_trim)
        self.trim_slider.grid(row=0, column=0, sticky="ew")
        self._values_row(tbox, 1, "Start", self.start_var, self.length_var, "End", self.end_var)

        # Fade (F6): only the trimmed range; handles move in from the ends
        self._section(root, 4, "Fade", self.fade_note)
        fbox = ttk.Frame(root)
        fbox.grid(row=5, column=0, sticky="ew")
        fbox.columnconfigure(0, weight=1)
        self.fade_slider = RangeSlider(fbox, style="fade", height=64, min_gap=0.0,
                                       on_change=self._fade_changed, on_seek=self._seek_fade)
        self.fade_slider.grid(row=0, column=0, sticky="ew")
        self._values_row(fbox, 1, "Fade in", self.fade_in_var,
                         "Handles at the ends = no fade (default)", "Fade out", self.fade_out_var)

        # Preview (F5)
        self._section(root, 6, "Preview", self.cursor_note)
        prow = ttk.Frame(root)
        prow.grid(row=7, column=0, sticky="ew")
        prow.columnconfigure(0, weight=1, uniform="p")
        prow.columnconfigure(2, weight=1, uniform="p")
        self.preview_btns = {
            "from_start": Button(prow, "⏮  From start", DARK, self.preview_from_start),
            "from_end": Button(prow, "From end  ⏭", DARK, self.preview_from_end),
        }
        self.preview_btns["from_start"].grid(row=0, column=0, sticky="ew")
        self.play_btn = RoundButton(prow, PURPLE, self.toggle_play, size=58)
        self.play_btn.grid(row=0, column=1, padx=18)
        self.preview_btns["from_end"].grid(row=0, column=2, sticky="ew")

        # Save (F8–F10) + progress, status, Cancel, error Details (F11)
        ttk.Separator(root).grid(row=8, column=0, sticky="ew", pady=(18, 0))
        self._section(root, 9, "Save")
        self.save_btn = Button(root, "Save MP3…", PURPLE, self.save, big=True)
        self.save_btn.configure(font=self.f_save, pady=12)
        self.save_btn.grid(row=10, column=0, sticky="ew")

        # The bar shows only while downloading or saving; its slot keeps the
        # same height when it's hidden, so nothing below jumps.
        self.progress_slot = ttk.Frame(root)
        self.progress_slot.grid(row=11, column=0, sticky="ew", pady=(12, 4))
        self.progress = ttk.Progressbar(self.progress_slot, mode="determinate", maximum=1.0)
        self.progress_slot.configure(height=self.progress.winfo_reqheight())
        self.progress_slot.pack_propagate(False)
        srow = ttk.Frame(root)
        srow.grid(row=12, column=0, sticky="ew")
        srow.columnconfigure(0, weight=1)
        self.status_label = tk.Label(srow, textvariable=self.status_var, anchor="w",
                                     justify="left", wraplength=520)
        self.status_label.grid(row=0, column=0, sticky="w")
        self._status_fg = self.status_label.cget("fg")
        self.details_link = tk.Label(srow, text="Details ▸", fg=PURPLE, cursor=HAND)
        self.details_link.bind("<Button-1>", lambda _e: self.toggle_details())
        self.cancel_btn = Button(srow, "Cancel", DARK, self.cancel)
        self.reveal_link = tk.Label(srow, text="Reveal in Finder", fg=PURPLE, font=self.f_head,
                                    cursor=HAND)
        self.reveal_link.bind("<Button-1>", lambda _e: self.reveal())

        self.details_box = tk.Text(root, height=9, wrap="word", font="TkFixedFont",
                                   relief="flat", bg="#f4f4f6", padx=8, pady=6)
        self.fetch_details_box = tk.Text(self.fetch_error, height=7, wrap="word",
                                         font="TkFixedFont", relief="flat", bg="#f7f4f7",
                                         padx=8, pady=6)
        self.details_shown = False

    def _blank_image(self) -> tk.PhotoImage:
        # A Label with an image sizes in pixels, so the placeholder matches the thumbnail.
        self._blank = tk.PhotoImage(width=THUMB_W, height=THUMB_H)
        return self._blank

    # ------------------------------------------------------------ state
    def _set_state(self, state: str) -> None:
        self.state = state
        busy = state in BUSY
        self.fetch_btn.set_enabled(not busy)
        self.url_entry.configure(state="disabled" if busy else "normal")
        has_info = self.info is not None and state not in (IDLE, FETCHING, CANCELLED)
        self.key_box.configure(state="readonly" if has_info and state != SAVING else "disabled")
        self.pencil.set_enabled(has_info and state != SAVING)
        if busy:
            self.cancel_btn.grid(row=0, column=2, sticky="e", padx=(12, 0))
        else:
            self.cancel_btn.grid_remove()
        if state == SAVED and self.saved_path is not None:
            self.reveal_link.grid(row=0, column=2, sticky="e")
        else:
            self.reveal_link.grid_remove()
        if state != ERROR:
            self._hide_details()
        if state in BUSY:
            self.pause()
        self._update_bar()
        self._refresh_save()
        self._refresh_editing()

    def _update_bar(self) -> None:
        """The bar shows while fetching, downloading, saving or preparing a preview."""
        if self.state in BUSY or self.preparing:
            if not self.progress.winfo_ismapped():
                self.progress.pack(fill="x", expand=True)
        else:
            self.progress.pack_forget()

    def _step(self, fraction: float, message: str) -> None:
        self.progress.configure(value=fraction)
        self.status_var.set(message)

    def _key(self) -> str | None:
        """The original key, in words (the dropdown shows short names)."""
        text = self.key_var.get()
        return keys.from_short(text) or keys.lookup(text)

    def save_blocker(self) -> str:
        """Why Save is disabled, or '' when it's enabled."""
        if self.state in (FETCHING, DOWNLOADING):
            return "downloading…"
        if self.state == SAVING:
            return "saving…"
        if self.state == PREPARING:
            return "preparing audio…"
        if self.audio is None or self.info is None:
            return "fetch a video first"
        return ""

    def _refresh_save(self) -> None:
        why = self.save_blocker()
        self.save_btn.set_enabled(not why)
        self.save_btn.configure(text="Save MP3…" + (f"   · {why}" if why else ""))

    def _say(self, text: str) -> None:
        """Set the status line. While a preview is being prepared, it's also
        what comes back when the preview is ready."""
        self.status_var.set(text)
        if self._prep_status_saved:
            self._status_before_preview = text

    def _key_changed(self) -> None:
        self.key_box.selection_clear()
        self._show_shift()
        shown = self._status_before_preview if self._prep_status_saved else self.status_var.get()
        if shown.startswith("Transposed "):          # it names the key you hear
            self._say(self._setting_status())
        self._refresh_save()

    def set_title(self, text: str) -> None:
        self.title_var.set(text)

    def _reset_for_new_url(self) -> None:
        self.info = None
        self.audio = None
        self.title_var.set("")
        self.meta_var.set("")
        self.key_var.set(KEY_NONE)
        self._stop_transpose()
        self.shift = self.shift_wanted = 0
        self.speed = self.speed_wanted = 100
        self._show_shift()
        self._thumb_img = None
        self.thumb.configure(image=self._blank, text="♪")
        self.progress.configure(value=0)
        self._drop_preview()
        self.spec = None
        self.cursor = 0.0
        self._sync_sliders()

    # ------------------------------------------------------------ actions
    def fetch(self) -> None:
        if self.state in BUSY:
            return
        text = self.url_var.get()
        if not text.strip():
            self.status_var.set("Paste a YouTube link first.")
            return
        self._clear_fetch_error()
        try:
            url = fetch.check_url(text)     # instant: playlists, other sites, not a link
        except fetch.FetchError as e:
            self._show_error(e.message, where="fetch")
            return
        self.tools = tools.locate()
        if not self.tools.ok:
            self._show_error(self.tools.problem(), where="fetch")
            self.show_prereq_dialog()
            return
        self._token += 1
        self._reset_for_new_url()
        self.source_url = url
        self._set_state(FETCHING)
        self._step(STEP_LOOKUP, "Looking up the video…")
        self._start_worker(self._fetch_worker, url, self.tools)

    def edit_title(self) -> None:
        if self.info is None or self.title_sheet is not None or self.state == SAVING:
            return
        self.title_sheet = TitleSheet(self)

    def save(self) -> None:
        if self.save_blocker():
            return
        assert self.info is not None and self.audio is not None
        if not self._ensure_source(self.save):
            return
        key = self._key()
        folder = self.cfg.get("last_save_folder") or str(Path.home() / "Music")
        path = self._ask_save_path(folder if Path(folder).is_dir() else str(Path.home()),
                                   naming.filename(self.title_var.get(), key, self.shift,
                                                   self.speed))
        if not path:
            # Save dialog cancelled: replace any earlier "Saved …" message.
            self.status_var.set("Not saved.")
            settings.log("save dialog cancelled")
            return
        out = Path(path)
        if out.suffix.lower() != ".mp3":
            out = out.with_name(out.name + ".mp3")
        problem = render.check_writable(out.parent)
        if problem:
            self._show_error(problem)
            return
        spec = self.spec or TrimSpec().clamped(self.info.duration)
        self._saving_part = render.part_path(out)
        self._set_state(SAVING)
        self._step(0.0, "Saving…")
        self._start_worker(self._save_worker, self.tools["ffmpeg"], self._source(),
                           spec.scaled(self._k()), out)

    def _ask_save_path(self, folder: str, name: str) -> str:
        """The native Save dialog as its own window, not a sheet. Given the
        main window as parent, Tk 9 on macOS attaches the panel as a sheet,
        which starts cut off and only lays itself out properly once
        clicked; a hidden parent gets a normal, fully laid-out app-modal
        panel. No filetypes: the Format popup they add has nothing to offer
        when MP3 is the only choice."""
        holder = tk.Toplevel(self)
        holder.withdraw()
        try:
            return filedialog.asksaveasfilename(
                parent=holder, title="Save MP3", initialdir=folder,
                initialfile=name, defaultextension=".mp3")
        finally:
            holder.destroy()

    def cancel(self) -> None:
        if self.state == PREPARING:
            self._cancel_transpose()
            return
        if self.state in BUSY and self._cancel is not None:
            self._cancel.set()
            self.status_var.set("Cancelling…")

    def reveal(self) -> None:
        """F13: show the saved file in Finder."""
        if self.saved_path is not None and self.saved_path.exists():
            subprocess.Popen(["open", "-R", str(self.saved_path)])

    def _ensure_audio(self, then) -> bool:
        """True if the downloaded audio is still on disk. If macOS (or
        someone) removed it from the cache, download it again and run
        *then* when that's done."""
        if self.audio is not None and self.audio.exists():
            return True
        if self.info is None or self.state in BUSY:
            return False
        self._pending = then
        self._redownloading = True
        self.audio = None
        self._set_state(DOWNLOADING)
        self._step(STEP_DOWNLOAD[0], "The download was removed from the cache; downloading it again…")
        self._start_worker(self._redownload_worker, self.info, self.source_url or self.info.url,
                           self.tools)
        return False

    def _ensure_source(self, then) -> bool:
        """True if the audio to render from is on disk: the download, or its
        processed copy. A missing copy is made again, then *then* runs."""
        if not self._ensure_audio(then):
            return False
        if transpose.is_plain(self.shift, self.speed) or self._copy_path(self.shift, self.speed).exists():
            return True
        n, s = self.shift, self.speed
        self.shift, self.speed = 0, 100        # only the download is left
        self._pending = then
        self._want(n, s, delay=0)
        return False

    # ------------------------------------------------------------ transpose (F17) and speed (F18)
    def _source(self) -> Path:
        """The audio previews and saves render from."""
        assert self.audio is not None
        if transpose.is_plain(self.shift, self.speed):
            return self.audio
        return self._copy_path(self.shift, self.speed)

    def _copy_path(self, n: int, s: int) -> Path:
        assert self.info is not None
        return cache.processed_audio(self.info.id, n, s)

    def _k(self) -> float:
        """How many times longer the source is than the song: song time × k
        is the same moment in the processed copy."""
        return 100 / self.speed

    def _can_transpose(self) -> bool:
        return (self.audio is not None and self.info is not None
                and self.state not in (IDLE, FETCHING, DOWNLOADING, SAVING, CANCELLED))

    def _show_shift(self) -> None:
        """'+2' in the control and '→ C' beside it when a key is picked; the
        speed box; the trimmed length at that speed."""
        n = self.shift_wanted
        self.shift_var.set(keys.shift_label(n))
        key = self._key()
        self.heard_var.set(f"→ {keys.short_name(keys.effective_key(key, n))}" if key and n else "")
        if self.focus_get() is not self.speed_box:     # don't fight someone typing
            self.speed_var.set(str(self.speed_wanted))
        self._show_length()
        self._refresh_editing()

    def _setting_status(self) -> str:
        n, s = self.shift, self.speed
        parts = []
        if n:
            key = self._key()
            heard = f" → {keys.short_name(keys.effective_key(key, n))}" if key else ""
            parts.append(f"Transposed {keys.shift_label(n)}{heard}")
        if s != 100:
            parts.append(f"at {s}%" if parts else f"Speed set to {s}%")
        return (", ".join(parts) + ".") if parts else "Back in the original key and speed."

    def _setting_label(self) -> str:
        """The current shift and speed in a few characters: "+1", "75%", "+1 at 75%"."""
        parts = [keys.shift_label(self.shift)] if self.shift else []
        if self.speed != 100:
            parts.append(f"{self.speed}%")
        return " at ".join(parts)

    def transpose_by(self, step: int) -> None:
        """The − / + buttons and keys."""
        if not self._can_transpose():
            return
        n = max(-keys.MAX_SHIFT, min(keys.MAX_SHIFT, self.shift_wanted + step))
        if n != self.shift_wanted:
            self._want(n, self.speed_wanted)

    def reset_shift(self) -> None:
        """The 0 key: back to the original key."""
        if self._can_transpose() and self.shift_wanted != 0:
            self._want(0, self.speed_wanted)

    def speed_by(self, step: int) -> None:
        """The ] and [ keys: SPEED_STEP faster or slower."""
        if self._can_transpose():
            self._set_speed(self.speed_wanted + step)

    def reset_speed(self) -> None:
        """The \\ key: back to 100%."""
        if self._can_transpose():
            self._set_speed(100)

    def _set_speed(self, value: int, delay: int | None = None) -> None:
        s = transpose.clamp_speed(value)
        self.speed_var.set(str(s))
        if s != self.speed_wanted:
            self._want(self.shift_wanted, s, delay=delay)

    def _speed_arrow(self) -> None:
        """The speed box's up/down arrows (the box already shows the new value)."""
        if not self._can_transpose():
            return
        try:
            value = int(self.speed_var.get())
        except ValueError:
            value = self.speed_wanted
        self._set_speed(value)

    def _speed_typed(self, _e=None) -> str | None:
        """Return or leaving the box: apply a typed whole number, clamped to
        the range; anything else goes back to the last value."""
        text = self.speed_var.get().strip().rstrip("%").strip()
        try:
            value = int(text)
        except ValueError:
            self.speed_var.set(str(self.speed_wanted))
            return None
        if self._can_transpose():
            self._set_speed(value, delay=0)
        else:
            self.speed_var.set(str(self.speed_wanted))
        return None

    def _speed_return(self, e) -> str:
        self._speed_typed(e)
        self.focus_set()                 # out of the box, so Space and the keys work again
        return "break"

    def _want_shift(self, n: int, delay: int | None = None) -> None:
        self._want(n, self.speed_wanted, delay)

    def _want(self, n: int, s: int, delay: int | None = None) -> None:
        """Show shift *n* and speed *s* at once; make their audio once the
        controls have been still for *delay* ms. A preparation already
        running is cancelled. A setting that needs no work (0 / 100%, or the
        copy already made) applies straight away."""
        self.pause()                    # while the cursor still maps through the old speed
        self.shift_wanted, self.speed_wanted = n, s
        self._show_shift()
        self._stop_transpose()
        if transpose.is_plain(n, s) or self._copy_path(n, s).exists():
            changed = (n, s) != (self.shift, self.speed) or self.state == PREPARING
            self.shift, self.speed = n, s
            if changed:
                self.progress.configure(value=0)
                self._say(self._setting_status())
                self._set_state(READY)
                self._sync_sliders()
                self._schedule_preview()
            if self._pending is not None:
                action, self._pending = self._pending, None
                self._after(0, action)
            return
        self._drop_preview()
        if self.state != PREPARING:
            self._set_state(PREPARING)
        self._step(0.0, f"{transpose.progress_label(n, s)}…")
        self._transpose_after = self._after(TRANSPOSE_DEBOUNCE_MS if delay is None else delay,
                                            self._start_transpose)

    def _stop_transpose(self) -> None:
        """Forget a pending or running preparation (its messages go stale)."""
        self._transpose_token += 1
        if self._transpose_after is not None:
            try:
                self.after_cancel(self._transpose_after)
            except tk.TclError:
                pass
            self._afters.discard(self._transpose_after)
            self._transpose_after = None
        if self.state == PREPARING and self._cancel is not None:
            self._cancel.set()

    def _start_transpose(self) -> None:
        self._transpose_after = None
        if self.state != PREPARING or self.info is None or self.audio is None:
            return
        n, s = self.shift_wanted, self.speed_wanted
        self._transpose_token += 1
        self._start_worker(self._transpose_worker, self._transpose_token, self.tools["ffmpeg"],
                           self.tools["rubberband"], self.audio, n, s, self._copy_path(n, s),
                           self.info.duration)

    def _cancel_transpose(self) -> None:
        """Cancel: back to the shift and speed the audio already has."""
        self._stop_transpose()
        self._pending = None
        self.shift_wanted, self.speed_wanted = self.shift, self.speed
        self.speed_var.set(str(self.speed))
        self._show_shift()
        self.progress.configure(value=0)
        still = self._setting_label()
        self._say("Cancelled." + (f" Still {still}." if still else ""))
        settings.log("cancelled while preparing audio")
        self._set_state(READY)
        self._schedule_preview(delay=0)

    # ------------------------------------------------------------ trim, fades, cursor (M3)
    def _can_edit(self) -> bool:
        """Sliders work once the audio is downloaded and nothing is busy."""
        return self.audio is not None and self.spec is not None and self.state not in BUSY

    def _can_play(self) -> bool:
        """The play buttons wait for the background preview to be ready."""
        return self._can_edit() and self.preview_clip is not None and not self.preparing

    def _refresh_editing(self) -> None:
        on = self._can_edit()
        self.trim_slider.set_enabled(on)
        self.fade_slider.set_enabled(on)
        play = self._can_play()
        for btn in self.preview_btns.values():
            btn.set_enabled(play)
        self.play_btn.set_enabled(play)
        self.play_btn.set_symbol("pause" if self.player.playing else "play")
        can = self._can_transpose()
        self.shift_down.set_enabled(can and self.shift_wanted > -keys.MAX_SHIFT)
        self.shift_up.set_enabled(can and self.shift_wanted < keys.MAX_SHIFT)
        self.speed_box.configure(state="normal" if can else "disabled")

    def _sync_sliders(self) -> None:
        """Push self.spec and self.cursor into both sliders and all the labels."""
        fmt = timecode.format_seconds
        spec = self.spec
        if spec is None:
            for sl in (self.trim_slider, self.fade_slider):
                sl.set_range(0, 1)
                sl.set_values(0, 1)
                sl.set_cursor(None)
            for v in (self.start_var, self.end_var, self.fade_in_var, self.fade_out_var):
                v.set("—")
            for v in (self.length_var, self.trim_note, self.fade_note, self.cursor_note):
                v.set("")
            self._refresh_editing()
            return
        duration = self.info.duration if self.info else spec.end
        self.trim_slider.set_range(0, duration)
        self.trim_slider.set_values(spec.start, spec.end)
        self.fade_slider.set_range(0, spec.length)
        self.fade_slider.set_values(spec.fade_in, spec.length - spec.fade_out)
        self.start_var.set(fmt(spec.start))
        self.end_var.set(fmt(spec.end))
        self._show_length()
        self.fade_in_var.set(fmt(spec.fade_in))
        self.fade_out_var.set(fmt(spec.fade_out))
        self.trim_note.set(f"whole track 0:00 – {fmt(duration)}")
        self.fade_note.set(f"trimmed range 0:00 – {fmt(spec.length)}")
        self._show_cursor()
        self._refresh_editing()

    def _show_length(self) -> None:
        """'Trimmed length 5:34.5', plus the saved length when the speed isn't 100%."""
        spec = self.spec
        if spec is None:
            return
        fmt = timecode.format_seconds
        text = f"Trimmed length {fmt(spec.length)}"
        s = self.speed_wanted
        if s != 100:
            text += f" · {fmt(spec.length * 100 / s)} at {s}%"
        self.length_var.set(text)

    def _show_cursor(self) -> None:
        spec = self.spec
        if spec is None:
            return
        self.trim_slider.set_cursor(self.cursor)
        self.fade_slider.set_cursor(self.cursor - spec.start)
        into = max(0.0, self.cursor - spec.start)
        self.cursor_note.set(f"cursor {timecode.format_seconds(self.cursor)} "
                             f"({timecode.format_seconds(into)} into trim)")

    def _set_spec(self, spec: TrimSpec) -> None:
        assert self.info is not None
        self.spec = spec.clamped(self.info.duration)
        self.cursor = min(max(self.cursor, self.spec.start), self.spec.end)
        self._sync_sliders()

    def _trim_changed(self, start: float, end: float, final: bool) -> None:
        if self.spec is None:
            return
        self._set_spec(TrimSpec(start, end, self.spec.fade_in, self.spec.fade_out))
        self._schedule_preview()        # stops playback; the old preview no longer matches

    def _fade_changed(self, a: float, b: float, final: bool) -> None:
        if self.spec is None:
            return
        s = self.spec
        self._set_spec(TrimSpec(s.start, s.end, a, s.length - b))
        self._schedule_preview()

    def _seek_trim(self, t: float) -> None:
        self._seek(t)

    def _seek_fade(self, t: float) -> None:
        if self.spec is not None:
            self._seek(self.spec.start + t)

    def _seek(self, t: float) -> None:
        """A click on either slider's track moves the cursor there; if a
        preview is playing it carries on from the new spot."""
        if self.spec is None:
            return
        was_playing = self.player.playing
        self.cursor = min(max(t, self.spec.start), self.spec.end)
        self._show_cursor()
        if was_playing:
            self._play_from_cursor()

    # -- the background preview (F5): one WAV of the whole trimmed range
    def _schedule_preview(self, delay: int = PREVIEW_DEBOUNCE_MS) -> None:
        """Throw away the current preview and make a new one for self.spec.
        A render already running is killed; while a slider is being dragged
        the new render waits until it has stopped moving for *delay* ms."""
        self._drop_preview()
        if not self._can_edit():
            return
        self.preparing = True
        if not self._prep_status_saved:
            self._status_before_preview = self.status_var.get()
            self._prep_status_saved = True
        self._update_bar()
        self._step(0.0, "Preparing preview…")
        self._refresh_editing()
        self._prep_after = self._after(delay, self._start_preview_render)

    def _drop_preview(self) -> None:
        """Pause playback, kill a render in progress, delete the old preview."""
        self.pause()
        self._preview_token += 1
        if self._preview_cancel is not None:
            self._preview_cancel.set()
            self._preview_cancel = None
        if self._prep_after is not None:
            try:
                self.after_cancel(self._prep_after)
            except tk.TclError:
                pass
            self._afters.discard(self._prep_after)
            self._prep_after = None
        if self.preview_clip is not None:
            self.preview_clip.unlink(missing_ok=True)
            self.preview_clip = None
        if self.preparing:
            self.preparing = False
            self._update_bar()

    def _finish_preparing(self) -> None:
        self.preparing = False
        if self._prep_status_saved:
            if self.state not in BUSY:          # don't overwrite "Saving… 40%"
                self.status_var.set(self._status_before_preview)
            self._prep_status_saved = False
        self._update_bar()
        self._refresh_editing()

    def _start_preview_render(self) -> None:
        self._prep_after = None
        if not self.preparing or self.spec is None:
            return
        if not self._ensure_source(self._schedule_preview):
            return
        self._preview_token += 1
        self._preview_cancel = proc.Cancel()
        clip = self._tmp / f"preview-{self._preview_token}.wav"
        threading.Thread(target=self._preview_worker, daemon=True,
                         args=(self._token, self._preview_token, self._preview_cancel,
                               self.tools["ffmpeg"], self._source(), self.spec.scaled(self._k()),
                               clip)).start()

    def _preview_worker(self, token: int, ptoken: int, cancel: proc.Cancel, ffmpeg: str,
                        audio: Path, spec: TrimSpec, clip: Path) -> None:
        try:
            out = render.render_preview(
                ffmpeg, audio, spec, spec.start, clip, cancel=cancel,
                on_fraction=lambda f: self._post(token, "preview_progress", ptoken, f))
            if out is not None:
                self._post(token, "preview_ready", ptoken, out)
        except render.RenderError as e:
            self._post(token, "preview_error", ptoken, e.message, e.details)
        except Exception as e:
            self._post(token, "preview_error", ptoken, f"Preview failed: {e}", repr(e))

    # -- the play buttons (F5): From start · play/pause · From end
    def preview_from_start(self) -> None:
        if self._can_play():
            self.cursor = self.spec.start
            self._play_from_cursor()

    def toggle_play(self) -> None:
        """The round button and Space: play from the cursor, or pause."""
        if self.player.playing:
            self.pause()
        elif self._can_play():
            if self.cursor >= self.spec.end - 0.05:     # at the end: start over
                self.cursor = self.spec.start
            self._play_from_cursor()

    def preview_from_end(self) -> None:
        if self._can_play():
            k = self._k()                   # the last 10 s as you hear them
            self.cursor = trim.from_end_cursor(self.spec.scaled(k)) / k
            self._play_from_cursor()

    def pause(self) -> None:
        """Stop playback; the cursor stays where playback reached. The
        preview itself is kept, so playing again is instant."""
        pos = self.player.stop()
        if pos is not None and self.spec is not None:
            pos /= self._k()                # the player counts in the copy's time
            self.cursor = min(max(pos, self.spec.start), self.spec.end)
            self._show_cursor()
        self._refresh_editing()

    def _play_from_cursor(self) -> None:
        assert self.spec is not None and self.preview_clip is not None
        cursor = self.cursor
        self.pause()                    # would move the cursor to where the old clip had got to
        self.cursor = cursor
        # The preview and the player count in the processed copy's time; the
        # cursor is in the song's (× k = the same moment in the copy).
        k = self._k()
        copy = self.spec.scaled(k)
        at = copy.start + trim.preview_offset(copy, cursor * k)
        offset = at - copy.start
        if offset < 0.01:
            clip = self.preview_clip
        else:
            clip = slice_wav(self.preview_clip, self._tmp / "play.wav", offset)
        self.player.play(clip, at)
        self.cursor = at / k
        self._show_cursor()
        self._refresh_editing()
        self._start_ticking()

    def _start_ticking(self) -> None:
        if not self._ticking:
            self._ticking = True
            self._after(TICK_MS, self._tick)

    def _tick(self) -> None:
        """Advance the cursor while a clip plays; at the clip's end the
        cursor rests at the trim end."""
        if self.player.playing and self.spec is not None:
            self.cursor = min(self.player.position() / self._k(), self.spec.end)
            self._show_cursor()
            self._after(TICK_MS, self._tick)
            return
        self._ticking = False
        if self.player.finished and self.spec is not None:
            self.player.reset()
            self.cursor = self.spec.end
            self._show_cursor()
            self._refresh_editing()

    # ------------------------------------------------------------ workers (no widgets here)
    def _fetch_worker(self, token: int, cancel: proc.Cancel, url: str, found: tools.Toolset) -> None:
        ytdlp = found["yt-dlp"]
        try:
            info = fetch.fetch_info(ytdlp, url, cancel=cancel)
            if info is None:
                return self._post(token, "cancelled", FETCHING)
            self._post(token, "info", info)
            settings.log(f"fetched {info.id} {info.title!r} ({info.duration:.1f} s)")

            audio = cache.find_audio(info.id)
            if audio is None:
                info_json = fetch.save_info(info, cache.info_path(info.id))
                self._post(token, "step", STEP_THUMB, "Getting the thumbnail…")
                thumb = fetch.fetch_thumbnail(ytdlp, info_json, cache.thumb_stem(info.id), cancel=cancel)
                if thumb is not None:
                    self._post(token, "thumb", thumb)
                if cancel.is_set:
                    return self._post(token, "cancelled", DOWNLOADING)
                audio = self._download(token, cancel, ytdlp, info.id, info_json)
                if audio is None:
                    return self._post(token, "cancelled", DOWNLOADING)
                settings.log(f"downloaded {info.id} → {audio.name}")
            else:
                self._post(token, "step", STEP_DOWNLOAD[1], "Found it in the download cache…")
                thumb = cache.thumb_stem(info.id).with_suffix(".png")
                if thumb.exists():
                    self._post(token, "thumb", thumb)
            self._post(token, "step", STEP_FINISH, "Finishing…")
            cache.prune(protect=info.id)
            self._post(token, "downloaded", audio)
        except (fetch.FetchError, download.DownloadError) as e:
            self._post(token, "error", e.message, e.details, "fetch")
        except Exception as e:  # never leave the UI stuck in a busy state
            self._post(token, "error", f"Something went wrong: {e}", repr(e), "fetch")

    def _download(self, token: int, cancel: proc.Cancel, ytdlp: str, video_id: str,
                  source) -> Path | None:
        lo, hi = STEP_DOWNLOAD
        self._post(token, "step", lo, "Downloading the audio…")

        def progress(p: download.Progress) -> None:
            if p.fraction is not None:
                self._post(token, "step", lo + (hi - lo) * p.fraction,
                           f"Downloading the audio… {int(p.fraction * 100)}%")

        return download.download(ytdlp, video_id, source, cancel=cancel, on_progress=progress)

    def _redownload_worker(self, token: int, cancel: proc.Cancel, info: fetch.VideoInfo,
                           url: str, found: tools.Toolset) -> None:
        try:
            audio = self._download(token, cancel, found["yt-dlp"], info.id, url)
            if audio is None:
                return self._post(token, "cancelled", DOWNLOADING)
            settings.log(f"downloaded again {info.id} → {audio.name}")
            self._post(token, "step", STEP_FINISH, "Finishing…")
            self._post(token, "downloaded", audio)
        except download.DownloadError as e:
            self._post(token, "error", e.message, e.details, "fetch")
        except Exception as e:
            self._post(token, "error", f"Something went wrong: {e}", repr(e), "fetch")

    def _transpose_worker(self, token: int, cancel: proc.Cancel, tt: int, ffmpeg: str,
                          rubberband: str, audio: Path, n: int, s: int, dest: Path,
                          duration: float) -> None:
        try:
            out = transpose.transpose(
                ffmpeg, rubberband, audio, n, dest, duration, cancel=cancel, tmp_dir=self._tmp,
                speed=s, on_fraction=lambda f: self._post(token, "transpose_progress", tt, n, s, f))
            if out is None:
                return self._post(token, "transpose_cancelled", tt)
            settings.log(f"prepared {audio.parent.name}: {n:+d}, {s}%")
            self._post(token, "transposed", tt, n, s)
        except transpose.TransposeError as e:
            self._post(token, "transpose_error", tt, e.message, e.details)
        except Exception as e:
            self._post(token, "transpose_error", tt, f"Preparing the audio failed: {e}", repr(e))

    def _save_worker(self, token: int, cancel: proc.Cancel, ffmpeg: str, audio: Path,
                     spec: TrimSpec, out: Path) -> None:
        try:
            saved = render.render_mp3(ffmpeg, audio, spec, out, cancel=cancel,
                                      on_fraction=lambda f: self._post(token, "progress", f))
            if saved is None:
                return self._post(token, "cancelled", SAVING)
            settings.log(f"saved {saved}")
            self._post(token, "saved", saved)
        except render.RenderError as e:
            self._post(token, "error", e.message, e.details, "bottom")
        except Exception as e:
            self._post(token, "error", f"Something went wrong: {e}", repr(e), "bottom")

    # ------------------------------------------------------------ messages (Tk thread)
    def _dispatch(self, kind: str, payload: tuple) -> None:
        if kind == "info":
            (info,) = payload
            self.info = info
            self.spec = TrimSpec().clamped(info.duration)
            self.cursor = self.spec.start
            self._sync_sliders()
            self.title_var.set(info.title)
            self.meta_var.set(" · ".join(x for x in (info.channel, timecode.format_seconds(info.duration)) if x))
            self._set_state(DOWNLOADING)     # the worker posts the next step
        elif kind == "thumb":
            (path,) = payload
            self._show_thumbnail(path)
        elif kind == "step":
            fraction, message = payload
            if self.state in BUSY:
                self._step(fraction, message)
        elif kind == "progress":                  # saving
            (fraction,) = payload
            if fraction is not None and self.state == SAVING:
                self._step(fraction, f"Saving… {int(fraction * 100)}%")
        elif kind == "preview_progress":
            ptoken, fraction = payload
            if ptoken == self._preview_token and self.preparing and self.state not in BUSY:
                self._step(fraction, f"Preparing preview… {int(fraction * 100)}%")
        elif kind == "downloaded":
            (audio,) = payload
            self.audio = audio
            self._redownloading = False
            self.progress.configure(value=1.0)
            self.status_var.set("Ready. Trim and preview, pick the key if you like, then save.")
            self._set_state(READY)
            self.focus_set()                # out of the link box, so Space plays
            if self._pending is not None:
                action, self._pending = self._pending, None
                self._after(0, action)
            elif self.preview_clip is None:
                self._schedule_preview(delay=0)
        elif kind == "saved":
            (path,) = payload
            self.cfg["last_save_folder"] = str(path.parent)
            settings.save(self.cfg)
            self._saving_part = None
            self.saved_path = path
            self.status_var.set(f"Saved “{path.name}” in {short_folder(path.parent)}.")
            self._set_state(SAVED)
        elif kind == "cancelled":
            (stage,) = payload
            self.progress.configure(value=0)
            settings.log(f"cancelled while {stage}")
            self._pending = None
            if stage == SAVING:
                self._saving_part = None
                self.status_var.set("Save cancelled. Nothing was written.")
                self._set_state(READY)
            elif self._redownloading:
                # a re-download was cancelled: keep the track, it just can't play or save yet
                self._redownloading = False
                self.status_var.set("Cancelled. Click Fetch to download the audio again.")
                self._set_state(CANCELLED)
            else:
                self._reset_for_new_url()
                self.status_var.set("Cancelled.")
                self._set_state(CANCELLED)
        elif kind == "transpose_progress":
            tt, n, s, fraction = payload
            if tt == self._transpose_token and self.state == PREPARING:
                self._step(fraction, f"{transpose.progress_label(n, s)}… {int(fraction * 100)}%")
        elif kind == "transposed":
            tt, n, s = payload
            if tt != self._transpose_token or self.state != PREPARING:
                return
            self.shift, self.speed = n, s
            self._want(n, s)             # the copy now exists: applies at once
        elif kind == "transpose_cancelled":
            (tt,) = payload
            if tt == self._transpose_token and self.state == PREPARING:
                self._cancel_transpose()
        elif kind == "transpose_error":
            tt, message, details = payload
            if tt != self._transpose_token or self.state != PREPARING:
                return
            self._pending = None
            # keep the shift and speed the audio has
            self.shift_wanted, self.speed_wanted = self.shift, self.speed
            self.speed_var.set(str(self.speed))
            self._show_shift()
            if details:
                settings.log("preparing error: " + message + "\n" + details)
            self._show_error(message, details)
            self._schedule_preview(delay=0)
        elif kind == "preview_ready":
            ptoken, clip = payload
            if ptoken != self._preview_token or not self.preparing:
                clip.unlink(missing_ok=True)
                return
            self._preview_cancel = None
            self.preview_clip = clip
            self._finish_preparing()
        elif kind == "preview_error":
            ptoken, message, details = payload
            if ptoken == self._preview_token:
                self._preview_cancel = None
                self._finish_preparing()
                if details:
                    settings.log("preview error: " + message + "\n" + details)
                self._show_error(message, details)
        elif kind == "error":
            message, details, where = payload
            self._redownloading = False
            self._pending = None
            if details:
                settings.log("error: " + message + "\n" + details)
            if self.audio is None:
                self._reset_for_new_url()
            self._show_error(message, details, where=where)

    def _show_thumbnail(self, path: Path) -> None:
        try:
            img = tk.PhotoImage(file=str(path))
        except tk.TclError:
            return
        factor = max(1, math.ceil(max(img.width() / THUMB_W, img.height() / THUMB_H)))
        if factor > 1:
            img = img.subsample(factor)
        self._thumb_img = img
        self.thumb.configure(image=img, text="")

    def _show_error(self, message: str, details: str = "", where: str = "bottom") -> None:
        """Fetch problems (bad link, lookup or download failures, missing
        tools) show in a band right under the link box; save and preview
        problems in the status line at the bottom. Both offer Details."""
        self.details = details
        self.error_where = where
        self.progress.configure(value=0)
        self._set_state(ERROR)
        if where == "fetch":
            self.fetch_error_var.set(message)
            self.status_var.set("")
            self.fetch_error.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
            if details:
                self.fetch_details_link.configure(text="Details ▸")
                self.fetch_details_link.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))
        else:
            self.status_var.set(message)
            self.status_label.configure(fg=WARN)
            if details:
                self.details_link.configure(text="Details ▸")
                self.details_link.grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _clear_fetch_error(self) -> None:
        if self.fetch_error.winfo_ismapped() or self.fetch_error_var.get():
            self.fetch_error_var.set("")
            self.fetch_error.grid_remove()
            self.fetch_details_link.grid_remove()
            self.fetch_details_box.grid_remove()

    def _hide_details(self) -> None:
        self.status_label.configure(fg=self._status_fg)
        self.details_link.grid_remove()
        self.details_box.grid_remove()
        self.details_shown = False

    def toggle_details(self) -> None:
        if not self.details:
            return
        self.details_shown = not self.details_shown
        fetch_area = getattr(self, "error_where", "bottom") == "fetch"
        box = self.fetch_details_box if fetch_area else self.details_box
        link = self.fetch_details_link if fetch_area else self.details_link
        if self.details_shown:
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", self.details)
            box.configure(state="disabled")
            if fetch_area:
                box.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
            else:
                box.grid(row=13, column=0, sticky="nsew", pady=(6, 0))
            link.configure(text="Details ▾")
        else:
            box.grid_remove()
            link.configure(text="Details ▸")

    # ------------------------------------------------------------ close
    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._cancel is not None:
            self._cancel.set()            # kills any running yt-dlp / ffmpeg
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=4)  # let it clean up its partial files
        if self._saving_part is not None:
            self._saving_part.unlink(missing_ok=True)
        if self._preview_cancel is not None:
            self._preview_cancel.set()
        self.player.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)
        for tid in list(self._afters):
            try:
                self.after_cancel(tid)
            except tk.TclError:
                pass
        self._afters.clear()
        for dialog in (self.title_sheet, self.prereq_dialog):
            if dialog is not None:
                try:
                    dialog.close()
                except tk.TclError:
                    pass
        # Flush pending idle redraws and focus changes now: Tcl's idle queue is
        # per thread, so ones left behind would run against destroyed windows.
        try:
            self.update_idletasks()
        except tk.TclError:
            pass
        try:
            self.quit()
        finally:
            self.destroy()


def main() -> None:
    if "--self-test" in sys.argv[1:]:
        from karaokegrab import selftest
        args = [a for a in sys.argv[1:] if a != "--self-test"]
        sys.exit(selftest.run(*args[:1]))
    App().mainloop()


if __name__ == "__main__":
    main()
