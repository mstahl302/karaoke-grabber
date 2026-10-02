"""Download a video's best audio stream into the cache, as is (no re-encode)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from karaokegrab import cache, proc

PREFIX = "PROG|"
PROGRESS_TEMPLATE = (
    "download:" + PREFIX
    + "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    + "%(progress.total_bytes_estimate)s|%(progress.eta)s"
)

FAILED = ("YouTube download failed. yt-dlp may be out of date; "
          "update it with: brew upgrade yt-dlp")


class DownloadError(Exception):
    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


@dataclass(frozen=True)
class Progress:
    downloaded: int
    total: int | None
    eta: float | None

    @property
    def fraction(self) -> float | None:
        if not self.total:
            return None
        return min(1.0, self.downloaded / self.total)


OnProgress = Callable[[Progress], None]


def _num(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None  # yt-dlp prints "NA" for unknown values


def parse_progress(line: str) -> Progress | None:
    """One ``PROG|downloaded|total|estimate|eta`` line → Progress; None for
    any other line."""
    if not line.startswith(PREFIX):
        return None
    parts = line[len(PREFIX):].split("|")
    if len(parts) != 4:
        return None
    downloaded, total, estimate, eta = (_num(p.strip()) for p in parts)
    if downloaded is None:
        return None
    size = total if total else estimate
    return Progress(downloaded=int(downloaded),
                    total=int(size) if size else None,
                    eta=eta)


def download_argv(ytdlp: str, video_id: str, source: str | Path,
                  root: Path | None = None) -> list[str]:
    """*source* is the video URL, or a saved info.json (skips a second lookup)."""
    argv = [ytdlp, "-f", "bestaudio/best", "--no-playlist", "--newline",
            "--no-warnings", "--no-mtime", "--progress-template", PROGRESS_TEMPLATE,
            "-o", cache.audio_template(video_id, root)]
    if isinstance(source, Path):
        return argv + ["--load-info-json", str(source)]
    return argv + [source]


def download(ytdlp: str, video_id: str, source: str | Path,
             on_progress: OnProgress | None = None,
             cancel: proc.Cancel | None = None,
             root: Path | None = None) -> Path | None:
    """Download into the cache and return the audio file, reusing a cached
    copy if there is one. Returns None if cancelled (partial files deleted);
    raises DownloadError on failure."""
    cached = cache.find_audio(video_id, root)
    if cached is not None:
        return cached
    cache.video_dir(video_id, root).mkdir(parents=True, exist_ok=True)

    def on_line(line: str) -> None:
        p = parse_progress(line)
        if p is not None and on_progress is not None:
            on_progress(p)

    r = proc.run(download_argv(ytdlp, video_id, source, root), on_line=on_line, cancel=cancel)
    if r.cancelled:
        cache.remove_partials(video_id, root)
        return None
    audio = cache.find_audio(video_id, root)
    if r.returncode != 0 or audio is None:
        cache.remove_partials(video_id, root)
        raise DownloadError(FAILED, r.output)
    return audio
