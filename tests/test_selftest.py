import io
import json
from pathlib import Path

from karaokegrab import selftest, tools
from conftest import result


def test_self_test_runs_lookup_download_and_save(monkeypatch, fake_run, video_json):
    monkeypatch.setattr(tools, "locate", lambda: tools.Toolset(
        paths={n: f"/opt/homebrew/bin/{n}" for n in tools.TOOLS}, brew="/opt/homebrew/bin/brew"))

    def download(argv, on_line, cancel):
        (Path(argv[argv.index("-o") + 1]).parent / "audio.webm").write_bytes(b"opus")
        return result(argv)

    def ffmpeg(argv, on_line, cancel):
        Path(argv[-1]).write_bytes(b"mp3")
        return result(argv)

    fake_run.on(lambda a: "-J" in a, lambda a, ol, c: result(a, stdout=json.dumps(video_json)))
    fake_run.on(lambda a: "--progress-template" in a, download)
    def rubberband(argv, on_line, cancel):
        Path(argv[-1]).write_bytes(b"fLaC")
        return result(argv)

    fake_run.on(lambda a: a[0].endswith("ffmpeg"), ffmpeg)
    fake_run.on(lambda a: a[0].endswith("rubberband"), rubberband)
    out = io.StringIO()
    assert selftest.run(out=out) == 0
    text = out.getvalue()
    assert "lookup ok" in text and "download ok" in text and "save ok" in text
    assert "transpose ok" in text
    save = fake_run.calls[-1]
    assert save[save.index("-i") + 1].endswith("shift2.flac")
    assert text.rstrip().endswith("self-test passed")


def test_self_test_reports_missing_tools(monkeypatch, fake_run):
    monkeypatch.setattr(tools, "locate", lambda: tools.Toolset(
        paths={"yt-dlp": None, "ffmpeg": "/x", "ffprobe": "/x", "deno": "/x"},
        brew="/x/brew", missing=["yt-dlp"]))
    out = io.StringIO()
    assert selftest.run(out=out) == 1
    assert "brew install yt-dlp" in out.getvalue()
    assert fake_run.calls == []
