"""The 24 key names, written as words, in Key-dropdown order (product spec F7).

The same spelling goes into the filename, e.g. ``... - AUDIO - B-flat.mp3``.
"""

from __future__ import annotations

MAJOR: tuple[str, ...] = (
    "C", "D-flat", "D", "E-flat", "E", "F",
    "F-sharp", "G", "A-flat", "A", "B-flat", "B",
)

MINOR: tuple[str, ...] = (
    "C minor", "C-sharp minor", "D minor", "E-flat minor", "E minor", "F minor",
    "F-sharp minor", "G minor", "G-sharp minor", "A minor", "B-flat minor", "B minor",
)

KEYS: tuple[str, ...] = MAJOR + MINOR


def lookup(text: str) -> str | None:
    """The canonical key name for *text*, ignoring case and extra spaces;
    None when it isn't one of the 24."""
    wanted = " ".join(text.split()).casefold()
    for key in KEYS:
        if key.casefold() == wanted:
            return key
    return None
