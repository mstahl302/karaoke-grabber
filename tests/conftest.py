"""Keep tests off the real settings, log and cache, and off the network."""

import gc
import json
import tkinter
from pathlib import Path
from typing import Callable

import pytest

from karaokegrab import cache, proc, settings

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    d = tmp_path / "appsupport"
    monkeypatch.setattr(settings, "APP_DIR", d)
    monkeypatch.setattr(settings, "SETTINGS_PATH", d / "settings.json")
    monkeypatch.setattr(settings, "LOG_PATH", d / "karaoke-grabber.log")
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache")
    return d


@pytest.fixture(autouse=True)
def _tk_cleanup():
    """Tk hates multiple Tk() instances per process — clear the leaked
    default root and collect between tests so widgets from a destroyed
    interpreter don't trip the next one."""
    yield
    root = getattr(tkinter, "_default_root", None)
    if root is not None:
        try:
            root.destroy()
        except Exception:
            pass
    tkinter._default_root = None
    gc.collect()


@pytest.fixture
def video_json() -> dict:
    return json.loads((DATA / "video_info.json").read_text())


class FakeRun:
    """Stands in for proc.run. Each handler is (match, action): the first
    whose *match* returns True for the argv runs. *action(argv, on_line,
    cancel)* may emit lines, create files, and returns a proc.Result."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.handlers: list[tuple[Callable, Callable]] = []

    def on(self, match: Callable[[list[str]], bool], action: Callable) -> None:
        self.handlers.append((match, action))

    def __call__(self, argv, on_line=None, cancel=None):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        for match, action in self.handlers:
            if match(argv):
                return action(argv, on_line, cancel)
        raise AssertionError(f"unexpected subprocess: {argv}")


def result(argv, returncode=0, stdout="", stderr="", cancelled=False):
    return proc.Result(argv=list(argv), returncode=returncode, stdout=stdout,
                       stderr=stderr, cancelled=cancelled)


@pytest.fixture
def fake_run(monkeypatch) -> FakeRun:
    fake = FakeRun()
    monkeypatch.setattr(proc, "run", fake)
    return fake
