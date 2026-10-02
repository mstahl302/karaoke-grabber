from pathlib import Path

import pytest

from karaokegrab import cache, download
from conftest import result


@pytest.mark.parametrize("line, expected", [
    ("PROG|1024|4096|NA|3", download.Progress(1024, 4096, 3.0)),
    ("PROG|1024|NA|8000.5|NA", download.Progress(1024, 8000, None)),
    ("PROG|1024|NA|NA|NA", download.Progress(1024, None, None)),
    ("PROG|NA|NA|NA|NA", None),
    ("PROG|1|2|3", None),
    ("[download] Destination: audio.webm", None),
    ("", None),
])
def test_parse_progress(line, expected):
    assert download.parse_progress(line) == expected


def test_fraction():
    assert download.Progress(50, 200, None).fraction == 0.25
    assert download.Progress(300, 200, None).fraction == 1.0
    assert download.Progress(50, None, None).fraction is None


def test_argv_uses_saved_info_json(tmp_path):
    argv = download.download_argv("yt-dlp", "abc", tmp_path / "info.json", root=tmp_path)
    assert argv[-2:] == ["--load-info-json", str(tmp_path / "info.json")]
    assert argv[argv.index("-o") + 1] == str(tmp_path / "abc" / "audio.%(ext)s")
    assert argv[argv.index("--progress-template") + 1] == download.PROGRESS_TEMPLATE
    assert "--newline" in argv
    # a URL source is passed through as is
    assert download.download_argv("yt-dlp", "abc", "https://youtu.be/abc", root=tmp_path)[-1] \
        == "https://youtu.be/abc"


def _ytdlp_writing(names, lines=(), returncode=0, cancelled=False):
    def action(argv, on_line, cancel):
        out = Path(argv[argv.index("-o") + 1]).parent
        for n in names:
            (out / n).write_bytes(b"audio")
        for line in lines:
            on_line(line)
        return result(argv, returncode=returncode, cancelled=cancelled,
                      stderr="ERROR: boom" if returncode else "")
    return action


def test_download_reports_progress_and_returns_audio(fake_run):
    fake_run.on(lambda a: True, _ytdlp_writing(
        ["audio.webm"], ["[info] x", "PROG|50|100|NA|1", "PROG|100|100|NA|0"]))
    seen = []
    path = download.download("yt-dlp", "abc", "https://youtu.be/abc", on_progress=seen.append)
    assert path == cache.video_dir("abc") / "audio.webm"
    assert [p.fraction for p in seen] == [0.5, 1.0]


def test_cached_audio_is_reused_without_ytdlp(fake_run):
    d = cache.video_dir("abc")
    d.mkdir(parents=True)
    (d / "audio.m4a").write_bytes(b"audio")
    assert download.download("yt-dlp", "abc", "https://youtu.be/abc") == d / "audio.m4a"
    assert fake_run.calls == []


def test_cancel_deletes_partial_files(fake_run):
    fake_run.on(lambda a: True, _ytdlp_writing(
        ["audio.webm.part", "audio.webm.ytdl"], ["PROG|10|100|NA|9"], returncode=-15, cancelled=True))
    assert download.download("yt-dlp", "abc", "https://youtu.be/abc") is None
    assert list(cache.video_dir("abc").iterdir()) == []


def test_failure_cleans_up_and_suggests_upgrade(fake_run):
    fake_run.on(lambda a: True, _ytdlp_writing(["audio.webm.part"], returncode=1))
    with pytest.raises(download.DownloadError) as e:
        download.download("yt-dlp", "abc", "https://youtu.be/abc")
    assert "brew upgrade yt-dlp" in e.value.message
    assert "ERROR: boom" in e.value.details
    assert list(cache.video_dir("abc").iterdir()) == []
