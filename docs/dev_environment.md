# Karaoke Grabber — Dev Environment

**Status:** v1.1 shipped 2026-10-11 (adds rubberband for transposing).
**Date:** 2026-10-11
**Related:** [product_spec.md](product_spec.md) · [architecture.md](architecture.md) · [build_plan.md](build_plan.md) · [roadmap.md](roadmap.md)

This plan covers setting up the development machine, the project
skeleton, the GitHub repo and the app build (milestones M0 and M5). It
deliberately mirrors **Music Printer** so the two projects feel the same
to work on. Claude runs all of these setup steps; you shouldn't need to
type any commands.

---

## 1. What's on the machine today (checked 2026-10-02)

| Item | Status |
|------|--------|
| Homebrew | ✅ `/opt/homebrew/bin/brew` (Apple Silicon) |
| Python 3.14 (python.org build, Tk 9) | ✅ 3.14.7 at `/Library/Frameworks/Python.framework/…` |
| `yt-dlp` | ❌ not installed |
| `ffmpeg` / `ffprobe` | ❌ not installed |
| `deno` (the JavaScript runtime yt-dlp needs for YouTube) | ❌ not installed (assumed; not checked) |
| Project folder `~/Development/youtube-downloader` | ✅ exists; contains only `docs/`; not a git repo. Renamed to `~/Development/karaoke-grabber` on 2026-10-02 (first M0 step). |

## 2. External tools (Homebrew)

```bash
brew install yt-dlp ffmpeg deno rubberband
```

| Tool | Why |
|------|-----|
| **yt-dlp** | Downloads the audio stream from YouTube. |
| **ffmpeg** (+ `ffprobe`) | Encodes MP3, trims, applies fades, makes preview clips and reads durations. Homebrew's build includes `libmp3lame` (MP3). |
| **deno** | Since late 2025, yt-dlp needs a JavaScript runtime to solve YouTube's player challenges. Without one, many videos fail or only offer low-quality formats. Deno is the runtime yt-dlp recommends. (If `brew install yt-dlp` already installs it as a dependency, this step changes nothing.) |
| **rubberband** | Shifts the pitch for Transpose (F17) without changing the tempo. Plain `ffmpeg` doesn't include the rubberband library (only the much larger `ffmpeg-full` does), so the app runs the small `rubberband` command-line tool instead. |

Previews play through `afplay`, which ships with macOS, so nothing extra
is needed for playback.

Verify:

```bash
yt-dlp --version
```

```bash
ffmpeg -hide_banner -encoders | grep libmp3lame
```

```bash
yt-dlp -v --simulate "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 2>&1 | grep -i -E "js runtime|deno|error"
```

The last command should list Deno as an available JS runtime and show no
errors.

**Staying current:** until the Roadmap update check (R3) exists, run
`brew upgrade yt-dlp` whenever downloads start failing.

### Why use the Homebrew tools instead of bundling them in the `.app`

| | External (Homebrew), **recommended** | Bundled in the `.app` |
|---|---|---|
| Fixing a YouTube breakage | `brew upgrade yt-dlp` | Rebuild the app |
| App size | Small (~20 MB) | Large (ffmpeg alone is 80 MB+) |
| Works on another Mac | Yes, after one setup command; the app's prerequisite check (F16) says which | Yes |
| ffmpeg licensing and code-signing nested binaries | Not our problem | Has to be handled |
| Startup update check (Roadmap) | `brew outdated` / `brew upgrade` | Would need its own updater |

External tools win: updates are one command, and on any other Mac the
app's prerequisite check tells you exactly what to install. A
self-contained build is listed as Feature request FR8 in [roadmap.md](roadmap.md).

## 3. Python

- **Interpreter:** the python.org **Python 3.14** universal2 build, which
  is already installed. It's the same as Music Printer because it ships
  **Tk 9**. Don't use `/usr/bin/python3` (3.9 with Tk 8.5).
- **Virtualenv:** `.venv/` in the project root.
- **Runtime dependencies:** none beyond the standard library (tkinter,
  subprocess, threading, json, pathlib). yt-dlp can convert thumbnails to
  PNG (`--convert-thumbnails png`), which Tk 9 displays natively, so
  Pillow isn't needed. `requirements.txt` still exists, empty apart from a
  comment, to match Music Printer.
- **Dev dependencies** (`requirements-dev.txt`):

```
-r requirements.txt
pyinstaller>=6
pytest>=8
```

The icon is made with tools that ship with macOS (`sips` and `iconutil`,
see `assets/make_icon.py`), so no imaging packages are needed.

Setup:

```bash
cd ~/Development/karaoke-grabber && python3.14 -m venv .venv
```

```bash
.venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/python -c "import tkinter; print(tkinter.TkVersion)"
```

## 4. Project skeleton (created in M0)

```
karaoke-grabber/
  .gitignore            from Music Printer: .venv, build, dist, *.spec, .DS_Store, icon intermediates
  README.md             see §6
  USER_GUIDE.md         (M5) how to use the app, for a singer rather than a developer
  LICENSE               MIT, like Music Printer
  requirements.txt
  requirements-dev.txt
  main.py
  karaokegrab/__init__.py
  tests/
  assets/               icon.svg, make_icon.py, icon.icns (checked in)
  docs/                 product_spec.md, architecture.md, dev_environment.md, roadmap.md
  build.sh              PyInstaller → "dist/Karaoke Grabber.app"
  run.sh                creates the venv if it's missing, builds, opens the app
  .github/workflows/ci.yml
```

`build.sh`, `run.sh` and `make_icon.py` are adapted from Music Printer,
with the name and package changed.

## 5. GitHub

### 5.1 Visibility: "public but not indexed" isn't possible

GitHub has no setting that keeps a public repository out of search
engines. Public repos are crawlable by Google and others, and they also
appear in GitHub's own search. There's no `noindex` option for a repo,
and a `robots.txt` in your repo has no effect. The only way to keep it
out of search is to make it **private**.

**Recommendation: private repo.** It's free and you can still share it
with specific people by inviting them as collaborators. GitHub Actions on
a private repo get 2,000 free minutes a month. The test job runs on
Linux, like Music Printer's CI, and takes about a minute per push, so
we'd stay far below the limit. You can switch the repo to public at any
time later.

**Decision:** private repo. Making it public is deferred.

### 5.2 Repo setup

- Name: `karaoke-grabber` under `mstahl302`, matching the local folder.
- Created with `gh repo create mstahl302/karaoke-grabber --private --source . --push`
  once M0's first commit exists.
- Branch `main`. CI badge in the README.

### 5.3 CI

Copied from Music Printer's `ci.yml`: `ubuntu-latest`, Python 3.14,
`xvfb-run -a python -m pytest -q` (Xvfb gives the UI flow tests a
display). CI doesn't need yt-dlp or ffmpeg, because every subprocess call
is mocked.

A separate smoke test that downloads one real, short video end to end,
`tests/smoke_real_download.py`, is run by hand and isn't collected by
pytest.

## 6. README (part of V1)

The README is aimed at you-in-six-months and anyone you share it with,
and follows Music Printer's structure:

1. **What it is.** One paragraph and a screenshot of the app.
2. **Requirements.** macOS on Apple Silicon, Homebrew,
   `brew install yt-dlp ffmpeg deno rubberband`, and Python 3.14 from python.org
   (with the reason why). Includes how to install Homebrew itself, which
   the app's prerequisite check points to.
3. **Install / build.** Clone, `./run.sh`, then drag the app to
   /Applications. Includes the Gatekeeper "right-click → Open" note for
   first launch.
4. **Using it.** A short version that links to `USER_GUIDE.md`.
5. **When downloads stop working.** `brew upgrade yt-dlp`, and why it
   happens.
6. **Project layout.** The annotated tree from [architecture.md](architecture.md).
7. **Develop & test.** venv, `python main.py`, `python -m pytest`, and
   the icon rebuild steps.
8. **License.**

## 7. Building the app (M5)

- PyInstaller `--windowed --icon assets/icon.icns`, arm64 only. This Mac
  is Apple Silicon and universal2 isn't needed for personal use.
- `Info.plist` gets a stable bundle id, `com.mstahl302.karaokegrabber`,
  so macOS remembers the app's permissions between rebuilds.
- Install by copying `dist/Karaoke Grabber.app` to `/Applications` and
  pinning it in the Dock.
- The app is unsigned or ad-hoc signed, so the first launch needs
  right-click → Open to get past Gatekeeper. This is the same as Music
  Printer.
- **PATH gotcha:** apps launched from Finder don't inherit your shell's
  PATH, so `/opt/homebrew/bin` isn't on it. `karaokegrab/tools.py` looks
  there explicitly, and this is unit-tested.
- Settings and log: `~/Library/Application Support/Karaoke Grabber/`.
- Download cache (full-length audio before trimming):
  `~/Library/Caches/Karaoke Grabber/`, automatically pruned to the most
  recent ~10 tracks.

## 8. M0 checklist

The M0 steps and exit criteria live in [build_plan.md](build_plan.md) §3.

## 9. Open questions

None right now.
