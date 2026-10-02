"""Command-line front end for the engine (milestone M1):

    python -m karaokegrab "<url>" --key B-flat --start 4.5 --end 339 --fade-out 2

Looks the video up, downloads its audio once into the cache, then trims,
fades and saves ``<Song Title> - AUDIO - <key>.mp3``. The work runs on a
worker thread, the way the app will run it; Ctrl-C cancels cleanly.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path
from typing import Callable, TextIO

from karaokegrab import cache, download, fetch, keys, naming, proc, render, settings, timecode, tools
from karaokegrab.trim import TrimSpec

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_CANCELLED = 0, 1, 2, 130


class Failure(Exception):
    def __init__(self, message: str, details: str = "", code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.code = code


def _key(text: str) -> str:
    key = keys.lookup(text)
    if key is None:
        raise argparse.ArgumentTypeError(
            f"{text!r} isn't a key. Use one of: {', '.join(keys.KEYS)}")
    return key


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a number of seconds") from None
    if value < 0:
        raise argparse.ArgumentTypeError("times can't be negative")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m karaokegrab",
        description="Turn a YouTube karaoke track into a trimmed, named MP3.")
    p.add_argument("url", help="YouTube video link")
    p.add_argument("--key", required=True, type=_key,
                   help='the song\'s key, as words: e.g. B-flat, "F-sharp minor"')
    p.add_argument("--title", help="song title (default: the YouTube title)")
    p.add_argument("--start", type=_seconds, default=0.0, help="trim start, seconds (default 0)")
    p.add_argument("--end", type=_seconds, default=None, help="trim end, seconds (default: track end)")
    p.add_argument("--fade-in", type=_seconds, default=0.0, help="fade-in length, seconds")
    p.add_argument("--fade-out", type=_seconds, default=0.0, help="fade-out length, seconds")
    p.add_argument("--out", type=Path, default=None,
                   help="folder to save in (default: the last one used, else the current folder)")
    p.add_argument("--overwrite", action="store_true", help="replace an existing file")
    return p


class Console:
    """Prints status lines, and one self-updating progress line."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream
        self._live = False
        self._last = -1

    def say(self, text: str) -> None:
        self.end_progress()
        print(text, file=self.stream, flush=True)

    def progress(self, label: str, fraction: float | None) -> None:
        pct = -2 if fraction is None else int(fraction * 100)
        if pct == self._last:
            return
        self._last = pct
        shown = "…" if fraction is None else f"{pct:3d}%"
        self.stream.write(f"\r{label} {shown}")
        self.stream.flush()
        self._live = True

    def end_progress(self) -> None:
        if self._live:
            self.stream.write("\n")
            self.stream.flush()
        self._live = False
        self._last = -1


def run(args: argparse.Namespace, out: Console, cancel: proc.Cancel) -> Path | None:
    """The whole pipeline. Returns the saved path, None if cancelled."""
    found = tools.locate()
    if not found.ok:
        raise Failure(found.problem(), code=EXIT_USAGE)

    out.say("Looking up the video…")
    try:
        info = fetch.fetch_info(found["yt-dlp"], args.url, cancel=cancel)
    except fetch.FetchError as e:
        raise Failure(e.message, e.details) from None
    if info is None:
        return None
    out.say(f"  Title:    {info.title}")
    out.say(f"  Channel:  {info.channel}")
    out.say(f"  Duration: {timecode.format_seconds(info.duration)}")
    settings.log(f"fetched {info.id} {info.title!r} ({info.duration:.1f} s)")

    audio = cache.find_audio(info.id)
    if audio is not None:
        out.say("Using the cached download.")
    else:
        info_json = fetch.save_info(info, cache.info_path(info.id))
        try:
            audio = download.download(
                found["yt-dlp"], info.id, info_json,
                on_progress=lambda p: out.progress("Downloading", p.fraction),
                cancel=cancel)
        except download.DownloadError as e:
            raise Failure(e.message, e.details) from None
        out.end_progress()
        if audio is None:
            return None
        settings.log(f"downloaded {info.id} → {audio.name}")
        fetch.fetch_thumbnail(found["yt-dlp"], info_json, cache.thumb_stem(info.id), cancel=cancel)
    cache.prune(protect=info.id)

    wanted = TrimSpec(args.start, args.end, args.fade_in, args.fade_out)
    spec = wanted.clamped(info.duration)
    if spec != TrimSpec(wanted.start, wanted.end if wanted.end is not None else info.duration,
                        wanted.fade_in, wanted.fade_out):
        out.say("Note: trim and fades adjusted to fit the track.")
    out.say(f"  Trim:     {timecode.format_seconds(spec.start)} → {timecode.format_seconds(spec.end)}"
            f"  ({timecode.format_seconds(spec.length)})")
    if spec.fade_in or spec.fade_out:
        out.say(f"  Fades:    in {timecode.format_seconds(spec.fade_in)}, "
                f"out {timecode.format_seconds(spec.fade_out)}")

    prefs = settings.load()
    folder = args.out or (Path(prefs["last_save_folder"]) if prefs["last_save_folder"] else Path.cwd())
    folder = folder.expanduser()
    if not folder.is_dir():
        raise Failure(f"The folder {folder} doesn't exist.", code=EXIT_USAGE)
    path = folder / naming.filename(args.title or info.title, args.key)
    if path.exists() and not args.overwrite:
        raise Failure(f"{path} already exists. Use --overwrite to replace it.", code=EXIT_USAGE)

    try:
        saved = render.render_mp3(found["ffmpeg"], audio, spec, path,
                                  on_fraction=lambda f: out.progress("Saving", f),
                                  cancel=cancel)
    except render.RenderError as e:
        raise Failure(e.message, e.details) from None
    out.end_progress()
    if saved is None:
        return None
    settings.save({**prefs, "last_save_folder": str(folder.resolve())})
    settings.log(f"saved {saved}")
    return saved


def main(argv: list[str] | None = None, stream: TextIO = sys.stdout,
         runner: Callable[[argparse.Namespace, Console, proc.Cancel], Path | None] = run) -> int:
    args = build_parser().parse_args(argv)
    console = Console(stream)
    cancel = proc.Cancel()
    outcome: dict = {}

    def work() -> None:
        try:
            outcome["path"] = runner(args, console, cancel)
        except Failure as e:
            outcome["failure"] = e
        except Exception as e:  # unexpected: still report, never hang
            outcome["failure"] = Failure(f"Something went wrong: {e}")

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        cancel.set()
        worker.join()

    console.end_progress()
    if "failure" in outcome:
        f: Failure = outcome["failure"]
        console.say(f"Error: {f.message}")
        if f.details:
            settings.log("error: " + f.message + "\n" + f.details)
            console.say(f"(Details are in the log: {settings.LOG_PATH})")
        return f.code
    if outcome.get("path") is None:
        console.say("Cancelled.")
        return EXIT_CANCELLED
    console.say(f"Saved: {outcome['path']}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
