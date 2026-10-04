"""Drive the main window headlessly: a real tk.Tk(), the real engine
modules, and only the subprocess layer (proc.run) faked. No network."""

import json
import sys
import time
import wave
from pathlib import Path

import pytest

import main
from karaokegrab import cache, settings, tools
from conftest import result

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _pump(app, until, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out in state {app.state!r}")


@pytest.fixture
def all_tools(monkeypatch):
    found = tools.Toolset(paths={n: f"/opt/homebrew/bin/{n}" for n in tools.TOOLS},
                          brew="/opt/homebrew/bin/brew")
    monkeypatch.setattr(tools, "locate", lambda: found)
    return found


class Tools:
    """Fake yt-dlp and ffmpeg behind proc.run. Set ``hold_download``,
    ``hold_save`` or ``hold_preview`` to make that step wait until cancelled.
    Preview renders write a real (silent, 8 kHz) WAV of the requested length."""

    def __init__(self, fake_run, video_json):
        self.video_json = video_json
        self.hold_download = False
        self.hold_save = False
        self.hold_preview = False
        self.cancelled_previews = 0
        self.save_argv: list[str] | None = None
        self.preview_argvs: list[list[str]] = []
        fake_run.on(lambda a: "-J" in a, self.info)
        fake_run.on(lambda a: "--write-thumbnail" in a, self.thumb)
        fake_run.on(lambda a: "--progress-template" in a, self.download)
        fake_run.on(lambda a: a[0].endswith("ffmpeg"), self.ffmpeg)

    def info(self, argv, on_line, cancel):
        return result(argv, stdout=json.dumps(self.video_json))

    def thumb(self, argv, on_line, cancel):
        return result(argv, returncode=1)            # no thumbnail: the card keeps its placeholder

    def download(self, argv, on_line, cancel):
        out = Path(argv[argv.index("-o") + 1]).parent
        on_line("PROG|100|200|NA|1")
        if self.hold_download:
            (out / "audio.webm.part").write_bytes(b"half")
            cancel.wait(5)
            return result(argv, returncode=-15, cancelled=True)
        (out / "audio.webm").write_bytes(b"opus")
        return result(argv)

    def ffmpeg(self, argv, on_line, cancel):
        if argv[-2] == "wav":
            hold = self.hold_preview                  # read before the test can see this call
            self.preview_argvs.append(argv)
            seconds = float(argv[argv.index("-t") + 1])
            with wave.open(argv[-1], "wb") as w:      # the .part file
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\0\0" * int(seconds * 8000))
            on_line("out_time_us=1000000")
            if hold:
                cancel.wait(5)
                self.cancelled_previews += 1
                return result(argv, returncode=-15, cancelled=True)
            return result(argv)
        self.save_argv = argv
        Path(argv[-1]).write_bytes(b"mp3")           # the .part file
        on_line("out_time_us=9500000")
        if self.hold_save:
            cancel.wait(5)
            return result(argv, returncode=-15, cancelled=True)
        return result(argv)


@pytest.fixture
def fake_tools(all_tools, fake_run, video_json):
    return Tools(fake_run, video_json)


@pytest.fixture
def app():
    a = main.App()
    yield a
    a._on_close()


@pytest.fixture
def save_to(monkeypatch, tmp_path):
    """Answer the Save dialog with a path in tmp_path; records its arguments."""
    seen: dict = {}

    def dialog(**kw):
        seen.update(kw)
        return str(tmp_path / "out" / kw["initialfile"])

    (tmp_path / "out").mkdir()
    monkeypatch.setattr(main.filedialog, "asksaveasfilename", dialog)
    return seen


def _fetch(app, url=URL):
    app.url_var.set(url)
    app.fetch()
    _pump(app, lambda: app.state in (main.READY, main.ERROR))


def _pick(app, key):
    app.key_var.set(key)
    app._key_changed()


def test_starts_idle_with_save_disabled(fake_tools, app):
    app.update()
    assert app.state == main.IDLE
    assert not app.progress.winfo_ismapped()
    assert app.save_blocker() == "fetch a video first"
    assert str(app.key_box.cget("state")) == "disabled"


def test_save_is_ready_without_a_key(fake_tools, app):
    _fetch(app)
    assert app.state == main.READY
    assert app.title_var.get() == "Me at the zoo"
    assert app.meta_var.get() == "jawed · 19.0 s"
    assert str(app.key_box.cget("state")) == "readonly"
    assert app.key_var.get() == main.KEY_NONE
    assert app.save_blocker() == ""
    assert app.save_btn.cget("text") == "Save MP3…"
    assert app.key_box.cget("values")[0] == main.KEY_NONE   # "— none —" clears a picked key


def test_no_key_leaves_it_out_of_the_filename(fake_tools, app, save_to, tmp_path):
    _fetch(app)
    for key, name in ((None, "Me at the zoo - AUDIO.mp3"),
                      ("B-flat", "Me at the zoo - AUDIO - B-flat.mp3"),
                      (main.KEY_NONE, "Me at the zoo - AUDIO.mp3")):
        if key:
            _pick(app, key)
        app.save()
        _pump(app, lambda: app.state == main.SAVED)
        assert save_to["initialfile"] == name
        assert (tmp_path / "out" / name).exists()


def test_save_writes_the_named_full_length_mp3(fake_tools, app, save_to, tmp_path):
    _fetch(app)
    _pick(app, "B-flat")
    app.save()
    _pump(app, lambda: app.state == main.SAVED)
    saved = tmp_path / "out" / "Me at the zoo - AUDIO - B-flat.mp3"
    assert save_to["initialfile"] == saved.name
    assert saved.read_bytes() == b"mp3"
    assert not Path(str(saved) + ".part").exists()
    argv = fake_tools.save_argv
    assert argv[argv.index("-ss") + 1] == "0" and argv[argv.index("-t") + 1] == "19"
    assert "-af" not in argv                      # untouched sliders: whole track, no fades
    assert settings.load()["last_save_folder"] == str(tmp_path / "out")
    assert "Saved" in app.status_var.get()
    app.update()
    assert not app.progress.winfo_ismapped()      # the bar is only shown while busy
    # A standalone dialog, not a sheet on the main window, and no Format popup
    assert save_to["parent"] is not app and "filetypes" not in save_to
    # Saving again opens the dialog in the last-used folder
    app.save()
    assert save_to["initialdir"] == str(tmp_path / "out")


def test_edited_title_feeds_the_filename(fake_tools, app, save_to):
    _fetch(app)
    app.edit_title()
    sheet = app.title_sheet
    assert sheet is not None and sheet.value.get() == "Me at the zoo"
    sheet.value.set("  Zoo   Song ")
    sheet.save()
    assert app.title_sheet is None
    assert app.title_var.get() == "Zoo Song"
    _pick(app, "C")
    app.save()
    assert save_to["initialfile"] == "Zoo Song - AUDIO - C.mp3"


def _press(sheet, key):
    """Type *key* into the sheet's text field. Key events go to the focus
    window, and headless X11 (CI) has no window manager to hand it out."""
    sheet.entry.focus_force()
    sheet.update()
    sheet.entry.event_generate(key)
    sheet.update()


def test_title_sheet_keys(fake_tools, app):
    _fetch(app)
    app.edit_title()
    app.update()                                       # the sheet is on screen before a key press
    app.title_sheet.value.set("Changed")
    _press(app.title_sheet, "<Escape>")
    assert app.title_sheet is None
    assert app.title_var.get() == "Me at the zoo"          # Esc cancels
    app.edit_title()
    app.update()
    app.title_sheet.value.set("Changed")
    _press(app.title_sheet, "<Return>")
    assert app.title_sheet is None
    assert app.title_var.get() == "Changed"                # Return saves


def test_title_and_key_reset_for_a_new_url(fake_tools, app):
    _fetch(app)
    app.set_title("My edit")
    _pick(app, "D")
    fake_tools.video_json = {**fake_tools.video_json, "id": "other12345", "title": "Another"}
    _fetch(app, "https://youtu.be/other12345")
    assert app.title_var.get() == "Another"
    assert app.key_var.get() == main.KEY_NONE


def test_second_fetch_of_the_same_video_uses_the_cache(fake_tools, fake_run, app):
    _fetch(app)
    fake_run.calls.clear()
    _fetch(app)
    assert app.state == main.READY
    assert not any("--progress-template" in c for c in fake_run.calls)


def test_cancel_during_download_leaves_no_partial_file(fake_tools, app):
    fake_tools.hold_download = True
    app.url_var.set(URL)
    app.fetch()
    _pump(app, lambda: app.state == main.DOWNLOADING and app.progress.cget("value") > 0)
    assert app.cancel_btn.winfo_ismapped()
    app.cancel()
    _pump(app, lambda: app.state == main.CANCELLED)
    assert list(cache.video_dir("jNQXAC9IVRw").glob("audio.*")) == []
    assert app.info is None and app.title_var.get() == ""
    assert app.save_blocker() == "fetch a video first"


def test_cancel_during_save_leaves_no_part_file(fake_tools, app, save_to, tmp_path):
    _fetch(app)
    _pick(app, "E")
    fake_tools.hold_save = True
    app.save()
    _pump(app, lambda: app.state == main.SAVING and app.progress.cget("value") > 0)
    assert str(app.key_box.cget("state")) == "disabled"
    assert app.progress.winfo_ismapped()
    app.cancel()
    _pump(app, lambda: app.state == main.READY)
    assert list((tmp_path / "out").iterdir()) == []
    assert "cancelled" in app.status_var.get()
    assert app.save_blocker() == ""                 # the download is still there: save again


def test_fetch_error_shows_friendly_message_and_details(all_tools, fake_run, app):
    fake_run.on(lambda a: True, lambda a, ol, c: result(
        a, returncode=1, stderr="ERROR: [youtube] xxxxxxxxxxx: This video is unavailable"))
    _fetch(app, "https://www.youtube.com/watch?v=xxxxxxxxxxx")
    assert app.state == main.ERROR
    app.update()
    # fetch problems show right under the link box, not in the status line
    assert app.fetch_error.winfo_ismapped()
    assert "unavailable" in app.fetch_error_var.get()
    assert app.fetch_details_link.winfo_ismapped()
    app.toggle_details()
    app.update()
    assert app.fetch_details_box.winfo_ismapped()
    assert "This video is unavailable" in app.fetch_details_box.get("1.0", "end")
    app.toggle_details()
    app.update()
    assert not app.fetch_details_box.winfo_ismapped()
    app.url_entry.event_generate("<Key>", keysym="a")      # editing the link clears it
    app.update()
    assert not app.fetch_error.winfo_ismapped()
    assert "This video is unavailable" in settings.LOG_PATH.read_text()


def test_download_failure_suggests_updating_ytdlp(fake_tools, fake_run, app):
    fake_run.handlers.insert(0, (lambda a: "--progress-template" in a,
                                 lambda a, ol, c: result(a, returncode=1, stderr="ERROR: 403")))
    _fetch(app)
    assert app.state == main.ERROR
    assert "brew upgrade yt-dlp" in app.fetch_error_var.get()
    assert app.save_blocker() == "fetch a video first"


def test_missing_tools_are_reported_on_launch(monkeypatch, fake_run):
    monkeypatch.setattr(tools, "locate", lambda: tools.Toolset(
        paths={"yt-dlp": None, "ffmpeg": "/x", "ffprobe": "/x", "deno": "/x"},
        brew="/x/brew", missing=["yt-dlp"]))
    a = main.App()
    try:
        assert a.state == main.ERROR
        assert "brew install yt-dlp" in a.fetch_error_var.get()
        a.url_var.set(URL)
        a.fetch()
        assert fake_run.calls == []
    finally:
        a._on_close()


def test_closing_mid_download_cancels_the_worker(fake_tools, app):
    fake_tools.hold_download = True
    app.url_var.set(URL)
    app.fetch()
    _pump(app, lambda: app.state == main.DOWNLOADING)
    cancel = app._cancel
    app._on_close()
    assert cancel.is_set


def test_cancelling_the_save_dialog_replaces_the_saved_message(fake_tools, app, save_to, monkeypatch):
    _fetch(app)
    _pick(app, "C")
    app.save()
    _pump(app, lambda: app.state == main.SAVED)
    assert app.status_var.get().startswith("Saved")
    monkeypatch.setattr(main.filedialog, "asksaveasfilename", lambda **kw: "")
    app.save()
    assert app.status_var.get() == "Not saved."
    assert app.state == main.SAVED                 # nothing else changes; Save still available
    assert app.save_blocker() == ""


def test_cancel_after_an_earlier_save_says_cancelled(fake_tools, app, save_to):
    _fetch(app)
    _pick(app, "C")
    app.save()
    _pump(app, lambda: app.state == main.SAVED)
    fake_tools.hold_save = True
    app.save()
    _pump(app, lambda: app.state == main.SAVING)
    app.cancel()
    _pump(app, lambda: app.state == main.READY)
    assert app.status_var.get() == "Save cancelled. Nothing was written."
    assert "cancelled while saving" in settings.LOG_PATH.read_text()



# --- M3/M4: trim, fade, cursor, the background preview ----------------------

from karaokegrab.player import Player       # noqa: E402
from karaokegrab.trim import TrimSpec        # noqa: E402
from test_player import Clock, FakeProc      # noqa: E402


@pytest.fixture
def player(app):
    """A Player with fake afplay processes and a hand-moved clock."""
    procs, clock = [], Clock()

    def popen(argv, **kw):
        p = FakeProc()
        p.argv = argv
        procs.append(p)
        return p

    app.player = Player(popen=popen, clock=clock)
    app.player.procs, app.player.clock = procs, clock
    return app.player


def _preview_ready(app):
    _pump(app, lambda: app.preview_clip is not None and not app.preparing)


def _ready(app):
    """Fetched, downloaded, and the background preview is ready to play."""
    _fetch(app)
    assert app.state == main.READY
    _preview_ready(app)


def _wav_seconds(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def test_sliders_start_at_the_whole_track_with_no_fades(fake_tools, app):
    assert not app.trim_slider.enabled and not app.play_btn._enabled
    _ready(app)
    assert app.spec == TrimSpec(0, 19, 0, 0)
    assert app.trim_slider.enabled and app.fade_slider.enabled
    assert (app.trim_slider.lo, app.trim_slider.hi) == (0, 19)
    assert (app.fade_slider.a, app.fade_slider.b) == (0, 19)
    assert app.start_var.get() == "0.0 s" and app.end_var.get() == "19.0 s"
    assert app.length_var.get() == "Trimmed length 19.0 s"
    assert app.fade_in_var.get() == app.fade_out_var.get() == "0.0 s"
    assert app.play_btn._enabled and app.play_btn.symbol == "play"


def test_preview_is_made_in_the_background_after_the_download(fake_tools, app):
    _fetch(app)
    assert app.preparing and not app.play_btn._enabled          # play waits for it
    assert not app.preview_btns["from_start"]._enabled
    _preview_ready(app)
    argv = fake_tools.preview_argvs[-1]
    assert argv[argv.index("-ss") + 1] == "0" and argv[argv.index("-t") + 1] == "19"
    assert _wav_seconds(app.preview_clip) == 19
    assert app.status_var.get().startswith("Ready.")            # the status comes back
    app.update()
    assert not app.progress.winfo_ismapped()


def test_changing_a_slider_remakes_the_preview_once_it_settles(fake_tools, app):
    _ready(app)
    renders = len(fake_tools.preview_argvs)
    for end in (18, 17, 16):                                     # a drag: three quick moves
        app._trim_changed(2, end, False)
        assert app.preview_clip is None and app.preparing and not app.play_btn._enabled
    _preview_ready(app)
    assert len(fake_tools.preview_argvs) == renders + 1          # one render, after it settled
    argv = fake_tools.preview_argvs[-1]
    assert argv[argv.index("-ss") + 1] == "2" and argv[argv.index("-t") + 1] == "14"


def test_a_slider_change_kills_a_render_in_progress(fake_tools, app):
    _ready(app)
    fake_tools.hold_preview = True
    renders = len(fake_tools.preview_argvs)
    app._fade_changed(1, 19, True)
    _pump(app, lambda: len(fake_tools.preview_argvs) > renders)   # ffmpeg is running
    running = app._preview_cancel
    fake_tools.hold_preview = False
    app._fade_changed(2, 19, True)
    assert running.is_set
    _preview_ready(app)
    _pump(app, lambda: fake_tools.cancelled_previews == 1)
    argv = fake_tools.preview_argvs[-1]
    assert argv[argv.index("-af") + 1].startswith("afade=t=in:st=0:d=2")


def test_fade_slider_rescales_with_the_trim_and_fades_stay_clamped(fake_tools, app):
    _ready(app)
    app._fade_changed(5, 14, True)              # fade in 5 s, fade out 5 s
    assert (app.spec.fade_in, app.spec.fade_out) == (5, 5)
    app._trim_changed(2, 8, True)               # only 6 s left
    assert (app.spec.start, app.spec.end) == (2, 8)
    assert (app.fade_slider.lo, app.fade_slider.hi) == (0, 6)
    assert (app.spec.fade_in, app.spec.fade_out) == (5, 1)
    assert (app.fade_slider.a, app.fade_slider.b) == (5, 5)


def test_save_uses_the_trim_and_fades(fake_tools, app, save_to):
    _ready(app)
    _pick(app, "G")
    app._trim_changed(2.5, 16, True)
    app._fade_changed(1, 11.5, True)            # in 1 s; out 13.5 − 11.5 = 2 s
    app.save()
    _pump(app, lambda: app.state == main.SAVED)
    argv = fake_tools.save_argv
    assert argv[argv.index("-ss") + 1] == "2.5" and argv[argv.index("-t") + 1] == "13.5"
    assert argv[argv.index("-af") + 1] == "afade=t=in:st=0:d=1,afade=t=out:st=11.5:d=2"


def test_cursor_is_shared_by_both_sliders(fake_tools, app):
    _ready(app)
    app._trim_changed(4, 16, True)
    app._seek_fade(3)                           # 3 s into the trim
    assert app.cursor == 7
    assert app.trim_slider.cursor == 7 and app.fade_slider.cursor == 3
    assert app.cursor_note.get() == "cursor 7.0 s (3.0 s into trim)"
    app._seek_trim(1)                           # before the trim: clamped to its start
    assert app.cursor == 4


def test_play_from_start_uses_the_preview_itself(fake_tools, app, player):
    _ready(app)
    app.preview_from_start()
    assert player.procs[-1].argv[1] == str(app.preview_clip)
    assert app.player.playing and app.play_btn.symbol == "pause"


def test_play_from_the_cursor_cuts_the_preview_there(fake_tools, app, player):
    _ready(app)
    app._seek_trim(5)
    renders = len(fake_tools.preview_argvs)
    app.toggle_play()
    clip = Path(player.procs[-1].argv[1])
    assert clip != app.preview_clip and _wav_seconds(clip) == 14
    assert app.player.offset == 5
    assert len(fake_tools.preview_argvs) == renders               # no new render: instant


def test_pause_keeps_the_preview_and_the_cursor(fake_tools, app, player):
    _ready(app)
    app._seek_trim(5)
    app.toggle_play()
    player.clock.now += 2.5
    _pump(app, lambda: app.cursor == 7.5)
    app.toggle_play()                                              # pause
    assert player.procs[-1].terminated and app.cursor == 7.5
    assert app.play_btn.symbol == "play" and app.preview_clip.exists()
    renders = len(fake_tools.preview_argvs)
    app.toggle_play()                                              # and play again, at once
    assert app.player.playing and app.player.offset == 7.5
    assert len(fake_tools.preview_argvs) == renders


def test_from_end_plays_the_last_ten_seconds(fake_tools, app, player):
    _ready(app)
    app._trim_changed(0, 18, True)
    _preview_ready(app)
    app.preview_from_end()
    assert app.cursor == 8 and _wav_seconds(player.procs[-1].argv[1]) == 10


def test_cursor_rests_at_the_end_when_the_clip_finishes(fake_tools, app, player):
    _ready(app)
    app._trim_changed(2, 12, True)
    _preview_ready(app)
    app.preview_from_end()
    player.procs[-1].returncode = 0            # afplay reached the end
    _pump(app, lambda: not app.player.finished and app.cursor == 12)
    assert app.play_btn.symbol == "play"
    app.toggle_play()                           # at the end it starts over from the trim start
    assert app.player.offset == 2


def test_changing_the_trim_or_fades_stops_playback(fake_tools, app, player):
    _ready(app)
    app.preview_from_start()
    app._trim_changed(1, 19, False)
    assert player.procs[-1].terminated and not app.player.playing
    _preview_ready(app)
    app.preview_from_start()
    app._fade_changed(2, 18, False)
    assert player.procs[-1].terminated


def test_clicking_the_track_while_playing_continues_from_there(fake_tools, app, player):
    _ready(app)
    app.preview_from_start()
    app._seek_trim(12)
    assert player.procs[0].terminated and app.player.playing
    assert app.player.offset == 12


def test_saving_pauses_playback_and_locks_the_sliders(fake_tools, app, player, save_to):
    _ready(app)
    _pick(app, "A")
    app.preview_from_start()
    fake_tools.hold_save = True
    app.save()
    assert player.procs[-1].terminated
    assert not app.trim_slider.enabled and not app.play_btn._enabled
    app.cancel()
    _pump(app, lambda: app.state == main.READY)
    assert app.trim_slider.enabled and app.play_btn._enabled     # the preview survived


def test_new_url_resets_trim_fades_cursor_and_preview(fake_tools, app):
    _ready(app)
    app._trim_changed(3, 9, True)
    app._fade_changed(1, 5, True)
    app._seek_trim(6)
    fake_tools.video_json = {**fake_tools.video_json, "id": "other12345", "duration": 30}
    _fetch(app, "https://youtu.be/other12345")
    assert app.spec == TrimSpec(0, 30, 0, 0)
    assert app.cursor == 0
    _preview_ready(app)
    assert _wav_seconds(app.preview_clip) == 30


# --- M4: progress steps, shortcuts, prerequisites, robustness -------------------

def test_fetch_walks_through_the_progress_steps(fake_tools, app):
    seen = []
    real_step = app._step
    app._step = lambda f, m: (seen.append((m, round(f, 2))), real_step(f, m))
    _fetch(app)
    _preview_ready(app)
    messages = [m for m, _ in seen]
    fetch_part = messages[:messages.index("Finishing…") + 1]
    assert fetch_part[:3] == ["Looking up the video…", "Getting the thumbnail…",
                              "Downloading the audio…"]
    assert "Downloading the audio… 50%" in fetch_part
    values = [v for _, v in seen][:len(fetch_part)]
    assert values == sorted(values)                       # the bar only moves forward
    assert values[0] == main.STEP_LOOKUP and values[-1] == main.STEP_FINISH
    assert messages[len(fetch_part)] == "Preparing preview…"   # then the background preview


def test_cancel_is_a_button_beside_the_bar_while_fetching(fake_tools, app):
    fake_tools.hold_download = True
    app.url_var.set(URL)
    app.fetch()
    app.update()
    assert app.progress.winfo_ismapped() and app.cancel_btn.winfo_ismapped()
    app.cancel()
    _pump(app, lambda: app.state == main.CANCELLED)
    app.update()
    assert not app.cancel_btn.winfo_ismapped()


@pytest.mark.parametrize("text, message", [
    ("https://www.youtube.com/playlist?list=PL1", main.fetch.PLAYLIST),
    ("https://vimeo.com/1", main.fetch.NOT_YOUTUBE),
    ("look: https://www.youtube.com/watch?v=jNQXAC9IVRw", main.fetch.NOT_A_LINK),
    ("https://www.youtube.com/@SingKingKaraoke", main.fetch.NOT_A_VIDEO),
])
def test_bad_links_are_rejected_instantly_under_the_link_box(fake_tools, fake_run, app, text, message):
    app.url_var.set(text)
    app.fetch()
    app.update()
    assert app.state == main.ERROR
    assert app.fetch_error_var.get() == message and app.fetch_error.winfo_ismapped()
    assert fake_run.calls == []


def test_clicking_a_slider_takes_focus_out_of_the_link_box(fake_tools, app, player):
    _ready(app)
    app.url_entry.focus_force()
    app.update()
    app.trim_slider.event_generate("<Button-1>", x=5, y=5)
    app.update()
    assert app.focus_get() is not app.url_entry


def test_space_plays_and_pauses_but_not_while_typing(fake_tools, app, player):
    _ready(app)
    app.focus_force()
    app.update()
    app.event_generate("<space>")
    app.update()
    assert app.player.playing
    app.event_generate("<space>")
    app.update()
    assert not app.player.playing
    app.url_entry.focus_force()
    app.update()
    app.url_entry.event_generate("<space>")
    app.update()
    assert not app.player.playing


def test_command_s_saves(fake_tools, app, save_to):
    _ready(app)
    mod = "Command" if sys.platform == "darwin" else "Control"
    app.focus_force()
    app.update()
    app.event_generate(f"<{mod}-s>")
    _pump(app, lambda: app.state == main.SAVED)


def test_reveal_in_finder_after_saving(fake_tools, app, save_to, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(main.subprocess, "Popen", lambda argv, **kw: opened.append(argv))
    _ready(app)
    assert not app.reveal_link.winfo_ismapped()
    app.save()
    _pump(app, lambda: app.state == main.SAVED)
    app.update()
    assert app.reveal_link.winfo_ismapped()
    app.reveal()
    assert opened == [["open", "-R", str(tmp_path / "out" / "Me at the zoo - AUDIO.mp3")]]


def test_missing_tools_open_the_install_dialog(monkeypatch, fake_run):
    missing = tools.Toolset(paths={"yt-dlp": "/x", "ffmpeg": None, "ffprobe": None, "deno": "/x"},
                            brew="/x/brew", missing=["ffmpeg", "ffprobe"])
    monkeypatch.setattr(tools, "locate", lambda: missing)
    a = main.App()
    try:
        _pump(a, lambda: a.prereq_dialog is not None)
        d = a.prereq_dialog
        assert d.command == "brew install ffmpeg"
        d.copy()
        assert a.clipboard_get() == "brew install ffmpeg"
        d.check()                                          # still missing: stays open
        assert a.prereq_dialog is d
        found = tools.Toolset(paths={n: "/x" for n in tools.TOOLS}, brew="/x/brew")
        monkeypatch.setattr(tools, "locate", lambda: found)
        d.check()
        assert a.prereq_dialog is None and a.state == main.IDLE
    finally:
        a._on_close()


def test_missing_homebrew_points_to_brew_sh(monkeypatch, fake_run):
    monkeypatch.setattr(tools, "locate", lambda: tools.Toolset(
        paths={n: None for n in tools.TOOLS}, brew=None, missing=list(tools.TOOLS)))
    a = main.App()
    try:
        _pump(a, lambda: a.prereq_dialog is not None)
        texts = " ".join(str(w.cget("text")) for w in a.prereq_dialog.frm.winfo_children()
                         if "text" in w.keys())
        assert "Homebrew isn't installed" in texts and "Open brew.sh" in texts
    finally:
        a._on_close()


def test_cache_is_pruned_on_launch(fake_tools):
    import os
    for i in range(12):
        d = cache.video_dir(f"v{i:02d}")
        d.mkdir(parents=True)
        (d / "audio.webm").write_bytes(b"x")
        os.utime(d, (1000 + i, 1000 + i))
    a = main.App()
    try:
        assert len(list(cache.CACHE_DIR.iterdir())) == cache.KEEP
    finally:
        a._on_close()


def test_audio_removed_from_the_cache_is_downloaded_again(fake_tools, fake_run, app, save_to):
    _ready(app)
    app.audio.unlink()
    fake_run.calls.clear()
    app.save()                                             # notices, downloads again, then saves
    _pump(app, lambda: app.state == main.SAVED)
    assert any("--progress-template" in c for c in fake_run.calls)
    assert app.audio.exists()


def test_quitting_mid_save_leaves_no_part_file(fake_tools, app, save_to, tmp_path):
    _ready(app)
    fake_tools.hold_save = True
    app.save()
    _pump(app, lambda: app.state == main.SAVING and app.progress.cget("value") > 0)
    assert list((tmp_path / "out").glob("*.part"))
    app._on_close()
    assert list((tmp_path / "out").iterdir()) == []


def test_unwritable_folder_says_so(fake_tools, app, monkeypatch, tmp_path):
    _ready(app)
    monkeypatch.setattr(main.filedialog, "asksaveasfilename",
                        lambda **kw: str(tmp_path / "nowhere" / "x.mp3"))
    app.save()
    assert app.state == main.ERROR
    assert app.status_var.get() == main.render.NOT_WRITABLE


def test_preview_error_shows_details(fake_tools, fake_run, app):
    fake_run.handlers.insert(0, (lambda a: a[-2] == "wav",
                                 lambda a, ol, c: result(a, returncode=1, stderr="ffmpeg exploded")))
    _fetch(app)
    _pump(app, lambda: app.state == main.ERROR)
    app.update()
    assert app.details_link.winfo_ismapped()
    assert "ffmpeg exploded" in app.details
    assert app.save_blocker() == ""                        # the track is still usable
