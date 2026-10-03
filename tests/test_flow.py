"""Drive the main window headlessly: a real tk.Tk(), the real engine
modules, and only the subprocess layer (proc.run) faked. No network."""

import json
import time
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
    """Fake yt-dlp and ffmpeg behind proc.run. Set ``hold_download`` or
    ``hold_save`` to make that step wait until cancelled."""

    def __init__(self, fake_run, video_json):
        self.video_json = video_json
        self.hold_download = False
        self.hold_save = False
        self.save_argv: list[str] | None = None
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


def test_save_disabled_until_a_key_is_chosen(fake_tools, app):
    _fetch(app)
    assert app.state == main.READY
    assert app.title_var.get() == "Me at the zoo"
    assert app.meta_var.get() == "jawed · 19.0 s"
    assert str(app.key_box.cget("state")) == "readonly"
    assert app.save_blocker() == "pick a key first"
    assert "pick a key first" in app.save_btn.cget("text")
    _pick(app, "B-flat")
    assert app.save_blocker() == ""
    assert app.save_btn.cget("text") == "Save MP3…"


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
    assert "-af" not in argv                      # M2 saves the whole track, no fades
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
    assert app.key_var.get() == main.KEY_PLACEHOLDER
    assert app.save_blocker() == "pick a key first"


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
    assert app.cancel_link.winfo_ismapped()
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
    assert "unavailable" in app.status_var.get()
    assert app.details_link.winfo_ismapped()
    app.toggle_details()
    app.update()
    assert app.details_box.winfo_ismapped()
    assert "This video is unavailable" in app.details_box.get("1.0", "end")
    app.toggle_details()
    app.update()
    assert not app.details_box.winfo_ismapped()
    assert "This video is unavailable" in settings.LOG_PATH.read_text()


def test_download_failure_suggests_updating_ytdlp(fake_tools, fake_run, app):
    fake_run.handlers.insert(0, (lambda a: "--progress-template" in a,
                                 lambda a, ol, c: result(a, returncode=1, stderr="ERROR: 403")))
    _fetch(app)
    assert app.state == main.ERROR
    assert "brew upgrade yt-dlp" in app.status_var.get()
    assert app.save_blocker() == "fetch a video first"


def test_missing_tools_are_reported_on_launch(monkeypatch, fake_run):
    monkeypatch.setattr(tools, "locate", lambda: tools.Toolset(
        paths={"yt-dlp": None, "ffmpeg": "/x", "ffprobe": "/x", "deno": "/x"},
        brew="/x/brew", missing=["yt-dlp"]))
    a = main.App()
    try:
        assert a.state == main.ERROR
        assert "brew install yt-dlp" in a.status_var.get()
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
