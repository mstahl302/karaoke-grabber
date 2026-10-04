"""Check what was pasted into the URL box, before yt-dlp sees it.

Only a single, well-formed ``http(s)://`` link to one YouTube video is
accepted: the box may hold surrounding spaces, nothing else. Other sites
wait for Roadmap R10. Playlist-only links are spotted here because yt-dlp
would otherwise spend a long time listing the playlist before we could
reject it.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

# youtube.com and its subdomains (www., m., music.), youtu.be, the no-cookie embed domain.
YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com")

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{6,}$")
# Paths that name one video: /shorts/<id>, /live/<id>, /embed/<id>, /v/<id>
_VIDEO_PATHS = ("shorts", "live", "embed", "v")


def well_formed(text: str) -> str | None:
    """The link if *text* is exactly one http(s) URL with a host (surrounding
    spaces allowed), else None."""
    url = text.strip()
    if not url or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return url


def host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_youtube(url: str) -> bool:
    h = host(url)
    return any(h == d or h.endswith("." + d) for d in YOUTUBE_HOSTS)


def is_playlist_only(url: str) -> bool:
    """A link to a whole playlist rather than one video in it:
    ``/playlist?list=…``, or ``watch?list=…`` without a ``v=``."""
    if not is_youtube(url) or host(url).endswith("youtu.be"):
        return False
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    return "list" in query and "v" not in query and parts.path.rstrip("/") in ("/playlist", "/watch", "")


def is_video(url: str) -> bool:
    """A YouTube link that names one video (``watch?v=…``, ``youtu.be/…``,
    ``/shorts/…``, ``/live/…``, ``/embed/…``)."""
    if not is_youtube(url):
        return False
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if host(url).endswith("youtu.be"):
        return len(segments) == 1 and bool(_VIDEO_ID.match(segments[0]))
    if parts.path.rstrip("/") == "/watch":
        v = parse_qs(parts.query).get("v", [""])[0]
        return bool(_VIDEO_ID.match(v))
    return len(segments) == 2 and segments[0] in _VIDEO_PATHS and bool(_VIDEO_ID.match(segments[1]))
