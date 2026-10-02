"""Format seconds for the read-only trim and fade values.

Under a minute reads as ``4.5 s``; a minute or more as ``5:34.5``, and an
hour or more as ``1:02:03.0``. Always one decimal place. (Parsing typed
values arrives with Roadmap R8.)
"""

from __future__ import annotations


def format_seconds(seconds: float) -> str:
    # Round to tenths first, so 59.96 becomes 1:00.0 rather than 60.0 s.
    tenths = max(0, round(seconds * 10))
    if tenths < 600:
        return f"{tenths / 10:.1f} s"
    whole, frac = divmod(tenths, 10)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{frac}"
    return f"{minutes}:{secs:02d}.{frac}"
