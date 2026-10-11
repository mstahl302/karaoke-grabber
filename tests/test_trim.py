from pathlib import Path

import pytest

from karaokegrab import trim
from karaokegrab.trim import TrimSpec

SRC = Path("/cache/abc/audio.webm")


# --- clamping ---------------------------------------------------------------

def test_end_defaults_to_track_end():
    assert TrimSpec(4.5).clamped(300) == TrimSpec(4.5, 300, 0, 0)


def test_values_stay_inside_the_track():
    assert TrimSpec(-3, 999).clamped(200) == TrimSpec(0, 200, 0, 0)


def test_end_stays_at_least_min_length_after_start():
    s = TrimSpec(100, 50).clamped(200)
    assert (s.start, s.end) == (100, 100 + trim.MIN_LENGTH)
    s = TrimSpec(199.9, None).clamped(200)
    assert (s.start, s.end) == (200 - trim.MIN_LENGTH, 200)


def test_fades_never_overlap_and_fade_in_keeps_priority():
    s = TrimSpec(10, 20, fade_in=7, fade_out=7).clamped(100)
    assert (s.fade_in, s.fade_out) == (7, 3)
    s = TrimSpec(10, 20, fade_in=50, fade_out=5).clamped(100)
    assert (s.fade_in, s.fade_out) == (10, 0)
    s = TrimSpec(0, 10, fade_in=-1, fade_out=-2).clamped(100)
    assert (s.fade_in, s.fade_out) == (0, 0)


def test_track_shorter_than_min_length():
    assert TrimSpec(0.2, 5).clamped(0.5) == TrimSpec(0, 0.5, 0, 0)


def test_fade_out_start_math():
    s = TrimSpec(4.5, 339, fade_in=1, fade_out=2).clamped(400)
    assert s.length == pytest.approx(334.5)
    assert s.fade_out_start == pytest.approx(332.5)


def test_length_needs_an_end():
    with pytest.raises(ValueError):
        TrimSpec(1).length


# --- filters and argv -------------------------------------------------------

def test_filter_chain():
    assert trim.filter_chain(TrimSpec(0, 10)) == ""
    assert trim.filter_chain(TrimSpec(0, 10, fade_in=1.5)) == "afade=t=in:st=0:d=1.5"
    assert trim.filter_chain(TrimSpec(4.5, 339, 0, 2)) == "afade=t=out:st=332.5:d=2"
    assert trim.filter_chain(TrimSpec(4.5, 339, 1, 2)) == \
        "afade=t=in:st=0:d=1,afade=t=out:st=332.5:d=2"


def test_mp3_argv_snapshot():
    spec = TrimSpec(4.5, 339, 1, 2)
    assert trim.mp3_argv("ffmpeg", SRC, spec, Path("/out/Song - AUDIO - C.mp3.part")) == [
        "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y",
        "-ss", "4.5", "-t", "334.5", "-i", "/cache/abc/audio.webm",
        "-map", "0:a:0", "-vn",
        "-af", "afade=t=in:st=0:d=1,afade=t=out:st=332.5:d=2",
        "-c:a", "libmp3lame", "-q:a", "0",
        "-progress", "pipe:1", "-f", "mp3", "/out/Song - AUDIO - C.mp3.part",
    ]


def test_mp3_argv_without_fades_has_no_filter():
    argv = trim.mp3_argv("ffmpeg", SRC, TrimSpec(0, 180), Path("o.part"))
    assert "-af" not in argv
    assert argv[argv.index("-ss") + 1] == "0"
    assert argv[argv.index("-t") + 1] == "180"


def test_absolute_filter_chain():
    assert trim.absolute_filter_chain(TrimSpec(10, 70)) == ""
    assert trim.absolute_filter_chain(TrimSpec(10, 70, 2, 3)) == \
        "afade=t=in:st=10:d=2,afade=t=out:st=67:d=3"


def test_preview_argv_snapshot():
    spec = TrimSpec(10, 70, 2, 3)
    assert trim.preview_argv("ffmpeg", SRC, spec, cursor=40.25, out=Path("/tmp/p.wav.part")) == [
        "ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y",
        "-copyts", "-ss", "40.25", "-t", "29.75", "-i", "/cache/abc/audio.webm",
        "-map", "0:a:0", "-vn",
        "-af", "afade=t=in:st=10:d=2,afade=t=out:st=67:d=3",
        "-c:a", "pcm_s16le", "-progress", "pipe:1", "-f", "wav", "/tmp/p.wav.part",
    ]


def test_preview_cursor_outside_the_trim_is_clamped():
    spec = TrimSpec(10, 70)
    before = trim.preview_argv("ffmpeg", SRC, spec, cursor=0, out=Path("p.wav"))
    assert before[before.index("-ss") + 1] == "10" and before[before.index("-t") + 1] == "60"
    after = trim.preview_argv("ffmpeg", SRC, spec, cursor=500, out=Path("p.wav"))
    assert after[after.index("-ss") + 1] == "69.9"


def test_preview_offset_is_clamped_to_the_trim():
    spec = TrimSpec(10, 70)
    assert trim.preview_offset(spec, 0) == 0
    assert trim.preview_offset(spec, 500) == pytest.approx(59.9)


def test_from_end_cursor():
    assert trim.from_end_cursor(TrimSpec(10, 70)) == 60
    assert trim.from_end_cursor(TrimSpec(10, 15)) == 10


# --- speed (F18): the song's timeline mapped onto the processed copy --------

@pytest.mark.parametrize("speed", [50, 75, 100, 150])
def test_scaled_spec_maps_the_song_onto_the_copy(speed):
    k = 100 / speed
    spec = TrimSpec(10, 110, 2, 6).clamped(200)
    copy = spec.scaled(k)
    assert copy.start == pytest.approx(10 * k) and copy.end == pytest.approx(110 * k)
    assert copy.length == pytest.approx(100 * k)
    assert copy.fade_in == pytest.approx(2 * k) and copy.fade_out == pytest.approx(6 * k)
    assert copy.clamped(200 * k) == copy          # still valid on the copy
    assert copy.fade_in + copy.fade_out <= copy.length


def test_from_end_on_the_copy_is_the_last_ten_seconds_heard():
    copy = TrimSpec(10, 110, 0, 0).scaled(2)      # 50%: the copy runs 20 s → 220 s
    assert trim.from_end_cursor(copy) == pytest.approx(210)
    assert trim.from_end_cursor(copy) / 2 == pytest.approx(105)     # 5 s before the end in the song


def test_scaled_keeps_an_open_end():
    assert TrimSpec(1, None).scaled(2).end is None
