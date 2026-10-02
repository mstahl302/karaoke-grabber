"""python -m karaokegrab end to end, with every subprocess mocked."""

import io
import json
from pathlib import Path

import pytest

from karaokegrab import __main__ as cli
from karaokegrab import cache, settings, tools
from conftest import result

URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@pytest.fixture
def all_tools(monkeypatch):
    found = tools.Toolset(paths={n: f"/opt/homebrew/bin/{n}" for n in tools.TOOLS},
                          brew="/opt/homebrew/bin/brew")
    monkeypatch.setattr(tools, "locate", lambda: found)
    return found


@pytest.fixture
def fake_tools(fake_run, video_json):
    """yt-dlp and ffmpeg as the pipeline calls them."""
    def ytdlp_json(argv, on_line, cancel):
        return result(argv, stdout=json.dumps(video_json))

    def ytdlp_download(argv, on_line, cancel):
        out = Path(argv[argv.index("-o") + 1]).parent
        on_line("PROG|100|200|NA|1")
        on_line("PROG|200|200|NA|0")
        (out / "audio.webm").write_bytes(b"opus")
        return result(argv)

    def ytdlp_thumb(argv, on_line, cancel):
        Path(argv[argv.index("-o") + 1].replace(".%(ext)s", ".png")).write_bytes(b"png")
        return result(argv)

    def ffmpeg(argv, on_line, cancel):
        on_line("out_time_us=7000000")
        on_line("progress=end")
        Path(argv[-1]).write_bytes(b"mp3")
        return result(argv)

    fake_run.on(lambda a: "-J" in a, ytdlp_json)
    fake_run.on(lambda a: "--write-thumbnail" in a, ytdlp_thumb)
    fake_run.on(lambda a: "--progress-template" in a, ytdlp_download)
    fake_run.on(lambda a: a[0].endswith("ffmpeg"), ffmpeg)
    return fake_run


def _main(*args):
    out = io.StringIO()
    code = cli.main(list(args), stream=out)
    return code, out.getvalue()


def test_url_to_trimmed_named_mp3(all_tools, fake_tools, tmp_path):
    code, text = _main(URL, "--key", "b-flat", "--title", "Zoo Song",
                       "--start", "2", "--end", "16", "--fade-out", "2", "--out", str(tmp_path))
    assert code == cli.EXIT_OK, text
    saved = tmp_path / "Zoo Song - AUDIO - B-flat.mp3"
    assert saved.read_bytes() == b"mp3"
    assert f"Saved: {saved}" in text
    assert "Downloading 100%" in text

    kinds = [("-J" in c) and "info" or ("--write-thumbnail" in c) and "thumb"
             or ("--progress-template" in c) and "download" or "ffmpeg" for c in fake_tools.calls]
    assert kinds == ["info", "download", "thumb", "ffmpeg"]
    ff = fake_tools.calls[-1]
    assert ff[ff.index("-ss") + 1] == "2" and ff[ff.index("-t") + 1] == "14"
    assert ff[ff.index("-af") + 1] == "afade=t=out:st=12:d=2"
    assert (cache.video_dir("jNQXAC9IVRw") / "thumb.png").exists()
    assert settings.load()["last_save_folder"] == str(tmp_path.resolve())
    assert "saved" in settings.LOG_PATH.read_text()


def test_second_run_reuses_the_download_and_the_folder(all_tools, fake_tools, tmp_path, monkeypatch):
    assert _main(URL, "--key", "C", "--out", str(tmp_path))[0] == cli.EXIT_OK
    fake_tools.calls.clear()
    monkeypatch.chdir(tmp_path.parent)          # not the save folder
    code, text = _main(URL, "--key", "D", "--start", "5")
    assert code == cli.EXIT_OK, text
    assert "Using the cached download." in text
    assert not any("--progress-template" in c for c in fake_tools.calls)
    assert (tmp_path / "Me at the zoo - AUDIO - D.mp3").exists()


def test_title_defaults_to_youtube_title_and_existing_file_is_kept(all_tools, fake_tools, tmp_path):
    existing = tmp_path / "Me at the zoo - AUDIO - C.mp3"
    existing.write_bytes(b"keep me")
    code, text = _main(URL, "--key", "C", "--out", str(tmp_path))
    assert code == cli.EXIT_USAGE
    assert "already exists" in text
    assert existing.read_bytes() == b"keep me"
    assert _main(URL, "--key", "C", "--out", str(tmp_path), "--overwrite")[0] == cli.EXIT_OK
    assert existing.read_bytes() == b"mp3"


def test_trim_outside_the_track_is_adjusted(all_tools, fake_tools, tmp_path):
    code, text = _main(URL, "--key", "C", "--end", "500", "--out", str(tmp_path))
    assert code == cli.EXIT_OK
    assert "adjusted to fit" in text
    ff = fake_tools.calls[-1]
    assert ff[ff.index("-t") + 1] == "19"


def test_missing_tools_say_what_to_run(monkeypatch, fake_run):
    monkeypatch.setattr(tools, "locate", lambda: tools.Toolset(
        paths={"yt-dlp": "/x/yt-dlp", "ffmpeg": None, "ffprobe": None, "deno": "/x/deno"},
        brew="/x/brew", missing=["ffmpeg", "ffprobe"]))
    code, text = _main(URL, "--key", "C")
    assert code == cli.EXIT_USAGE
    assert "brew install ffmpeg" in text
    assert fake_run.calls == []


def test_fetch_error_is_friendly_and_logged(all_tools, fake_run):
    fake_run.on(lambda a: True, lambda a, ol, c: result(
        a, returncode=1, stderr="ERROR: [youtube] x: This video is unavailable"))
    code, text = _main(URL, "--key", "C")
    assert code == cli.EXIT_ERROR
    assert "Error: That video is unavailable" in text
    assert "This video is unavailable" in settings.LOG_PATH.read_text()


def test_bad_key_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([URL, "--key", "H"])
    assert e.value.code == 2
    assert "isn't a key" in capsys.readouterr().err


def test_cancel_reports_cancelled(monkeypatch):
    code = cli.main([URL, "--key", "C"], stream=io.StringIO(), runner=lambda a, o, c: None)
    assert code == cli.EXIT_CANCELLED
