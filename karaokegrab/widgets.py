"""Flat, colour-filled buttons that actually render their colour on macOS.

`tk.Button` on the macOS aqua theme ignores `background` while enabled
(it draws the native grey button face), so a coloured button built that
way shows grey when clickable. `widgets.Button` is a `tk.Label` with
mouse bindings — Labels honour their `background` on every platform.

It is *not* a drop-in `tk.Button`: use ``set_enabled(bool)`` instead of
``configure(state=…)``. ``configure(text=…)``, ``cget(…)``, ``grid(…)``
etc. are the stock `tk.Label` methods, untouched.
"""

from __future__ import annotations

import sys
import tkinter as tk

# Karaoke Grabber palette (the icon's purple-to-magenta gradient, product spec §7).
PURPLE = "#6a2c91"
MAGENTA = "#b8327a"

# "pointinghand" exists only on macOS (aqua); X11, as in CI, calls it "hand2".
HAND = "pointinghand" if sys.platform == "darwin" else "hand2"


def _rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _hex(r: float, g: float, b: float) -> str:
    def c(v: float) -> int:
        return max(0, min(255, int(round(v))))
    return f"#{c(r):02x}{c(g):02x}{c(b):02x}"


def darken(colour: str, factor: float = 0.82) -> str:
    r, g, b = _rgb(colour)
    return _hex(r * factor, g * factor, b * factor)


def _fade(colour: str, t: float = 0.55) -> str:
    """Blend toward white — the disabled / not-yet-available look."""
    r, g, b = _rgb(colour)
    return _hex(r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t)


class Button(tk.Label):
    def __init__(self, parent, text: str, colour: str, command, *, big: bool = False):
        super().__init__(
            parent, text=text, bg=colour, fg="white", font="TkDefaultFont",
            padx=20 if big else 16, pady=9 if big else 7,
            bd=0, relief="flat", highlightthickness=0, cursor=HAND,
        )
        self._command = command
        self._colour = colour
        self._enabled = True
        self.bind("<Enter>", self._hover)
        self.bind("<Leave>", self._unhover)
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _hover(self, _e):
        if self._enabled:
            tk.Label.configure(self, bg=darken(self._colour))

    def _unhover(self, _e):
        if self._enabled:
            tk.Label.configure(self, bg=self._colour)

    def _press(self, _e):
        if self._enabled:
            tk.Label.configure(self, bg=darken(self._colour, 0.68))

    def _release(self, e):
        if not self._enabled:
            return
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        tk.Label.configure(self, bg=darken(self._colour) if inside else self._colour)
        if inside and self._command:
            self._command()

    # ---- state / colour -----------------------------------------
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if self._enabled:
            tk.Label.configure(self, bg=self._colour, fg="white", cursor=HAND)
        else:
            tk.Label.configure(self, bg=_fade(self._colour), fg="#f4f6fa", cursor="")

    def recolour(self, colour: str) -> None:
        self._colour = colour
        self.set_enabled(self._enabled)


def button(parent, text: str, colour: str, command, *, big: bool = False) -> Button:
    return Button(parent, text, colour, command, big=big)


def recolour(btn: Button, colour: str) -> None:
    btn.recolour(colour)
