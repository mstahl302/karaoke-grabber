"""Look up a video with ``yt-dlp -J`` and fetch its thumbnail as PNG."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from karaokegrab import links, proc
from karaokegrab.trim import MIN_LENGTH

# Substrings of yt-dlp's error output → the message we show. First match wins.
_ERRORS: tuple[tuple[str, str], ...] = (
    ("is not a valid url", "That doesn't look like a web address. Paste the full YouTube link."),
    ("unsupported url", "That link isn't a YouTube video. Paste the link of a single video."),
    ("private video", "That video is private, so it can't be downloaded."),
    ("video is private", "That video is private, so it can't be downloaded."),
    ("confirm your age", "That video is age-restricted, so it can't be downloaded."),
    ("members-only", "That video is for channel members only, so it can't be downloaded."),
    ("not a bot", "YouTube asked to confirm this isn't a bot. Try again in a few minutes; "
                  "if it keeps happening, update yt-dlp: brew upgrade yt-dlp"),
    ("video unavailable", "That video is unavailable. It may have been removed or blocked."),
    ("this video is unavailable", "That video is unavailable. It may have been removed or blocked."),
    ("http error 404", "Nothing was found at that link. Check it and try again."),
    ("unable to download webpage", "Couldn't reach YouTube. Check your internet connection."),
    ("failed to resolve", "Couldn't reach YouTube. Check your internet connection."),
    ("nodename nor servname", "Couldn't reach YouTube. Check your internet connection."),
    ("timed out", "Couldn't reach YouTube. Check your internet connection."),
)

GENERIC = ("Couldn't look up that video. yt-dlp may be out of date; "
           "update it with: brew upgrade yt-dlp")
PLAYLIST = "That's a playlist link. Paste the link of a single video."
NOT_YOUTUBE = "Only YouTube links for now. Paste a youtube.com or youtu.be link."


class FetchError(Exception):
    """A friendly *message* plus the raw tool output in *details*."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details


@dataclass(frozen=True)
class VideoInfo:
    id: str
    title: str
    channel: str
    duration: float
    thumbnail_url: str
    url: str
    raw: dict = field(repr=False, compare=False, default_factory=dict)


def friendly_error(output: str) -> str:
    low = output.lower()
    for needle, message in _ERRORS:
        if needle in low:
            return message
    return GENERIC


def parse_info(data: dict) -> VideoInfo:
    """``yt-dlp -J`` JSON → VideoInfo. Raises FetchError for playlists,
    live streams and entries with no duration."""
    if data.get("_type", "video") != "video" or "entries" in data:
        raise FetchError(PLAYLIST)
    live = data.get("live_status")
    if data.get("is_live") or live in ("is_live", "is_upcoming", "post_live"):
        raise FetchError("That's a live stream. Only finished videos can be downloaded.")
    duration = data.get("duration")
    if not duration:
        raise FetchError("Couldn't tell how long that video is, so it can't be trimmed.")
    if float(duration) < MIN_LENGTH:
        raise FetchError("That video is too short to trim (under a second).")
    return VideoInfo(
        id=str(data["id"]),
        title=str(data.get("title") or ""),
        channel=str(data.get("channel") or data.get("uploader") or ""),
        duration=float(duration),
        thumbnail_url=str(data.get("thumbnail") or ""),
        url=str(data.get("webpage_url") or data.get("original_url") or ""),
        raw=data,
    )


NOT_A_LINK = ("That isn't a web address. Paste just the YouTube link, "
              "starting with https://")
NOT_A_VIDEO = ("That's not a link to a YouTube video. Paste the link of one video "
               "(it has watch?v= in it, or starts with youtu.be/).")


def check_url(text: str) -> str:
    """The link to fetch from what was pasted; raises FetchError for an
    empty box, anything but one well-formed link, a playlist-only link, a
    non-YouTube link or a YouTube link that isn't a video, before any
    yt-dlp call."""
    if not text.strip():
        raise FetchError("Paste a YouTube link first.")
    url = links.well_formed(text)
    if url is None:
        raise FetchError(NOT_A_LINK)
    if not links.is_youtube(url):
        raise FetchError(NOT_YOUTUBE)
    if links.is_playlist_only(url):
        raise FetchError(PLAYLIST)
    if not links.is_video(url):
        raise FetchError(NOT_A_VIDEO)
    return url


def info_argv(ytdlp: str, url: str) -> list[str]:
    return [ytdlp, "-J", "--no-playlist", "--no-warnings", url]


def fetch_info(ytdlp: str, url: str, cancel: proc.Cancel | None = None) -> VideoInfo | None:
    """Look up *url*. Returns None if cancelled; raises FetchError on failure."""
    url = check_url(url)
    r = proc.run(info_argv(ytdlp, url), cancel=cancel)
    if r.cancelled:
        return None
    if r.returncode != 0:
        raise FetchError(friendly_error(r.stderr or r.stdout), r.output)
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise FetchError(GENERIC, r.output) from None
    if not isinstance(data, dict):
        raise FetchError(GENERIC, r.output)
    return parse_info(data)


def save_info(info: VideoInfo, path: Path) -> Path:
    """Write the raw JSON where ``--load-info-json`` can reuse it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(info.raw))
    return path


def thumbnail_argv(ytdlp: str, info_json: Path, dest_stem: Path) -> list[str]:
    return [ytdlp, "--load-info-json", str(info_json), "--skip-download",
            "--write-thumbnail", "--convert-thumbnails", "png", "--no-warnings",
            "-o", f"{dest_stem}.%(ext)s"]


def fetch_thumbnail(ytdlp: str, info_json: Path, dest_stem: Path,
                    cancel: proc.Cancel | None = None) -> Path | None:
    """Save the thumbnail as ``<dest_stem>.png`` (Tk 9 shows PNG natively).
    Returns the path, or None if it couldn't be fetched; a missing
    thumbnail never stops the workflow."""
    png = dest_stem.with_suffix(".png")
    if png.exists():
        return png
    r = proc.run(thumbnail_argv(ytdlp, info_json, dest_stem), cancel=cancel)
    return png if r.ok and png.exists() else None
