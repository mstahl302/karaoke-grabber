"""Run ffmpeg for the final MP3 and for preview clips, with progress and cancel.

Output goes to ``<path>.part`` first and is renamed into place only when
ffmpeg succeeds, so a cancelled or failed save never leaves a half-written
file under the real name.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from karaokegrab import proc, trim
from karaokegrab.trim import TrimSpec

FAILED = "Saving the MP3 failed. See Details for ffmpeg's output."
PREVIEW_FAILED = "Making the preview failed. See Details for ffmpeg's output."

OnFraction = Callable[[float], None]


class RenderError(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


def parse_out_time(line: str) -> float | None:
    """Seconds of output written, from one ``-progress`` line
    (``out_time_us=12345678``); None for other lines or ``N/A``."""
    key, sep, value = line.partition("=")
    if not sep or key.strip() not in ("out_time_us", "out_time_ms"):
        return None
    # Despite its name, ffmpeg's out_time_ms is also in microseconds.
    try:
        return max(0.0, int(value.strip()) / 1_000_000)
    except ValueError:
        return None


def part_path(path: Path) -> Path:
    return path.with_name(path.name + ".part")


def _run(argv: list[str], expected: float, part: Path, final: Path, failed: str,
         on_fraction: OnFraction | None, cancel: proc.Cancel | None) -> Path | None:
    def on_line(line: str) -> None:
        if on_fraction is None:
            return
        if line.strip() == "progress=end":
            on_fraction(1.0)
            return
        t = parse_out_time(line)
        if t is not None and expected > 0:
            on_fraction(min(1.0, t / expected))

    r = proc.run(argv, on_line=on_line, cancel=cancel)
    if r.cancelled:
        part.unlink(missing_ok=True)
        return None
    if r.returncode != 0 or not part.exists():
        part.unlink(missing_ok=True)
        raise RenderError(failed, r.output)
    os.replace(part, final)
    return final


def render_mp3(ffmpeg: str, source: Path, spec: TrimSpec, path: Path,
               on_fraction: OnFraction | None = None,
               cancel: proc.Cancel | None = None) -> Path | None:
    """Save the trimmed, faded MP3 at *path* (spec already clamped). Returns
    *path*, or None if cancelled; raises RenderError on failure."""
    part = part_path(path)
    argv = trim.mp3_argv(ffmpeg, source, spec, part)
    return _run(argv, spec.length, part, path, FAILED, on_fraction, cancel)


def render_preview(ffmpeg: str, source: Path, spec: TrimSpec, cursor: float, path: Path,
                   on_fraction: OnFraction | None = None,
                   cancel: proc.Cancel | None = None) -> Path | None:
    """A WAV clip from *cursor* to the trim end, for afplay."""
    part = part_path(path)
    argv = trim.preview_argv(ffmpeg, source, spec, cursor, part)
    expected = spec.length - trim.preview_offset(spec, cursor)
    return _run(argv, expected, part, path, PREVIEW_FAILED, on_fraction, cancel)
