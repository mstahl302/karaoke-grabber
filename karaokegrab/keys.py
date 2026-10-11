"""The 24 key names, written as words, in Key-dropdown order (product spec F7),
and the key you hear after transposing (F17).

The same spelling goes into the filename, e.g. ``... - AUDIO - B-flat.mp3``.
Each list runs chromatically from C, so shifting by n semitones is n steps
along it, wrapping around.
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

MAX_SHIFT = 9          # transpose range: -9 to +9 semitones


def lookup(text: str) -> str | None:
    """The canonical key name for *text*, ignoring case and extra spaces;
    None when it isn't one of the 24."""
    wanted = " ".join(text.split()).casefold()
    for key in KEYS:
        if key.casefold() == wanted:
            return key
    return None


def effective_key(key: str, shift: int) -> str:
    """The key heard after shifting *key* by *shift* semitones: B-flat +2 → C,
    A minor -3 → F-sharp minor. Minor stays minor; spellings come from the lists."""
    for scale in (MAJOR, MINOR):
        if key in scale:
            return scale[(scale.index(key) + shift) % 12]
    raise ValueError(f"not a key: {key!r}")


def shift_label(shift: int) -> str:
    """The shift as shown in the window: "+2", "−3" (a real minus sign), "0"."""
    if shift > 0:
        return f"+{shift}"
    if shift < 0:
        return f"\u2212{-shift}"
    return "0"


def short_name(key: str) -> str:
    """The compact spelling the window uses: B♭, F♯, Cm, C♯m. The file name
    keeps the words (B-flat, C-sharp minor)."""
    return (key.replace("-flat", "♭").replace("-sharp", "♯")
            .replace(" minor", "m"))


SHORT: tuple[str, ...] = tuple(short_name(k) for k in KEYS)
_FROM_SHORT = dict(zip(SHORT, KEYS))


def from_short(text: str) -> str | None:
    """The key named by a short spelling from the dropdown, or None."""
    return _FROM_SHORT.get(text.strip())
