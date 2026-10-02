"""Run one external tool: stream its stdout line by line, keep its stderr,
and let another thread cancel it.

Every subprocess in the engine goes through :func:`run`, so tests mock one
function. The child runs in its own process group, so cancelling kills the
tool and anything it started (yt-dlp runs ffmpeg and deno).
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Sequence

from karaokegrab import tools

OnLine = Callable[[str], None]


class Cancel:
    """A cancel flag shared between the UI (or Ctrl-C) and a worker."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def set(self) -> None:
        self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


@dataclass
class Result:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.cancelled

    @property
    def output(self) -> str:
        """Command line plus everything the tool printed, for the Details pane and the log."""
        parts = ["$ " + " ".join(self.argv)]
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append(self.stderr.rstrip())
        return "\n".join(parts)


def _kill_group(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def run(argv: Sequence[str], on_line: OnLine | None = None,
        cancel: Cancel | None = None) -> Result:
    """Run *argv* to completion (or until *cancel* is set). Each stdout line
    goes to *on_line* (without its newline) as it arrives."""
    argv = [str(a) for a in argv]
    p = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        bufsize=1,
        env=tools.subprocess_env(),
        start_new_session=True,
    )
    err_chunks: list[str] = []
    reader = threading.Thread(target=lambda: err_chunks.append(p.stderr.read()), daemon=True)
    reader.start()

    cancelled = threading.Event()
    done = threading.Event()

    def watch() -> None:
        while not done.is_set():
            if cancel is not None and cancel.wait(0.1):
                cancelled.set()
                _kill_group(p)
                return
            if cancel is None:
                done.wait(0.5)

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()

    out_lines: list[str] = []
    assert p.stdout is not None
    try:
        for raw in p.stdout:
            line = raw.rstrip("\r\n")
            out_lines.append(line)
            if on_line is not None and not cancelled.is_set():
                on_line(line)
        returncode = p.wait()
    except BaseException:
        # e.g. KeyboardInterrupt or an on_line error: never leave the tool running.
        _kill_group(p)
        raise
    finally:
        done.set()
    reader.join(timeout=2)
    watcher.join(timeout=2)
    return Result(argv=argv, returncode=returncode, stdout="\n".join(out_lines),
                  stderr="".join(err_chunks), cancelled=cancelled.is_set())
