"""Shift the cached audio by whole semitones without changing its tempo
(product spec F17, architecture §5.3).

Pitch shifting is slow, so it's done once per shift for the whole track:
ffmpeg decodes the download to a 48 kHz stereo WAV in the temp folder,
``rubberband -p <n>`` shifts it, and the result is kept as
``cache/<id>/shift<n>.flac``. Every preview and save then renders from
that copy. Only the latest shift is kept; going back to 0 uses the
download itself.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable

from karaokegrab import proc, render

FAILED = "Transposing failed. See Details for the tool output."
DECODE_SHARE = 0.10        # the decode is the first 10% of the progress bar
SAMPLE_RATE = 48000

OnFraction = Callable[[float], None]

_PERCENT = re.compile(r"^\s*(\d{1,3})%\s*$")


class TransposeError(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def decode_argv(ffmpeg: str, source: Path, wav: Path) -> list[str]:
    """The download → a 16-bit 48 kHz stereo WAV for rubberband."""
    return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-i", str(source), "-vn",
            "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_s16le",
            "-progress", "pipe:1", "-nostats", str(wav)]


def rubberband_argv(rubberband: str, wav: Path, out: Path, shift: int) -> list[str]:
    """Pitch up (or down) by *shift* semitones, tempo unchanged. The default
    (R2) engine: about 25 times faster than real time; ``--fine`` (R3) was
    about 4 times, too slow to wait for. The output format follows *out*'s
    extension."""
    return [rubberband, "-p", str(shift), str(wav), str(out)]


def parse_percent(line: str) -> float | None:
    """rubberband's progress lines are just ``42%``; None for anything else."""
    m = _PERCENT.match(line)
    return min(1.0, int(m.group(1)) / 100) if m else None


def part_path(dest: Path) -> Path:
    """rubberband picks the format from the extension, so the in-progress
    file keeps ``.flac`` at the end: ``shift2.part.flac``."""
    return dest.with_name(f"{dest.stem}.part{dest.suffix}")


def remove_other_shifts(dest: Path) -> None:
    """Keep only *dest* among the transposed copies in its folder."""
    for p in dest.parent.glob("shift*.flac"):
        if p != dest:
            p.unlink(missing_ok=True)


def transpose(ffmpeg: str, rubberband: str, source: Path, shift: int, dest: Path,
              duration: float, on_fraction: OnFraction | None = None,
              cancel: proc.Cancel | None = None, tmp_dir: Path | None = None) -> Path | None:
    """Make *dest*, *source* shifted by *shift* semitones. Returns *dest*
    (straight away if it's already there), or None if cancelled; raises
    TransposeError on failure. Nothing half-made is left behind."""
    if dest.exists():
        return dest

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
            report(DECODE_SHARE + (1 - DECODE_SHARE) * f)

    fd, name = tempfile.mkstemp(prefix="transpose-", suffix=".wav", dir=tmp_dir)
    os.close(fd)
    wav = Path(name)
    part = part_path(dest)
    try:
        report(0.0)
        r = proc.run(decode_argv(ffmpeg, source, wav), on_line=on_decode, cancel=cancel)
        if r.cancelled:
            return None
        if r.returncode != 0:
            raise TransposeError(render.friendly_error(r.output, FAILED), r.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = proc.run(rubberband_argv(rubberband, wav, part, shift), on_line=on_shift,
                     cancel=cancel, merge_stderr=True)
        if r.cancelled:
            return None
        if r.returncode != 0 or not part.exists():
            raise TransposeError(render.friendly_error(r.output, FAILED), r.output)
        os.replace(part, dest)
        remove_other_shifts(dest)
        report(1.0)
        return dest
    finally:
        wav.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
