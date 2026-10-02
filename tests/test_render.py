from pathlib import Path

import pytest

from karaokegrab import render
from karaokegrab.trim import TrimSpec
from conftest import result

SPEC = TrimSpec(10, 110, 0, 2)   # 100 s trimmed


@pytest.mark.parametrize("line, seconds", [
    ("out_time_us=25000000", 25.0),
    ("out_time_ms=1500000", 1.5),     # also microseconds, despite the name
    ("out_time_us=N/A", None),
    ("out_time=00:00:25.000000", None),
    ("progress=continue", None),
    ("garbage", None),
])
def test_parse_out_time(line, seconds):
    assert render.parse_out_time(line) == seconds


def test_part_path():
    assert render.part_path(Path("/o/Song - AUDIO - C.mp3")) == Path("/o/Song - AUDIO - C.mp3.part")


def _ffmpeg(lines=(), returncode=0, cancelled=False, write=True):
    def action(argv, on_line, cancel):
        if write:
            Path(argv[-1]).write_bytes(b"mp3")
        for line in lines:
            on_line(line)
        return result(argv, returncode=returncode, cancelled=cancelled,
                      stderr="Error opening input" if returncode else "")
    return action


def test_render_writes_part_then_renames(fake_run, tmp_path):
    out = tmp_path / "Song - AUDIO - C.mp3"
    fake_run.on(lambda a: True, _ffmpeg(["out_time_us=50000000", "progress=continue",
                                         "out_time_us=100000000", "progress=end"]))
    seen = []
    assert render.render_mp3("ffmpeg", tmp_path / "a.webm", SPEC, out, on_fraction=seen.append) == out
    assert fake_run.calls[0][-1] == str(out) + ".part"
    assert out.read_bytes() == b"mp3"
    assert not render.part_path(out).exists()
    assert seen == [0.5, 1.0, 1.0]


def test_cancel_deletes_part_and_leaves_no_file(fake_run, tmp_path):
    out = tmp_path / "Song.mp3"
    fake_run.on(lambda a: True, _ffmpeg(["out_time_us=1000000"], returncode=-15, cancelled=True))
    assert render.render_mp3("ffmpeg", tmp_path / "a.webm", SPEC, out) is None
    assert list(tmp_path.iterdir()) == []


def test_failure_deletes_part_and_keeps_details(fake_run, tmp_path):
    out = tmp_path / "Song.mp3"
    fake_run.on(lambda a: True, _ffmpeg(returncode=1))
    with pytest.raises(render.RenderError) as e:
        render.render_mp3("ffmpeg", tmp_path / "a.webm", SPEC, out)
    assert "Error opening input" in e.value.details
    assert list(tmp_path.iterdir()) == []


def test_existing_file_is_replaced_only_on_success(fake_run, tmp_path):
    out = tmp_path / "Song.mp3"
    out.write_bytes(b"old")
    fake_run.on(lambda a: True, _ffmpeg(returncode=1))
    with pytest.raises(render.RenderError):
        render.render_mp3("ffmpeg", tmp_path / "a.webm", SPEC, out)
    assert out.read_bytes() == b"old"


def test_preview_progress_is_relative_to_the_clip(fake_run, tmp_path):
    out = tmp_path / "p.wav"
    fake_run.on(lambda a: True, _ffmpeg(["out_time_us=5000000"]))
    seen = []
    # cursor 90 s into a 10–110 trim → a 20 s clip
    assert render.render_preview("ffmpeg", tmp_path / "a.webm", SPEC, 90, out,
                                 on_fraction=seen.append) == out
    assert seen == [0.25]
    assert fake_run.calls[0][-3:] == ["-f", "wav", str(out) + ".part"]
