# Karaoke Grabber

![tests](https://github.com/mstahl302/karaoke-grabber/actions/workflows/ci.yml/badge.svg)

A small macOS app that turns a YouTube karaoke (backing) track into a
trimmed, faded, correctly named MP3 in your key:
`<Song Title> - AUDIO - <key>.mp3` (the key is optional). Paste a link,
trim off the intro and outro by ear, add fades if you like, transpose it
up or down if you sing it in another key, slow it down to learn it, and
save.

![Karaoke Grabber with a track loaded, trimmed and transposed](docs/screenshot_main.png)

**Using the app?** See the **[User's Guide](USER_GUIDE.md)** for a
step-by-step walkthrough. This file is for installing, building and
developing it.

## Requirements

- macOS on Apple Silicon.
- **Homebrew**, the free tool that installs the rest. If you don't have it,
  open Terminal and paste the one-line install command from
  [brew.sh](https://brew.sh), then follow what it prints.
- **yt-dlp, ffmpeg, deno and rubberband**, installed with Homebrew:

  ```bash
  brew install yt-dlp ffmpeg deno rubberband
  ```

  The app finds them in `/opt/homebrew/bin` by itself. If any are missing,
  it says which and shows this command with a Copy button.
- To build the app: **Python 3.14 from
  [python.org](https://www.python.org/downloads/macos/)**. It ships Tk 9,
  which the window needs; the system `/usr/bin/python3` (3.9, Tk 8.5)
  won't do.

## Install / build

```bash
git clone https://github.com/mstahl302/karaoke-grabber.git ~/Development/karaoke-grabber
~/Development/karaoke-grabber/run.sh
```

`run.sh` creates the virtualenv the first time, builds
`dist/Karaoke Grabber.app` and opens it. Then drag the app from
`dist/` to `/Applications` and, if you like, to the Dock.

The app isn't signed by an Apple developer account, so the **first**
time you open it macOS may refuse. Right-click (or Control-click) the
app, choose **Open**, then **Open** again. After that it opens normally.

## Using it

1. Paste a YouTube video link and press **Fetch** (or Return).
2. Drag the **Trim** handles to cut the intro and outro; drag the **Fade**
   handles in for a fade-in or fade-out.
3. Listen with **From start**, the round play/pause button (or Space) and
   **From end**.
4. Optionally pick the **Key**, transpose with **−** / **+** (or the − and
   = keys), set the **Speed** (50–150%, or the [ and ] keys), and tidy the
   title with the pencil.
5. **Save MP3…** (or ⌘S).

The [User's Guide](USER_GUIDE.md) covers each step with pictures.

## When downloads stop working

YouTube changes things now and then, and yt-dlp catches up within days.
If fetching or downloading starts failing with "yt-dlp may be out of
date", update it:

```bash
brew upgrade yt-dlp
```

If it still fails, run `brew upgrade` to update everything.

## What this project does and doesn't contain

**This project contains no code that scrapes, reverse-engineers or
otherwise accesses YouTube.** All of that is done by separate, independent
open-source projects, chiefly [yt-dlp](https://github.com/yt-dlp/yt-dlp)
(with [ffmpeg](https://ffmpeg.org) and [deno](https://deno.com)), which you
install yourself and which this app simply runs as external programs. Keeping
that line clean is deliberate, so this code stays free of legal entanglements.
Karaoke Grabber itself only trims, fades, names and saves audio that those
tools hand it. You are responsible for using it in line with the terms of the
sites you use and the laws where you live.

## Project layout

```
main.py                 Tkinter UI + workflow state machine; --self-test
karaokegrab/
  __main__.py           command-line version: python -m karaokegrab URL --key B-flat --transpose 2 --speed 75 --start 4.5 --end 339
  tools.py              find yt-dlp / ffmpeg / ffprobe / deno / rubberband; report what's missing
  links.py              check the pasted link: one well-formed YouTube video link
  fetch.py              yt-dlp -J → VideoInfo (title, channel, duration, thumbnail)
  download.py           best-audio download into the cache; progress; cancel
  transpose.py          shift the pitch and change the speed with rubberband; cache the copy
  cache.py              one cache folder per video; keep the 10 most recent
  trim.py               trim and fades → ffmpeg command lines (pure)
  render.py             run ffmpeg for the saved MP3 and the preview WAV
  player.py             play the preview with afplay; cut it at the cursor
  keys.py, naming.py,   key names and the key you hear, the file name, time formatting (pure)
  timecode.py
  rangeslider.py        the two-handle Trim and Fade sliders
  widgets.py            colour-filled and round buttons that work on macOS
  proc.py               run one tool: streamed output, cancel
  settings.py           last save folder + log file
  selftest.py           check the whole engine without the window
tests/                  pytest; every subprocess faked, no network
assets/                 icon.svg (source) → icon.icns via make_icon.py
docs/                   product spec, architecture, build plan, dev environment, roadmap
build.sh / run.sh       PyInstaller build / build and open
```

Settings and the log live in `~/Library/Application Support/Karaoke Grabber/`;
downloads are cached in `~/Library/Caches/Karaoke Grabber/`.

## Develop & test

```bash
cd ~/Development/karaoke-grabber
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python main.py
.venv/bin/python -m pytest
```

- **Command line:**
  `.venv/bin/python -m karaokegrab "<url>" --key B-flat --transpose 2 --speed 75 --start 4.5 --end 339 --fade-out 2`
  (`--help` lists everything).
- **Self-test** (tools, a real lookup, download, transpose and slow down, and save, no window). Run
  inside the built app with an empty environment, it proves the app works
  the way Finder starts it:

  ```bash
  env -i HOME="$HOME" "dist/Karaoke Grabber.app/Contents/MacOS/Karaoke Grabber" --self-test
  ```

- **Icon:** edit `assets/icon.svg`, then rebuild `assets/icon.icns` with
  `python3 assets/make_icon.py` (uses the macOS `sips` and `iconutil`).
- CI runs the tests on GitHub Actions (Linux, under Xvfb) on every push to
  `main`.

## Docs

[Product spec](docs/product_spec.md) · [Architecture](docs/architecture.md) ·
[Build plan](docs/build_plan.md) · [Dev environment](docs/dev_environment.md) ·
[Roadmap](docs/roadmap.md)

## License

MIT; see [LICENSE](LICENSE).
