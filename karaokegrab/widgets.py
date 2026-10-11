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


class RoundButton(tk.Canvas):
    """A round button with a white symbol: ``"play"`` (a forward triangle)
    or ``"pause"`` (two bars). Drawn on a Canvas, since aqua can't make a
    round tk.Button. Like :class:`Button`: ``set_enabled(bool)``."""

    def __init__(self, parent, colour: str, command, *, size: int = 56, bg: str | None = None):
        bg = bg or parent.winfo_toplevel().cget("background")
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, bd=0,
                         cursor=HAND)
        self.size = size
        self._colour = colour
        self._command = command
        self._enabled = True
        self._hover = False
        self.symbol = "play"
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def set_symbol(self, symbol: str) -> None:
        if symbol != self.symbol:
            self.symbol = symbol
            self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        tk.Canvas.configure(self, cursor=HAND if self._enabled else "")
        self._draw()

    def _set_hover(self, on: bool) -> None:
        self._hover = on
        self._draw()

    def _release(self, e) -> None:
        inside = 0 <= e.x < self.size and 0 <= e.y < self.size
        if self._enabled and inside and self._command:
            self._command()

    def _draw(self) -> None:
        self.delete("all")
        s = self.size
        fill = self._colour
        if not self._enabled:
            fill = _fade(fill)
        elif self._hover:
            fill = darken(fill)
        self.create_oval(1, 1, s - 1, s - 1, fill=fill, outline="")
        c = s / 2
        if self.symbol == "pause":
            w, h, gap = s * 0.11, s * 0.36, s * 0.07
            for x0 in (c - gap - w, c + gap):
                self.create_rectangle(x0, c - h / 2, x0 + w, c + h / 2, fill="white", outline="")
        else:
            h = s * 0.40
            # nudged right so the triangle looks centred
            self.create_polygon(c - h * 0.36, c - h / 2, c - h * 0.36, c + h / 2, c + h * 0.62, c,
                                fill="white", outline="")


class PencilButton(tk.Canvas):
    """A square button with a white pencil, tip down to the left. Drawn on a
    Canvas because the "✎" glyph is squat and points the other way. Like
    :class:`Button`: ``set_enabled(bool)``."""

    ANGLE = 62          # degrees above horizontal: steeper than a 45° glyph

    def __init__(self, parent, colour: str, command, *, size: int = 30):
        super().__init__(parent, width=size, height=size, highlightthickness=0, bd=0,
                         bg=parent.cget("background"), cursor=HAND)
        self.size = size
        self._colour = colour
        self._command = command
        self._enabled = True
        self._hover = False
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        tk.Canvas.configure(self, cursor=HAND if self._enabled else "")
        self._draw()

    def _set_hover(self, on: bool) -> None:
        self._hover = on
        self._draw()

    def _release(self, e) -> None:
        inside = 0 <= e.x < self.size and 0 <= e.y < self.size
        if self._enabled and inside and self._command:
            self._command()

    def _draw(self) -> None:
        import math
        self.delete("all")
        s = self.size
        fill = self._colour
        if not self._enabled:
            fill = _fade(fill)
        elif self._hover:
            fill = darken(fill)
        self.create_rectangle(0, 0, s, s, fill=fill, outline="")
        # Pencil in its own frame: u runs from the tip (u=0) to the eraser
        # end, v across it. Then rotated so the tip sits low on the left.
        a = math.radians(self.ANGLE)
        ux, uy = math.cos(a), -math.sin(a)          # along the pencil, up and to the right
        vx, vy = -uy, ux                            # across it
        length, half = s * 0.78, s * 0.115
        cx, cy = s / 2, s / 2
        x0, y0 = cx - ux * length / 2, cy - uy * length / 2      # the tip

        def pt(u: float, v: float) -> tuple[float, float]:
            return x0 + ux * u + vx * v, y0 + uy * u + vy * v

        tip, body, band = length * 0.26, length * 0.80, length * 0.86
        white = "white"
        # sharpened point, with the graphite in the pencil's colour
        self.create_polygon(*pt(0, 0), *pt(tip, -half), *pt(tip, half), fill=white, outline="")
        self.create_polygon(*pt(0, 0), *pt(tip * 0.36, -half * 0.36), *pt(tip * 0.36, half * 0.36),
                            fill=fill, outline="")
        # body, then a gap, then the eraser
        self.create_polygon(*pt(tip + 1, -half), *pt(body, -half), *pt(body, half),
                            *pt(tip + 1, half), fill=white, outline="")
        self.create_polygon(*pt(band, -half), *pt(length, -half), *pt(length, half),
                            *pt(band, half), fill=white, outline="")
