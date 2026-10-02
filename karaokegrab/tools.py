"""Find the external tools (yt-dlp, ffmpeg, ffprobe, deno) and Homebrew.

An app launched from Finder doesn't inherit the shell's PATH, so
/opt/homebrew/bin isn't on it. We search the Homebrew prefixes explicitly,
then PATH, and hand subprocesses a PATH that includes those prefixes so
yt-dlp can find deno and ffmpeg itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Apple Silicon prefix first, then Intel.
SEARCH_DIRS: tuple[str, ...] = ("/opt/homebrew/bin", "/usr/local/bin")

TOOLS: tuple[str, ...] = ("yt-dlp", "ffmpeg", "ffprobe", "deno")

# Homebrew formula that provides each tool (ffprobe ships with ffmpeg).
FORMULA: dict[str, str] = {
    "yt-dlp": "yt-dlp",
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffmpeg",
    "deno": "deno",
}

IsExe = Callable[[str], bool]


def _is_exe(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def search_path(env_path: str | None = None) -> list[str]:
    """The directories searched, in order: Homebrew prefixes, then PATH."""
    if env_path is None:
        env_path = os.environ.get("PATH", "")
    dirs = list(SEARCH_DIRS)
    for d in env_path.split(os.pathsep):
        if d and d not in dirs:
            dirs.append(d)
    return dirs


def find(name: str, env_path: str | None = None, is_exe: IsExe = _is_exe) -> str | None:
    """Full path of executable *name*, or None."""
    for d in search_path(env_path):
        candidate = str(Path(d) / name)
        if is_exe(candidate):
            return candidate
    return None


@dataclass(frozen=True)
class Toolset:
    paths: dict[str, str | None]
    brew: str | None
    missing: list[str] = field(default_factory=list)

    def __getitem__(self, name: str) -> str:
        path = self.paths.get(name)
        if not path:
            raise KeyError(f"{name} not found")
        return path

    @property
    def ok(self) -> bool:
        return not self.missing

    def install_command(self) -> str:
        """The one command that installs everything missing, e.g.
        ``brew install yt-dlp ffmpeg deno``; empty when nothing is missing."""
        formulas: list[str] = []
        for name in self.missing:
            f = FORMULA[name]
            if f not in formulas:
                formulas.append(f)
        return f"brew install {' '.join(formulas)}" if formulas else ""

    def problem(self) -> str:
        """A plain-English description of what's missing, or ''."""
        if self.ok:
            return ""
        names = ", ".join(self.missing)
        if self.brew is None:
            return (f"Missing: {names}. Homebrew isn't installed either; "
                    "see the README's Requirements section to set it up.")
        return f"Missing: {names}. To install, run:\n  {self.install_command()}"


def locate(env_path: str | None = None, is_exe: IsExe = _is_exe) -> Toolset:
    paths = {name: find(name, env_path, is_exe) for name in TOOLS}
    missing = [name for name, p in paths.items() if p is None]
    return Toolset(paths=paths, brew=find("brew", env_path, is_exe), missing=missing)


def subprocess_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """A copy of *env* (default: os.environ) whose PATH starts with the
    Homebrew prefixes, so child tools find each other."""
    out = dict(os.environ if env is None else env)
    out["PATH"] = os.pathsep.join(search_path(out.get("PATH", "")))
    return out
