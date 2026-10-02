"""The download cache: full-length source audio, one folder per video id.

    ~/Library/Caches/Karaoke Grabber/<video id>/
        audio.<ext>     best audio stream as downloaded (Opus/WebM, M4A, ...)
        info.json       yt-dlp metadata, reused for the thumbnail
        thumb.png

A folder's modification time marks when it was last used; :func:`prune`
keeps the most recent few.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

CACHE_DIR = Path.home() / "Library" / "Caches" / "Karaoke Grabber"
KEEP = 10

AUDIO_STEM = "audio"
# yt-dlp's in-progress and leftover files.
_PARTIAL_SUFFIXES = (".part", ".ytdl", ".temp")
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def video_dir(video_id: str, root: Path | None = None) -> Path:
    safe = _SAFE_ID.sub("_", video_id) or "_"
    return (root or CACHE_DIR) / safe


def info_path(video_id: str, root: Path | None = None) -> Path:
    return video_dir(video_id, root) / "info.json"


def thumb_stem(video_id: str, root: Path | None = None) -> Path:
    return video_dir(video_id, root) / "thumb"


def audio_template(video_id: str, root: Path | None = None) -> str:
    """yt-dlp ``-o`` template for the audio file."""
    return str(video_dir(video_id, root) / f"{AUDIO_STEM}.%(ext)s")


def _is_partial(p: Path) -> bool:
    return any(p.name.endswith(s) for s in _PARTIAL_SUFFIXES) or ".part-" in p.name


def find_audio(video_id: str, root: Path | None = None) -> Path | None:
    """The cached audio for *video_id*, or None. Marks the folder as used."""
    d = video_dir(video_id, root)
    if not d.is_dir():
        return None
    for p in sorted(d.glob(f"{AUDIO_STEM}.*")):
        if p.is_file() and not _is_partial(p) and p.stat().st_size > 0:
            touch(video_id, root)
            return p
    return None


def remove_partials(video_id: str, root: Path | None = None) -> None:
    d = video_dir(video_id, root)
    if not d.is_dir():
        return
    for p in d.iterdir():
        if p.is_file() and p.name.startswith(AUDIO_STEM + ".") and _is_partial(p):
            p.unlink(missing_ok=True)


def touch(video_id: str, root: Path | None = None) -> None:
    d = video_dir(video_id, root)
    if d.is_dir():
        now = time.time()
        os.utime(d, (now, now))


def prune(keep: int = KEEP, root: Path | None = None, protect: str | None = None) -> list[Path]:
    """Delete all but the *keep* most recently used video folders (never
    *protect*'s). Returns the folders removed."""
    base = root or CACHE_DIR
    if not base.is_dir():
        return []
    dirs = [d for d in base.iterdir() if d.is_dir()]
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    keep_set = set(dirs[:keep])
    if protect is not None:
        keep_set.add(video_dir(protect, root))
    removed = []
    for d in dirs:
        if d not in keep_set:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d)
    return removed
