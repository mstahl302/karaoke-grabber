"""The saved file's name (product spec F8): ``<Song Title> - AUDIO - <key>.mp3``
with the key you'll hear after any transposing, or ``<Song Title> - AUDIO.mp3``
when no key is chosen, ``<Song Title> - AUDIO (+2).mp3`` if it's transposed."""

from __future__ import annotations

import re

from karaokegrab import keys

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


def filename(title: str, key: str | None = None, shift: int = 0) -> str:
    """*key* is the original key; *shift* the transposition in semitones.
    The shift is written with a plain hyphen, (-2), so it's easy to type."""
    if key:
        return f"{clean_title(title)} - AUDIO - {keys.effective_key(key, shift)}.mp3"
    if shift:
        return f"{clean_title(title)} - AUDIO ({shift:+d}).mp3"
    return f"{clean_title(title)} - AUDIO.mp3"
