"""``Karaoke Grabber --self-test``: check the whole engine without the window.

Finds the tools, looks up a short video, downloads it into a temporary
cache, transposes it up 2 semitones at 75% speed and saves a 5-second MP3
from that,
printing each step. Run inside the built
app with an empty environment to prove it works the way Finder starts it
(no shell PATH):

    env -i HOME="$HOME" "dist/Karaoke Grabber.app/Contents/MacOS/Karaoke Grabber" --self-test
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from karaokegrab import download, fetch, render, tools, transpose
from karaokegrab.trim import TrimSpec

DEFAULT_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # 19 s, public


def run(url: str = DEFAULT_URL, out=sys.stdout) -> int:
    def say(text: str) -> None:
        print(text, file=out, flush=True)

    say(f"PATH seen by the app: {os.environ.get('PATH', '(none)')}")
    found = tools.locate()
    for name in tools.TOOLS:
        say(f"  {name:10} {found.paths.get(name) or 'MISSING'}")
    if not found.ok:
        say(found.problem())
        return 1
    try:
        info = fetch.fetch_info(found["yt-dlp"], url)
        say(f"lookup ok: {info.title!r}, {info.duration:.0f} s")
        with tempfile.TemporaryDirectory(prefix="karaoke-grabber-selftest-") as tmp:
            root = Path(tmp)
            audio = download.download(found["yt-dlp"], info.id, url, root=root)
            say(f"download ok: {audio.name}, {audio.stat().st_size // 1024} KB")
            shifted = transpose.transpose(found["ffmpeg"], found["rubberband"], audio, 2,
                                          root / "shift2-speed75.flac", info.duration,
                                          tmp_dir=root, speed=75)
            say(f"transpose ok: {shifted.name}, {shifted.stat().st_size // 1024} KB")
            mp3 = root / "selftest.mp3"
            render.render_mp3(found["ffmpeg"], shifted, TrimSpec(0, 5, 0.5, 0.5).clamped(info.duration), mp3)
            say(f"save ok: {mp3.name}, {mp3.stat().st_size // 1024} KB")
    except (fetch.FetchError, download.DownloadError, transpose.TransposeError,
            render.RenderError) as e:
        say(f"FAILED: {e.message}\n{e.details}")
        return 1
    say("self-test passed")
    return 0
