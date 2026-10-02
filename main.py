#!/usr/bin/env python3
"""Karaoke Grabber — Tkinter front-end.

M0 skeleton: an empty main window that quits cleanly. The real UI is built
in M2 and M3; see docs/product_spec.md §6 and docs/build_plan.md.
"""

from __future__ import annotations

import tkinter as tk

from karaokegrab import __version__

APP_NAME = "Karaoke Grabber"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self._closing = False
        self.title(APP_NAME)
        self.minsize(560, 420)
        tk.Label(self, text=f"{APP_NAME} {__version__}").pack(padx=24, pady=24)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # ⌘Q and the app-menu Quit bypass WM_DELETE_WINDOW on macOS.
        try:
            self.createcommand("tk::mac::Quit", self._on_close)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.quit()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
