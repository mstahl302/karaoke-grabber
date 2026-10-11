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
    assert transpose.rubberband_argv("rubberband", Path("in.wav"), Path("o.flac"), 2, 75) == [
        "rubberband", "-p", "2", "-T", "0.75", "in.wav", "o.flac"]
    assert transpose.rubberband_argv("rubberband", Path("i.wav"), Path("o.flac"), 0, 150)[3:5] == [
        "-T", "1.5"]
    c = transpose.convert_argv("ffmpeg", Path("/t/s.flac"), Path("/c/x.part.flac"))
    assert c[c.index("-sample_fmt") + 1] == "s16"
    assert c[-3:] == ["-f", "flac", "/c/x.part.flac"]


def test_paths_and_speed_helpers():
    assert cache.processed_audio("abc", 2).name == "shift2-speed100.flac"
    assert cache.processed_audio("abc", -3, 75).name == "shift-3-speed75.flac"
    assert transpose.part_path(Path("/c/shift2-speed75.flac")) == Path("/c/shift2-speed75.part.flac")
    assert transpose.clamp_speed(20) == 50 and transpose.clamp_speed(200) == 150
    assert transpose.clamp_speed(85) == 85
    assert transpose.is_plain(0, 100) and not transpose.is_plain(0, 75)


def _tools(fake_run, rb_lines=("50%", "100%"), decode_rc=0, rb_rc=0, convert_rc=0,
           rb_cancelled=False):
    def ffmpeg(argv, on_line, cancel):
        if "-sample_fmt" in argv:                     # the 16-bit conversion
            Path(argv[-1]).write_bytes(b"fLaC16")
            on_line("out_time_us=200000000")
            return result(argv, returncode=convert_rc, stderr="convert broke" if convert_rc else "")
        Path(argv[-1]).write_bytes(b"RIFF")
        on_line("out_time_us=100000000")
        return result(argv, returncode=decode_rc, stderr="bad input" if decode_rc else "")

    def rb(argv, on_line, cancel):
        Path(argv[-1]).write_bytes(b"fLaC24")
        for line in rb_lines:
            on_line(line)
        return result(argv, returncode=rb_rc, cancelled=rb_cancelled,
                      stdout="rubberband: failed" if rb_rc else "")

    fake_run.on(lambda a: a[0] == "ffmpeg", ffmpeg)
    fake_run.on(lambda a: a[0] == "rubberband", rb)


def test_transpose_writes_the_16_bit_copy(fake_run, tmp_path):
    _tools(fake_run)
    dest = tmp_path / "vid" / "shift2-speed100.flac"
    seen = []
    out = transpose.transpose("ffmpeg", "rubberband", tmp_path / "audio.webm", 2, dest,
                              duration=200, on_fraction=seen.append, tmp_dir=tmp_path)
    assert out == dest and dest.read_bytes() == b"fLaC16"
    assert seen == pytest.approx([0.0, 0.05, 0.525, 0.95, 1.0, 1.0])
    decode, rb, convert = fake_run.calls
    assert rb[:3] == ["rubberband", "-p", "2"] and "-T" not in rb
    assert fake_run.merged == [rb]                    # rubberband's progress comes on stderr
    assert convert[convert.index("-i") + 1] == rb[-1]
    assert convert[-1] == str(transpose.part_path(dest))
    # the temporary WAV, the 24-bit file and the part file are gone
    assert not Path(decode[-1]).exists() and not Path(rb[-1]).exists()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["shift2-speed100.flac"]


def test_speed_stretches_the_copy_and_its_progress(fake_run, tmp_path):
    _tools(fake_run)
    dest = tmp_path / "shift0-speed50.flac"
    seen = []
    transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 0, dest, duration=200,
                        on_fraction=seen.append, tmp_dir=tmp_path, speed=50)
    rb = fake_run.calls[1]
    assert rb[1:5] == ["-p", "0", "-T", "0.5"]
    # the converted copy is 400 s long, so 200 s converted is half of the last 5%
    assert seen[-2] == pytest.approx(0.975)


def test_only_the_latest_copy_is_kept(fake_run, tmp_path):
    _tools(fake_run)
    d = tmp_path / "vid"
    d.mkdir()
    (d / "audio.webm").write_bytes(b"x")
    (d / "shift-1-speed100.flac").write_bytes(b"old")
    (d / "shift0-speed75.flac").write_bytes(b"old")
    transpose.transpose("ffmpeg", "rubberband", d / "audio.webm", 3, d / "shift3-speed90.flac",
                        duration=10, tmp_dir=tmp_path, speed=90)
    assert sorted(p.name for p in d.iterdir()) == ["audio.webm", "shift3-speed90.flac"]


def test_cached_copy_is_reused(fake_run, tmp_path):
    dest = tmp_path / "shift2-speed100.flac"
    dest.write_bytes(b"fLaC")
    assert transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 2, dest,
                               duration=10) == dest
    assert fake_run.calls == []


def test_cancel_leaves_nothing_behind(fake_run, tmp_path):
    _tools(fake_run, rb_cancelled=True, rb_rc=-15)
    work = tmp_path / "tmp"
    work.mkdir()
    dest = tmp_path / "vid" / "shift2-speed100.flac"
    assert transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 2, dest,
                               duration=10, tmp_dir=work) is None
    assert not dest.exists()
    assert list(work.iterdir()) == []


@pytest.mark.parametrize("which, text", [("decode", "bad input"),
                                         ("rubberband", "rubberband: failed"),
                                         ("convert", "convert broke")])
def test_failure_raises_with_details_and_cleans_up(fake_run, tmp_path, which, text):
    _tools(fake_run, decode_rc=int(which == "decode"), rb_rc=int(which == "rubberband"),
           convert_rc=int(which == "convert"))
    work = tmp_path / "tmp"
    work.mkdir()
    dest = tmp_path / "vid" / "shift2-speed100.flac"
    with pytest.raises(transpose.TransposeError) as e:
        transpose.transpose("ffmpeg", "rubberband", tmp_path / "a.webm", 2, dest,
                            duration=10, tmp_dir=work)
    assert e.value.message == transpose.FAILED
    assert text in e.value.details
    assert not dest.exists()
    assert list(work.iterdir()) == []
    if dest.parent.exists():
        assert list(dest.parent.iterdir()) == []
