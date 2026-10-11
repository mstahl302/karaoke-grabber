from pathlib import Path

import pytest

from karaokegrab import cache, transpose
from conftest import result


@pytest.mark.parametrize("line, fraction", [
    ("42%", 0.42),
    ("  7% ", 0.07),
    ("100%", 1.0),
    ("Using R2 (faster) engine", None),
    ("in: 14033398, out: 14033398, ratio: 1", None),
    ("", None),
])
def test_parse_percent(line, fraction):
    assert transpose.parse_percent(line) == fraction


def test_argv():
    d = transpose.decode_argv("ffmpeg", Path("/c/audio.webm"), Path("/t/x.wav"))
    assert d[0] == "ffmpeg"
    assert d[d.index("-i") + 1] == "/c/audio.webm"
    assert d[d.index("-ar") + 1] == "48000"
    assert d[d.index("-ac") + 1] == "2"
    assert d[-1] == "/t/x.wav"
    assert transpose.rubberband_argv("rubberband", Path("in.wav"), Path("o.flac"), -3) == [
        "rubberband", "-p", "-3", "in.wav", "o.flac"]


def test_paths():
    assert cache.shifted_audio("abc", 2).name == "shift2.flac"
    assert cache.shifted_audio("abc", -3).name == "shift-3.flac"
    assert transpose.part_path(Path("/c/shift2.flac")) == Path("/c/shift2.part.flac")


def _tools(fake_run, decode_lines=(), rb_lines=("50%", "100%"), decode_rc=0, rb_rc=0,
           rb_cancelled=False):
    def decode(argv, on_line, cancel):
        Path(argv[-1]).write_bytes(b"RIFF")
        for line in decode_lines:
            on_line(line)
        return result(argv, returncode=decode_rc, stderr="bad input" if decode_rc else "")

    def rb(argv, on_line, cancel):
        Path(argv[-1]).write_bytes(b"fLaC")
        for line in rb_lines:
            on_line(line)
        return result(argv, returncode=rb_rc, cancelled=rb_cancelled,
                      stdout="rubberband: failed" if rb_rc else "")

    fake_run.on(lambda a: a[0] == "ffmpeg", decode)
    fake_run.on(lambda a: a[0] == "rubberband", rb)


def test_transpose_writes_the_shifted_copy(fake_run, tmp_path):
    _tools(fake_run, decode_lines=["out_time_us=100000000"])
    dest = tmp_path / "vid" / "shift2.flac"
    seen = []
    out = transpose.transpose("ffmpeg", "rubberband", tmp_path / "audio.webm", 2, dest,
                              duration=200, on_fraction=seen.append, tmp_dir=tmp_path)
    assert out == dest and dest.read_bytes() == b"fLaC"
    assert seen == [0.0, 0.05, 0.55, 1.0, 1.0]
    rb_argv = fake_run.calls[1]
    assert rb_argv[:3] == ["rubberband", "-p", "2"]
    assert rb_argv[-1] == str(transpose.part_path(dest))
    assert fake_run.merged == [rb_argv]                 # progress comes on stderr
    # the temporary WAV and the part file are gone
    assert not Path(rb_argv[3]).exists()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["shift2.flac"]


def test_only_the_latest_shift_is_kept(fake_run, tmp_path):
    _tools(fake_run)
    d = tmp_path / "vid"
    d.mkdir()
    (d / "audio.webm").write_bytes(b"x")
    (d / "shift-1.flac").write_bytes(b"old")
    transpose.transpose("ffmpeg", "rubberband", d / "audio.webm", 3, d / "shift3.flac",
                        duration=10, tmp_dir=tmp_path)
    assert sorted(p.name for p in d.iterdir()) == ["audio.webm", "shift3.flac"]


def test_cached_shift_is_reused(fake_run, tmp_path):
    dest = tmp_path / "shift2.flac"
    dest.write_bytes(b"fLaC")
    assert transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 2, dest,
                               duration=10) == dest
    assert fake_run.calls == []


def test_cancel_leaves_nothing_behind(fake_run, tmp_path):
    _tools(fake_run, rb_cancelled=True, rb_rc=-15)
    work = tmp_path / "tmp"
    work.mkdir()
    dest = tmp_path / "vid" / "shift2.flac"
    assert transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 2, dest,
                               duration=10, tmp_dir=work) is None
    assert not dest.exists()
    assert list(work.iterdir()) == []
    assert list(dest.parent.iterdir()) == []


@pytest.mark.parametrize("which", ["decode", "rubberband"])
def test_failure_raises_with_details_and_cleans_up(fake_run, tmp_path, which):
    if which == "decode":
        _tools(fake_run, decode_rc=1)
    else:
        _tools(fake_run, rb_rc=1)
    work = tmp_path / "tmp"
    work.mkdir()
    dest = tmp_path / "vid" / "shift2.flac"
    with pytest.raises(transpose.TransposeError) as e:
        transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 2, dest,
                            duration=10, tmp_dir=work)
    assert e.value.message == transpose.FAILED
    assert ("bad input" if which == "decode" else "rubberband: failed") in e.value.details
    assert not dest.exists()
    assert list(work.iterdir()) == []
