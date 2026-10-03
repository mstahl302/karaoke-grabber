"""The saved file's name: ``<Song Title> - AUDIO - <key>.mp3``, or
``<Song Title> - AUDIO.mp3`` when no key is chosen (product spec F8)."""

from __future__ import annotations

import re

# macOS allows 255 bytes per filename; leave room for the suffix and ".part".
MAX_TITLE_CHARS = 150
UNTITLED = "Untitled"


def clean_title(title: str) -> str:
    """The title made safe for a filename: ``/`` and ``:`` replaced, control
    characters dropped, whitespace trimmed and collapsed, no leading dot,
    length capped. Empty becomes ``Untitled``."""
    t = title.replace("/", "-").replace(":", "-")
    t = re.sub(r"[\x00-\x1f\x7f]", " ", t)
    t = " ".join(t.split())
    t = t.lstrip(".").strip()
    if len(t) > MAX_TITLE_CHARS:
        t = t[:MAX_TITLE_CHARS].rstrip()
    return t or UNTITLED


def filename(title: str, key: str | None = None) -> str:
    if key:
        return f"{clean_title(title)} - AUDIO - {key}.mp3"
    return f"{clean_title(title)} - AUDIO.mp3"
