"""Trim and fade settings → ffmpeg command lines (pure; no subprocess here).

All times are seconds. ``start``/``end`` are positions in the source track;
``fade_in``/``fade_out`` are lengths relative to the trimmed range, so the
fade-out starts at ``length - fade_out`` in the output.

The final MP3 and every preview use the same fades, so the saved file
matches what the preview played. A preview seeks straight to the cursor
and keeps the source timestamps (``-copyts``), so its fades are placed at
their absolute times in the track: the clip is sample-for-sample the
matching part of the final render, and starting late in a long track
costs almost nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MIN_LENGTH = 1.0      # shortest trimmed range, seconds
PREVIEW_TAIL = 10.0   # "From end" plays this many seconds before the trim end


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _num(x: float) -> str:
    """ffmpeg-friendly number: millisecond precision, no trailing zeros."""
    text = f"{x:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


@dataclass(frozen=True)
class TrimSpec:
    start: float = 0.0
    end: float | None = None   # None = to the end of the track
    fade_in: float = 0.0
    fade_out: float = 0.0

    @property
    def length(self) -> float:
        if self.end is None:
            raise ValueError("call clamped(duration) first")
        return self.end - self.start

    @property
    def fade_out_start(self) -> float:
        """Where the fade-out begins, in output time."""
        return self.length - self.fade_out

    def clamped(self, duration: float) -> TrimSpec:
        """A valid spec for a track of *duration* seconds: inside the track,
        End at least MIN_LENGTH after Start, fades never negative and never
        overlapping (the fade-in keeps priority)."""
        duration = max(0.0, duration)
        min_len = min(MIN_LENGTH, duration)
        start = _clamp(self.start, 0.0, duration - min_len)
        end = duration if self.end is None else self.end
        end = _clamp(end, start + min_len, duration)
        length = end - start
        fade_in = _clamp(self.fade_in, 0.0, length)
        fade_out = _clamp(self.fade_out, 0.0, length - fade_in)
        return TrimSpec(start, end, fade_in, fade_out)


def filter_chain(spec: TrimSpec) -> str:
    """The ``-af`` value for *spec* (already clamped); '' when there are no fades."""
    parts = []
    if spec.fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={_num(spec.fade_in)}")
    if spec.fade_out > 0:
        parts.append(f"afade=t=out:st={_num(spec.fade_out_start)}:d={_num(spec.fade_out)}")
    return ",".join(parts)


def _common(ffmpeg: str, source: Path, spec: TrimSpec) -> list[str]:
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y",
            "-ss", _num(spec.start), "-t", _num(spec.length), "-i", str(source),
            "-map", "0:a:0", "-vn"]
    chain = filter_chain(spec)
    if chain:
        argv += ["-af", chain]
    return argv


def mp3_argv(ffmpeg: str, source: Path, spec: TrimSpec, out: Path) -> list[str]:
    """Final save: best VBR MP3 (V0). *out* is the ``.part`` path; ``-f mp3``
    because ffmpeg can't guess the format from that suffix."""
    return _common(ffmpeg, source, spec) + [
        "-c:a", "libmp3lame", "-q:a", "0",
        "-progress", "pipe:1", "-f", "mp3", str(out)]


def preview_offset(spec: TrimSpec, cursor: float) -> float:
    """Cursor position (source time) → offset into the trimmed output."""
    return _clamp(cursor - spec.start, 0.0, max(0.0, spec.length - 0.1))


def from_end_cursor(spec: TrimSpec) -> float:
    """The cursor for "From end": PREVIEW_TAIL seconds before the trim end."""
    return max(spec.start, spec.end - PREVIEW_TAIL)


def absolute_filter_chain(spec: TrimSpec) -> str:
    """The fades of *spec* placed at source-track times (for ``-copyts``)."""
    parts = []
    if spec.fade_in > 0:
        parts.append(f"afade=t=in:st={_num(spec.start)}:d={_num(spec.fade_in)}")
    if spec.fade_out > 0:
        parts.append(f"afade=t=out:st={_num(spec.end - spec.fade_out)}:d={_num(spec.fade_out)}")
    return ",".join(parts)


def preview_argv(ffmpeg: str, source: Path, spec: TrimSpec, cursor: float,
                 out: Path) -> list[str]:
    """A WAV from *cursor* (source time) to the trim end, for afplay."""
    at = spec.start + preview_offset(spec, cursor)
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y",
            "-copyts", "-ss", _num(at), "-t", _num(spec.end - at), "-i", str(source),
            "-map", "0:a:0", "-vn"]
    chain = absolute_filter_chain(spec)
    if chain:
        argv += ["-af", chain]
    return argv + ["-c:a", "pcm_s16le", "-progress", "pipe:1", "-f", "wav", str(out)]
