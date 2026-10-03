#!/usr/bin/env python3
"""Karaoke Grabber — Tkinter front-end and workflow state machine.

Paste a YouTube link, Fetch, check the info card, tidy the song title,
trim and fade with the two sliders, listen with the preview buttons, pick
the key, Save. See docs/product_spec.md §4–§6 and docs/architecture.md §4
and §5.3.

Work runs on one background worker at a time. Workers never touch
widgets: they put messages on ``self._q``, which ``_pump`` drains on the
Tk thread every 50 ms.
"""

from __future__ import annotations

import math
import queue
import shutil
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

from karaokegrab import (cache, download, fetch, keys, naming, proc, render,
                         settings, timecode, tools, trim)
from karaokegrab.player import Player
from karaokegrab.rangeslider import RangeSlider
from karaokegrab.trim import TrimSpec
from karaokegrab.widgets import HAND, MAGENTA, PURPLE, Button

APP_NAME = "Karaoke Grabber"
KEY_NONE = "— none —"          # optional: no key leaves it out of the file name
THUMB_W, THUMB_H = 160, 90
PUMP_MS = 50
TICK_MS = 50          # playback cursor refresh

# --- states (docs/architecture.md §4) ---
IDLE = "idle"
FETCHING = "fetching"
DOWNLOADING = "downloading"
READY = "ready"
SAVING = "saving"
SAVED = "saved"
ERROR = "error"
CANCELLED = "cancelled"
BUSY = (FETCHING, DOWNLOADING, SAVING)

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


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._closing = False
        self._afters: set[str] = set()
        self._q: queue.Queue = queue.Queue()
        self._token = 0                       # bumps on each Fetch; stale messages are dropped
        self._cancel: proc.Cancel | None = None
        self.title_sheet: TitleSheet | None = None

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
        self.preparing = False          # a preview clip is being rendered
        self._clip: Path | None = None
        self._ticking = False

        self.url_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.meta_var = tk.StringVar()
        self.key_var = tk.StringVar(value=KEY_NONE)
        self.status_var = tk.StringVar()
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

        self._set_state(IDLE)
        if not self.tools.ok:
            self._show_error(self.tools.problem())
        else:
            self.status_var.set("Paste a YouTube link and click Fetch.")
        self.url_entry.focus_set()
        self._after(PUMP_MS, self._pump)

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
        threading.Thread(target=target, args=(self._token, self._cancel, *args),
                         daemon=True).start()

    # ------------------------------------------------------------ layout
    def _fonts(self) -> None:
        base = tkfont.nametofont("TkDefaultFont").actual()
        fam, size = base["family"], abs(int(base["size"]))
        self.f_title = tkfont.Font(family=fam, size=size + 5, weight="bold")
        self.f_head = tkfont.Font(family=fam, size=size - 1, weight="bold")
        self.f_small = tkfont.Font(family=fam, size=size - 1)
        self.f_save = tkfont.Font(family=fam, size=size + 3, weight="bold")

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

        # Info card: thumbnail, song title + pencil (F15), channel · duration, Key (F7)
        card = tk.Frame(root, bg=CARD_BG, highlightthickness=1, highlightbackground=CARD_EDGE)
        card.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        card.columnconfigure(1, weight=1)
        self.thumb = tk.Label(card, bg="#4b3a6b", fg="white", text="♪", font=self.f_title,
                              width=THUMB_W, height=THUMB_H, compound="center",
                              image=self._blank_image())
        self.thumb.grid(row=0, column=0, rowspan=4, padx=14, pady=14, sticky="nw")

        tk.Label(card, text="SONG TITLE · from YouTube, editable", font=self.f_small,
                 fg=MUTED, bg=CARD_BG).grid(row=0, column=1, sticky="sw", pady=(14, 0))
        trow = tk.Frame(card, bg=CARD_BG)
        trow.grid(row=1, column=1, sticky="ew", padx=(0, 14))
        trow.columnconfigure(0, weight=1)
        self.title_label = tk.Label(trow, textvariable=self.title_var, font=self.f_title,
                                    bg=CARD_BG, anchor="w", justify="left", wraplength=380)
        self.title_label.grid(row=0, column=0, sticky="w")
        self.pencil = Button(trow, "✎", PURPLE, self.edit_title)
        self.pencil.configure(padx=8, pady=2)
        self.pencil.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tk.Label(card, textvariable=self.meta_var, fg=MUTED, bg=CARD_BG).grid(
            row=2, column=1, sticky="w")

        krow = tk.Frame(card, bg=CARD_BG)
        krow.grid(row=3, column=1, sticky="w", pady=(6, 14))
        tk.Label(krow, text="♫ Key", font=self.f_head, bg=CARD_BG).grid(row=0, column=0, padx=(0, 8))
        self.key_box = ttk.Combobox(krow, textvariable=self.key_var,
                                    values=[KEY_NONE, *keys.KEYS],
                                    state="disabled", width=16, height=25)
        self.key_box.grid(row=0, column=1)
        self.key_box.bind("<<ComboboxSelected>>", lambda _e: self._key_changed())

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
        self.preview_btns = {}
        for i, (key, label, colour, cmd) in enumerate((
                ("from_start", "⏮  From start", DARK, self.preview_from_start),
                ("start", "▶  Start", PURPLE, self.preview_start),
                ("stop", "■  Stop", DARK, self.preview_stop),
                ("from_end", "⏭  From end", DARK, self.preview_from_end))):
            prow.columnconfigure(i, weight=1, uniform="p")
            b = Button(prow, label, colour, cmd)
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.preview_btns[key] = b

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
        self.cancel_link = tk.Label(srow, text="Cancel", fg=PURPLE, font=self.f_head,
                                    cursor=HAND)
        self.cancel_link.bind("<Button-1>", lambda _e: self.cancel())

        self.details_box = tk.Text(root, height=9, wrap="word", font="TkFixedFont",
                                   relief="flat", bg="#f4f4f6", padx=8, pady=6)
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
        if state in (DOWNLOADING, SAVING):
            self.progress.pack(fill="x", expand=True)
        else:
            self.progress.pack_forget()
        if busy:
            self.cancel_link.grid(row=0, column=2, sticky="e")
        else:
            self.cancel_link.grid_remove()
        if state != ERROR:
            self._hide_details()
        if state in BUSY:
            self._stop_preview()
        self._refresh_save()
        self._refresh_editing()

    def _key(self) -> str | None:
        return keys.lookup(self.key_var.get())

    def save_blocker(self) -> str:
        """Why Save is disabled, or '' when it's enabled."""
        if self.state in (FETCHING, DOWNLOADING):
            return "downloading…"
        if self.state == SAVING:
            return "saving…"
        if self.audio is None or self.info is None:
            return "fetch a video first"
        return ""

    def _refresh_save(self) -> None:
        why = self.save_blocker()
        self.save_btn.set_enabled(not why)
        self.save_btn.configure(text="Save MP3…" + (f"   · {why}" if why else ""))

    def _key_changed(self) -> None:
        self.key_box.selection_clear()
        self._refresh_save()

    def set_title(self, text: str) -> None:
        self.title_var.set(text)

    def _reset_for_new_url(self) -> None:
        self.info = None
        self.audio = None
        self.title_var.set("")
        self.meta_var.set("")
        self.key_var.set(KEY_NONE)
        self._thumb_img = None
        self.thumb.configure(image=self._blank, text="♪")
        self.progress.configure(value=0)
        self._stop_preview()
        self.spec = None
        self.cursor = 0.0
        self._sync_sliders()

    # ------------------------------------------------------------ actions
    def fetch(self) -> None:
        if self.state in BUSY:
            return
        url = self.url_var.get().strip()
        if not url:
            self.status_var.set("Paste a YouTube link first.")
            return
        self.tools = tools.locate()
        if not self.tools.ok:
            self._show_error(self.tools.problem())
            return
        self._token += 1
        self._reset_for_new_url()
        self.status_var.set("Looking up the video…")
        self._set_state(FETCHING)
        self._start_worker(self._fetch_worker, url, self.tools)

    def edit_title(self) -> None:
        if self.info is None or self.title_sheet is not None or self.state == SAVING:
            return
        self.title_sheet = TitleSheet(self)

    def save(self) -> None:
        if self.save_blocker():
            return
        assert self.info is not None and self.audio is not None
        key = self._key()
        folder = self.cfg.get("last_save_folder") or str(Path.home() / "Music")
        path = self._ask_save_path(folder if Path(folder).is_dir() else str(Path.home()),
                                   naming.filename(self.title_var.get(), key))
        if not path:
            # Save dialog cancelled: replace any earlier "Saved …" message.
            self.status_var.set("Not saved.")
            settings.log("save dialog cancelled")
            return
        out = Path(path)
        if out.suffix.lower() != ".mp3":
            out = out.with_name(out.name + ".mp3")
        spec = self.spec or TrimSpec().clamped(self.info.duration)
        self.progress.configure(value=0)
        self.status_var.set("Saving…")
        self._set_state(SAVING)
        self._start_worker(self._save_worker, self.tools["ffmpeg"], self.audio, spec, out)

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
        if self.state in BUSY and self._cancel is not None:
            self._cancel.set()
            self.status_var.set("Cancelling…")

    # ------------------------------------------------------------ trim, fades, cursor (M3)
    def _can_edit(self) -> bool:
        """Sliders and preview work once the audio is downloaded and nothing is busy."""
        return self.audio is not None and self.spec is not None and self.state not in BUSY

    def _refresh_editing(self) -> None:
        on = self._can_edit()
        self.trim_slider.set_enabled(on)
        self.fade_slider.set_enabled(on)
        active = self.player.playing or self.preparing
        for key, btn in self.preview_btns.items():
            btn.set_enabled(on and (active if key == "stop" else True))

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
        self.length_var.set(f"Trimmed length {fmt(spec.length)}")
        self.fade_in_var.set(fmt(spec.fade_in))
        self.fade_out_var.set(fmt(spec.fade_out))
        self.trim_note.set(f"whole track 0:00 – {fmt(duration)}")
        self.fade_note.set(f"trimmed range 0:00 – {fmt(spec.length)}")
        self._show_cursor()
        self._refresh_editing()

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
        self._stop_preview()            # changing the trim while playing stops playback
        self._set_spec(TrimSpec(start, end, self.spec.fade_in, self.spec.fade_out))

    def _fade_changed(self, a: float, b: float, final: bool) -> None:
        if self.spec is None:
            return
        self._stop_preview()
        s = self.spec
        self._set_spec(TrimSpec(s.start, s.end, a, s.length - b))

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
        was_active = self.player.playing or self.preparing
        self.cursor = min(max(t, self.spec.start), self.spec.end)
        self._show_cursor()
        if was_active:
            self._play()

    # -- preview buttons (F5)
    def preview_from_start(self) -> None:
        if self._can_edit():
            self.cursor = self.spec.start
            self._play()

    def preview_start(self) -> None:
        if self._can_edit():
            if self.cursor >= self.spec.end - 0.05:     # at the end: start over
                self.cursor = self.spec.start
            self._play()

    def preview_from_end(self) -> None:
        if self._can_edit():
            self.cursor = trim.from_end_cursor(self.spec)
            self._play()

    def preview_stop(self) -> None:
        self._stop_preview()

    def _stop_preview(self) -> None:
        """Stop playback (or a clip being prepared); the cursor stays where
        playback reached."""
        self._preview_token += 1
        self.preparing = False
        pos = self.player.stop()
        if pos is not None and self.spec is not None:
            self.cursor = min(max(pos, self.spec.start), self.spec.end)
            self._show_cursor()
        self._drop_clip()
        self._refresh_editing()

    def _drop_clip(self) -> None:
        if self._clip is not None:
            self._clip.unlink(missing_ok=True)
            self._clip = None

    def _play(self) -> None:
        """Render a clip from the cursor to the trim end (on a worker), then play it."""
        cursor = self.cursor
        self._stop_preview()            # would move the cursor to where the old clip had got to
        self.cursor = cursor
        assert self.spec is not None and self.audio is not None
        self._preview_token += 1
        self.preparing = True
        self._refresh_editing()
        self._show_cursor()
        at = self.spec.start + trim.preview_offset(self.spec, self.cursor)
        clip = self._tmp / f"preview-{self._preview_token}.wav"
        threading.Thread(target=self._preview_worker, daemon=True,
                         args=(self._token, self._preview_token, self.tools["ffmpeg"],
                               self.audio, self.spec, self.cursor, at, clip)).start()

    def _preview_worker(self, token: int, ptoken: int, ffmpeg: str, audio: Path,
                        spec: TrimSpec, cursor: float, at: float, clip: Path) -> None:
        try:
            out = render.render_preview(ffmpeg, audio, spec, cursor, clip)
            if out is not None:
                self._post(token, "preview_ready", ptoken, out, at)
        except render.RenderError as e:
            self._post(token, "preview_error", ptoken, e.message, e.details)
        except Exception as e:
            self._post(token, "preview_error", ptoken, f"Preview failed: {e}", repr(e))

    def _start_ticking(self) -> None:
        if not self._ticking:
            self._ticking = True
            self._after(TICK_MS, self._tick)

    def _tick(self) -> None:
        """Advance the cursor while a clip plays; at the clip's end the
        cursor rests at the trim end."""
        if self.player.playing and self.spec is not None:
            self.cursor = min(self.player.position(), self.spec.end)
            self._show_cursor()
            self._after(TICK_MS, self._tick)
            return
        self._ticking = False
        if self.player.finished and self.spec is not None:
            self.player.reset()
            self._drop_clip()
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
                thumb = fetch.fetch_thumbnail(ytdlp, info_json, cache.thumb_stem(info.id), cancel=cancel)
                if thumb is not None:
                    self._post(token, "thumb", thumb)
                audio = download.download(
                    ytdlp, info.id, info_json, cancel=cancel,
                    on_progress=lambda p: self._post(token, "progress", p.fraction))
                if audio is None:
                    return self._post(token, "cancelled", DOWNLOADING)
                settings.log(f"downloaded {info.id} → {audio.name}")
            else:
                thumb = cache.thumb_stem(info.id).with_suffix(".png")
                if thumb.exists():
                    self._post(token, "thumb", thumb)
            cache.prune(protect=info.id)
            self._post(token, "downloaded", audio)
        except (fetch.FetchError, download.DownloadError) as e:
            self._post(token, "error", e.message, e.details)
        except Exception as e:  # never leave the UI stuck in a busy state
            self._post(token, "error", f"Something went wrong: {e}", repr(e))

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
            self._post(token, "error", e.message, e.details)
        except Exception as e:
            self._post(token, "error", f"Something went wrong: {e}", repr(e))

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
            self.status_var.set("Downloading…")
            self._set_state(DOWNLOADING)
        elif kind == "thumb":
            (path,) = payload
            self._show_thumbnail(path)
        elif kind == "progress":
            (fraction,) = payload
            if fraction is not None:
                self.progress.configure(value=fraction)
                verb = "Saving" if self.state == SAVING else "Downloading"
                self.status_var.set(f"{verb}… {int(fraction * 100)}%")
        elif kind == "downloaded":
            (audio,) = payload
            self.audio = audio
            self.progress.configure(value=1.0)
            self.status_var.set("Ready. Trim and preview, pick the key if you like, then save.")
            self._set_state(READY)
        elif kind == "saved":
            (path,) = payload
            self.cfg["last_save_folder"] = str(path.parent)
            settings.save(self.cfg)
            self.status_var.set(f"Saved “{path.name}” in {path.parent}.")
            self._set_state(SAVED)
        elif kind == "cancelled":
            (stage,) = payload
            self.progress.configure(value=0)
            settings.log(f"cancelled while {stage}")
            if stage == SAVING:
                self.status_var.set("Save cancelled. Nothing was written.")
                self._set_state(READY)
            else:
                self._reset_for_new_url()
                self.status_var.set("Cancelled.")
                self._set_state(CANCELLED)
        elif kind == "preview_ready":
            ptoken, clip, at = payload
            if ptoken != self._preview_token or not self.preparing:
                clip.unlink(missing_ok=True)
                return
            self.preparing = False
            self._clip = clip
            self.player.play(clip, at)
            self.cursor = at
            self._show_cursor()
            self._refresh_editing()
            self._start_ticking()
        elif kind == "preview_error":
            ptoken, message, details = payload
            if ptoken == self._preview_token:
                self.preparing = False
                self._refresh_editing()
                self.details = details
                self.status_var.set(message)
        elif kind == "error":
            message, details = payload
            if details:
                settings.log("error: " + message + "\n" + details)
            if self.audio is None:
                self._reset_for_new_url()
            self._show_error(message, details)

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

    def _show_error(self, message: str, details: str = "") -> None:
        self.details = details
        self.progress.configure(value=0)
        self.status_var.set(message)
        self._set_state(ERROR)
        self.status_label.configure(fg=WARN)
        if details:
            self.details_link.configure(text="Details ▸")
            self.details_link.grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _hide_details(self) -> None:
        self.status_label.configure(fg=self._status_fg)
        self.details_link.grid_remove()
        self.details_box.grid_remove()
        self.details_shown = False

    def toggle_details(self) -> None:
        if not self.details:
            return
        self.details_shown = not self.details_shown
        if self.details_shown:
            self.details_box.configure(state="normal")
            self.details_box.delete("1.0", "end")
            self.details_box.insert("1.0", self.details)
            self.details_box.configure(state="disabled")
            self.details_box.grid(row=13, column=0, sticky="nsew", pady=(6, 0))
            self.details_link.configure(text="Details ▾")
        else:
            self.details_box.grid_remove()
            self.details_link.configure(text="Details ▸")

    # ------------------------------------------------------------ close
    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._cancel is not None:
            self._cancel.set()            # kills any running yt-dlp / ffmpeg
        self.player.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)
        for tid in list(self._afters):
            try:
                self.after_cancel(tid)
            except tk.TclError:
                pass
        self._afters.clear()
        if self.title_sheet is not None:
            try:
                self.title_sheet.close()
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
    App().mainloop()


if __name__ == "__main__":
    main()
