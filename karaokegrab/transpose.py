"""Prepare the cached audio for a shift and a speed: whole semitones up or
down without changing the tempo, and slower or faster without changing the
pitch (product spec F17, F18; architecture §5.3).

Both are slow, so they're done once per setting for the whole track:
ffmpeg decodes the download to a 48 kHz stereo WAV in the temp folder,
``rubberband -p <n> -T <s>`` shifts and stretches it in one pass, and
ffmpeg turns rubberband's 24-bit output into a 16-bit FLAC kept as
``cache/<id>/shift<n>-speed<s>.flac``. Every preview and save then renders
from that copy. Only the latest copy is kept; 0 / 100% uses the download
itself.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable

from karaokegrab import keys, proc, render

FAILED = "Preparing the audio failed. See Details for the tool output."
DECODE_SHARE = 0.10        # the decode is the first 10% of the progress bar,
CONVERT_SHARE = 0.05       # the 16-bit conversion the last 5%, rubberband the rest
SAMPLE_RATE = 48000

MIN_SPEED, MAX_SPEED, SPEED_STEP = 50, 150, 5     # percent

OnFraction = Callable[[float], None]

_PERCENT = re.compile(r"^\s*(\d{1,3})%\s*$")


class TransposeError(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def clamp_speed(speed: int) -> int:
    return max(MIN_SPEED, min(MAX_SPEED, speed))


def is_plain(shift: int, speed: int) -> bool:
    """True when there's nothing to prepare: the download is the source."""
    return shift == 0 and speed == 100


def progress_label(shift: int, speed: int) -> str:
    """What's being made: "Transposing +2", "Changing the speed to 75%",
    or "Preparing +2 at 75%"."""
    if speed == 100:
        return f"Transposing {keys.shift_label(shift)}"
    if shift == 0:
        return f"Changing the speed to {speed}%"
    return f"Preparing {keys.shift_label(shift)} at {speed}%"


def decode_argv(ffmpeg: str, source: Path, wav: Path) -> list[str]:
    """The download → a 16-bit 48 kHz stereo WAV for rubberband."""
    return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source), "-vn",
            "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s16le",
            "-progress", "pipe:1", "-nostats", str(wav)]


def rubberband_argv(rubberband: str, wav: Path, out: Path, shift: int,
                    speed: int = 100) -> list[str]:
    """Pitch up (or down) by *shift* semitones and the tempo to *speed*
    percent, in one pass. The default (R2) engine: about 25 times faster
    than real time for a shift; ``--fine`` (R3) was about 4 times, too slow
    to wait for. The output format follows *out*'s extension."""
    argv = [rubberband, "-p", str(shift)]
    if speed != 100:
        argv += ["-T", f"{speed / 100:g}"]
    return argv + [str(wav), str(out)]


def convert_argv(ffmpeg: str, src: Path, out: Path) -> list[str]:
    """rubberband's 24-bit output → 16-bit FLAC: half the size, and plenty
    for a backing track that ends up as an MP3."""
    return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(src),
            "-sample_fmt", "s16", "-c:a", "flac",
            "-progress", "pipe:1", "-nostats", "-f", "flac", str(out)]


def parse_percent(line: str) -> float | None:
    """rubberband's progress lines are just ``42%``; None for anything else."""
    m = _PERCENT.match(line)
    return min(1.0, int(m.group(1)) / 100) if m else None


def part_path(dest: Path) -> Path:
    """The in-progress copy keeps ``.flac`` at the end: ``….part.flac``."""
    return dest.with_name(f"{dest.stem}.part{dest.suffix}")


def remove_other_copies(dest: Path) -> None:
    """Keep only *dest* among the processed copies in its folder."""
    for p in dest.parent.glob("shift*.flac"):
        if p != dest:
            p.unlink(missing_ok=True)


def transpose(ffmpeg: str, rubberband: str, source: Path, shift: int, dest: Path,
              duration: float, on_fraction: OnFraction | None = None,
              cancel: proc.Cancel | None = None, tmp_dir: Path | None = None,
              speed: int = 100) -> Path | None:
    """Make *dest*, *source* shifted by *shift* semitones at *speed* percent.
    Returns *dest* (straight away if it's already there), or None if
    cancelled; raises TransposeError on failure. Nothing half-made is left
    behind."""
    if dest.exists():
        return dest
    out_duration = duration * 100 / speed
    shift_share = 1 - DECODE_SHARE - CONVERT_SHARE

    def report(f: float) -> None:
        if on_fraction is not None:
            on_fraction(f)

    def on_decode(line: str) -> None:
        t = render.parse_out_time(line)
        if t is not None and duration > 0:
            report(DECODE_SHARE * min(1.0, t / duration))

    def on_shift(line: str) -> None:
        f = parse_percent(line)
        if f is not None:
            report(DECODE_SHARE + shift_share * f)

    def on_convert(line: str) -> None:
        t = render.parse_out_time(line)
        if t is not None and out_duration > 0:
            report(DECODE_SHARE + shift_share + CONVERT_SHARE * min(1.0, t / out_duration))

    def fail(r: proc.Result) -> TransposeError:
        return TransposeError(render.friendly_error(r.output, FAILED), r.output)

    temps = []
    for suffix in (".wav", ".flac"):
        fd, name = tempfile.mkstemp(prefix="transpose-", suffix=suffix, dir=tmp_dir)
        os.close(fd)
        temps.append(Path(name))
    wav, stretched = temps
    part = part_path(dest)
    try:
        report(0.0)
        r = proc.run(decode_argv(ffmpeg, source, wav), on_line=on_decode, cancel=cancel)
        if r.cancelled:
            return None
        if r.returncode != 0:
            raise fail(r)
        r = proc.run(rubberband_argv(rubberband, wav, stretched, shift, speed),
                     on_line=on_shift, cancel=cancel, merge_stderr=True)
        if r.cancelled:
            return None
        if r.returncode != 0 or stretched.stat().st_size == 0:
            raise fail(r)
        wav.unlink(missing_ok=True)          # free the space before the next copy
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = proc.run(convert_argv(ffmpeg, stretched, part), on_line=on_convert, cancel=cancel)
        if r.cancelled:
            return None
        if r.returncode != 0 or not part.exists():
            raise fail(r)
        os.replace(part, dest)
        remove_other_copies(dest)
        report(1.0)
        return dest
    finally:
        for p in (*temps, part):
            p.unlink(missing_ok=True)
