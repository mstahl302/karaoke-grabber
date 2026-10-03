#!/usr/bin/env python3
"""Karaoke Grabber — Tkinter front-end and workflow state machine.

Paste a YouTube link, Fetch, check the info card, tidy the song title,
pick the key, Save. M2 saves the whole track; the Trim, Fade and Preview
sections are placeholders until M3. See docs/product_spec.md §4–§6 and
docs/architecture.md §4.

Work runs on one background worker at a time. Workers never touch
widgets: they put messages on ``self._q``, which ``_pump`` drains on the
Tk thread every 50 ms.
"""

from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, ttk

from karaokegrab import (cache, download, fetch, keys, naming, proc, render,
                         settings, timecode, tools)
from karaokegrab.trim import TrimSpec
from karaokegrab.widgets import HAND, MAGENTA, PURPLE, Button

APP_NAME = "Karaoke Grabber"
KEY_PLACEHOLDER = "— choose —"
THUMB_W, THUMB_H = 160, 90
PUMP_MS = 50

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

        self.url_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.meta_var = tk.StringVar()
        self.key_var = tk.StringVar(value=KEY_PLACEHOLDER)
        self.status_var = tk.StringVar()

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

    def _section(self, parent, row: int, text: str, note: str = "") -> ttk.Frame:
        head = ttk.Frame(parent)
        head.grid(row=row, column=0, sticky="ew", pady=(14, 4))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text=text.upper(), font=self.f_head, fg=MUTED).grid(row=0, column=0, sticky="w")
        if note:
            tk.Label(head, text=note, font=self.f_small, fg=MUTED).grid(row=0, column=1, sticky="e")
        return head

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
        self.key_box = ttk.Combobox(krow, textvariable=self.key_var, values=list(keys.KEYS),
                                    state="disabled", width=16, height=24)
        self.key_box.grid(row=0, column=1)
        self.key_box.bind("<<ComboboxSelected>>", lambda _e: self._key_changed())
        self.key_hint = tk.Label(krow, text="required", fg=WARN, bg=CARD_BG)
        self.key_hint.grid(row=0, column=2, padx=(10, 0))

        # Placeholders for M3 (Trim, Fade, Preview)
        self._section(root, 2, "Trim", "arrives in M3")
        self._placeholder(root, 3, "Two handles to cut the intro and outro.")
        self._section(root, 4, "Fade", "arrives in M3")
        self._placeholder(root, 5, "Fade in and out within the trimmed range. No fade by default.")
        self._section(root, 6, "Preview", "arrives in M3")
        prow = ttk.Frame(root)
        prow.grid(row=7, column=0, sticky="ew")
        for i, label in enumerate(("From start", "Start", "Stop", "From end")):
            prow.columnconfigure(i, weight=1, uniform="p")
            ttk.Button(prow, text=label, state="disabled").grid(
                row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))

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

    def _placeholder(self, parent, row: int, text: str) -> None:
        f = tk.Frame(parent, bg="#f4f4f6", highlightthickness=1, highlightbackground="#e4e4e8")
        f.grid(row=row, column=0, sticky="ew")
        tk.Label(f, text=text, fg="#a09aa6", bg="#f4f4f6").pack(padx=12, pady=12, anchor="w")

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
        self._refresh_save()

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
        if self._key() is None:
            return "pick a key first"
        return ""

    def _refresh_save(self) -> None:
        why = self.save_blocker()
        self.save_btn.set_enabled(not why)
        self.save_btn.configure(text="Save MP3…" + (f"   · {why}" if why else ""))
        if self.info is not None and self._key() is None:
            self.key_hint.grid()
        else:
            self.key_hint.grid_remove()

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
        self.key_var.set(KEY_PLACEHOLDER)
        self._thumb_img = None
        self.thumb.configure(image=self._blank, text="♪")
        self.progress.configure(value=0)

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
        spec = TrimSpec().clamped(self.info.duration)
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
            self.status_var.set("Ready. Pick the key, then save.")
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
