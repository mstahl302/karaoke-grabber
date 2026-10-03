"""Preview playback through macOS ``afplay``.

``afplay`` can't pause or seek, so a preview is a WAV clip that starts at
the cursor; :class:`Player` plays one clip at a time and reports how far it
has got, which the UI adds to the clip's start to move the cursor. Stop
kills afplay; playing again renders a new clip from the cursor.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

AFPLAY = "/usr/bin/afplay"

Popen = Callable[..., subprocess.Popen]


class Player:
    def __init__(self, afplay: str = AFPLAY, popen: Popen = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.afplay = afplay
        self._popen = popen
        self._clock = clock
        self._proc: subprocess.Popen | None = None
        self._started = 0.0
        self.offset = 0.0        # source time where the playing clip starts

    def play(self, clip: Path, offset: float) -> None:
        """Play *clip*, which starts at source time *offset*."""
        self.stop()
        self._proc = self._popen([self.afplay, str(clip)], stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._started = self._clock()
        self.offset = offset

    @property
    def playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def finished(self) -> bool:
        """True once a clip played to its end by itself (not stopped)."""
        return self._proc is not None and self._proc.poll() is not None

    def elapsed(self) -> float:
        return max(0.0, self._clock() - self._started) if self._proc is not None else 0.0

    def position(self) -> float:
        """The source time being heard right now."""
        return self.offset + self.elapsed()

    def stop(self) -> float | None:
        """Stop playback. Returns the position reached, or None if nothing was playing."""
        if self._proc is None:
            return None
        pos = self.position()
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        return pos

    def reset(self) -> None:
        """Forget a finished clip."""
        self._proc = None
