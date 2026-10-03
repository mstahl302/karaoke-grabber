"""A two-handle range slider on a Tk Canvas, with an optional playback cursor.

Used twice in the window: the Trim slider (a thick coloured bar between the
handles) and the Fade slider (a ramp at each end showing the fades). The
pixel ↔ seconds math lives in small pure functions at the top so it can be
tested without Tk.

Interaction: drag a handle to move it (handles never cross and keep
``min_gap`` apart); click anywhere else on the track to move the cursor.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from karaokegrab.widgets import MAGENTA, PURPLE, _rgb, _hex

GRAB_PX = 12          # how close (px) a press must be to grab a handle
PAD_X = 22            # space at each end so a handle at the extreme stays visible


# ---------------------------------------------------------------- pure math

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class Track:
    """Maps times in [lo, hi] onto pixels in [x0, x1]."""
    lo: float
    hi: float
    x0: float
    x1: float

    def to_x(self, t: float) -> float:
        if self.hi <= self.lo:
            return self.x0
        return self.x0 + (clamp(t, self.lo, self.hi) - self.lo) / (self.hi - self.lo) * (self.x1 - self.x0)

    def to_t(self, x: float) -> float:
        if self.x1 <= self.x0:
            return self.lo
        return self.lo + (clamp(x, self.x0, self.x1) - self.x0) / (self.x1 - self.x0) * (self.hi - self.lo)


def move_handle(which: int, t: float, a: float, b: float,
                lo: float, hi: float, gap: float) -> tuple[float, float]:
    """Move handle *which* (0 = left, 1 = right) to time *t*; returns the new
    (a, b) with the handles inside [lo, hi], uncrossed and *gap* apart."""
    gap = min(gap, max(0.0, hi - lo))
    if which == 0:
        a = clamp(t, lo, b - gap)
    else:
        b = clamp(t, a + gap, hi)
    return a, b


def pick_handle(x: float, xa: float, xb: float, grab: float = GRAB_PX) -> int | None:
    """Which handle a press at *x* grabs: 0, 1, or None (a click on the track).
    When the handles overlap, the side of the press decides."""
    da, db = abs(x - xa), abs(x - xb)
    if min(da, db) > grab:
        return None
    if da == db:
        return 0 if x <= xa else 1
    return 0 if da < db else 1


def blend(c1: str, c2: str, f: float) -> str:
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    return _hex(r1 + (r2 - r1) * f, g1 + (g2 - g1) * f, b1 + (b2 - b1) * f)


# ---------------------------------------------------------------- widget

OnChange = Callable[[float, float, bool], None]     # (a, b, final)
OnSeek = Callable[[float], None]

TRACK_BG = "#e4dfe9"
FRAME_BG = "#f6f4f8"
DISABLED = "#cfcad4"
CURSOR = "#1d1b20"


class RangeSlider(tk.Canvas):
    def __init__(self, parent, *, style: str = "trim", height: int = 64,
                 on_change: OnChange | None = None, on_seek: OnSeek | None = None,
                 min_gap: float = 0.0) -> None:
        super().__init__(parent, height=height, bg=FRAME_BG, highlightthickness=1,
                         highlightbackground="#e2dcea", bd=0)
        self.style = style
        self.on_change = on_change
        self.on_seek = on_seek
        self.min_gap = min_gap
        self.lo, self.hi = 0.0, 1.0
        self.a, self.b = 0.0, 1.0
        self.cursor: float | None = None
        self.enabled = False
        self._drag: int | None = None
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    # -- API
    def set_range(self, lo: float, hi: float) -> None:
        self.lo, self.hi = lo, max(lo, hi)
        self.redraw()

    def set_values(self, a: float, b: float) -> None:
        self.a, self.b = clamp(a, self.lo, self.hi), clamp(b, self.lo, self.hi)
        self.redraw()

    def set_cursor(self, t: float | None) -> None:
        self.cursor = t
        self._draw_cursor()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self._drag = None
        self.redraw()

    def track(self) -> Track:
        w = max(self.winfo_width(), 2 * PAD_X + 1)
        return Track(self.lo, self.hi, PAD_X, w - PAD_X)

    # -- drawing
    def redraw(self) -> None:
        self.delete("all")
        h = max(self.winfo_height(), int(self["height"]))
        tr = self.track()
        xa, xb = tr.to_x(self.a), tr.to_x(self.b)
        cy = h / 2
        on = self.enabled
        if self.style == "trim":
            self.create_line(tr.x0, cy, tr.x1, cy, width=10, fill=TRACK_BG, capstyle="round")
            if on:
                n = max(1, int((xb - xa) / 6))
                for i in range(n):
                    x = xa + (xb - xa) * i / n
                    self.create_line(x, cy, xa + (xb - xa) * (i + 1) / n + 0.5, cy, width=10,
                                     fill=blend(PURPLE, MAGENTA, i / max(1, n - 1)))
            else:
                self.create_line(xa, cy, xb, cy, width=10, fill=DISABLED)
        else:   # fade: a ramp up to the left handle, flat between, ramp down after the right one
            top, bottom = 14, h - 14
            fill = "#e3d3e8" if on else "#e6e3e9"
            edge = PURPLE if on else DISABLED
            pts = [tr.x0, bottom, xa, top, xb, top, tr.x1, bottom]
            self.create_polygon(*pts, fill=fill, outline="")
            self.create_line(*pts, fill=edge, width=2)
        for x, colour in ((xa, PURPLE), (xb, MAGENTA)):
            self.create_rectangle(x - 7, cy - 17, x + 7, cy + 17, fill="white",
                                  outline=colour if on else DISABLED, width=3, tags="handle")
        self._draw_cursor()

    def _draw_cursor(self) -> None:
        self.delete("cursor")
        if self.cursor is None or not self.enabled or not (self.lo <= self.cursor <= self.hi):
            return
        h = max(self.winfo_height(), int(self["height"]))
        x = self.track().to_x(self.cursor)
        self.create_line(x, 6, x, h - 6, width=2, fill=CURSOR, tags="cursor")
        self.create_polygon(x - 6, 4, x + 6, 4, x, 11, fill=CURSOR, tags="cursor")

    # -- mouse
    def _press(self, e) -> None:
        if not self.enabled:
            return
        tr = self.track()
        self._drag = pick_handle(e.x, tr.to_x(self.a), tr.to_x(self.b))
        if self._drag is None and self.on_seek is not None:
            self.on_seek(tr.to_t(e.x))

    def _motion(self, e) -> None:
        if self._drag is None or not self.enabled:
            return
        a, b = move_handle(self._drag, self.track().to_t(e.x), self.a, self.b,
                           self.lo, self.hi, self.min_gap)
        if (a, b) != (self.a, self.b):
            self.a, self.b = a, b
            self.redraw()
            if self.on_change is not None:
                self.on_change(a, b, False)

    def _release(self, _e) -> None:
        if self._drag is None:
            return
        self._drag = None
        if self.on_change is not None:
            self.on_change(self.a, self.b, True)
