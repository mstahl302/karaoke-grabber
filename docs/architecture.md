# Karaoke Grabber — Architecture

**Status:** DRAFT rev 0.3
**Date:** 2026-10-02
**Owner:** markstahl
**Related:** [product_spec.md](product_spec.md) · [build_plan.md](build_plan.md) · [dev_environment.md](dev_environment.md) · [roadmap.md](roadmap.md)

This document describes how Karaoke Grabber is built. What it does, and
why, is in [product_spec.md](product_spec.md). Machine setup, the repo,
CI and packaging steps are in [dev_environment.md](dev_environment.md),
and the milestone-by-milestone work is in [build_plan.md](build_plan.md).

---

## 1. Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language / UI | **Python 3.14** (python.org build) + **Tkinter on Tk 9** | Same as Music Printer. Tk 9 gives native-looking aqua widgets and PNG support. |
| Downloader | **yt-dlp** (Homebrew), called as a subprocess | The de facto best YouTube downloader, actively maintained. |
| JS runtime | **deno** (Homebrew) | yt-dlp needs a JavaScript runtime to handle YouTube's player challenges. |
| Audio processing | **ffmpeg / ffprobe** (Homebrew), called as a subprocess | Trimming, fades, MP3 encoding (libmp3lame) and preview clips. |
| Playback | **`afplay`** (built into macOS) | Tkinter has no audio playback. |
| Packaging | **PyInstaller** → `Karaoke Grabber.app` | Same as Music Printer. |
| Tests | **pytest**, GitHub Actions | Same as Music Printer. |

Python runtime dependencies: **none beyond the standard library**.

## 2. Principles

- **Thin UI, pure core.** `main.py` holds the Tkinter UI and a small state
  machine. The logic lives in small modules, mostly pure functions, that
  can be tested without Tk, the network or the external tools.
- **External tools via `subprocess`**, the same way Music Printer drives
  `lp`. Command lines are built by pure functions, which are unit-tested,
  and run by thin wrappers, which are mocked in tests.
- **Never block the Tk main thread.** Work runs on worker threads that
  report back through a queue, which the UI drains with `after()`.
  Worker threads never touch widgets. (The `macos-tkinter` skill covers
  this.)

## 3. Module layout

```
main.py                 Tkinter UI + workflow state machine
karaokegrab/
  __main__.py           tiny CLI for M1: python -m karaokegrab URL --key B-flat --start 4.5 --end 339
  tools.py              locate yt-dlp / ffmpeg / ffprobe / deno; report what's missing
  fetch.py              yt-dlp --dump-json → VideoInfo (id, title, channel, duration, thumbnail); title prefills the song title
  download.py           yt-dlp best-audio download into the cache; progress parsing; cancel
  keys.py               the 24 key names in words, e.g. B-flat, C-sharp minor (dropdown + filename)
  naming.py             pure: (song title, key) → "<Song Title> - AUDIO - <key>.mp3", with / and : replaced
  timecode.py           pure: format seconds for the read-only trim values (parsing arrives with R8)
  trim.py               pure: TrimSpec(start, end, fade_in, fade_out) → ffmpeg argv
  render.py             run ffmpeg for final MP3 + preview clips; progress; cancel
  player.py             preview playback via afplay: play from a cursor, stop, report elapsed time
  cache.py              cache paths keyed by video id; prune to last ~10
  settings.py           JSON settings (last save folder, fade defaults) + log file
tests/                  pytest; subprocess mocked; no network
assets/                 icon.svg (source) → icon.icns via make_icon.py
docs/                   product_spec, architecture, dev_environment, roadmap
build.sh / run.sh       PyInstaller build / build-and-open
```

## 4. Workflow and data flow

```
 URL ──Fetch──▶ fetch.py (yt-dlp --dump-json) ──▶ VideoInfo ──▶ info card
                     │
                     └──▶ download.py (yt-dlp -f bestaudio) ──▶ cache/<id>.<ext>
                                                                  │
   Slider/Fades ────▶ trim.py ──▶ ffmpeg argv ──┬──▶ render.py ──▶ preview clip ──▶ player.py (afplay)
                                                 │
   Key ──▶ naming.py ──▶ Save dialog ──▶ path ───┴──▶ render.py ──▶ <path>.part ──rename──▶ <path>.mp3
```

**UI states:**

`Idle → Fetching → Downloading → Ready → Rendering → Saved` (back to
`Ready`). Also `Error`, and `Cancelled → Idle`.

- *Ready* turns on the trim and preview controls. **Save** is enabled
  only when the state is *Ready* **and** a key is selected.
- A new URL resets the song title (to the new YouTube title), the trim slider (to the full length), the fades (to none) and the key.

## 5. Key design decisions

### 5.1 Use the Homebrew tools instead of `import yt_dlp`

yt-dlp breaks whenever YouTube changes something, and fixes ship often.
If PyInstaller froze yt-dlp into the `.app`, every fix would need a
rebuild. Calling the Homebrew copy means a fix is just
`brew upgrade yt-dlp`, which Roadmap R3 automates. This also keeps
ffmpeg out of the bundle, avoiding app size, licensing and code-signing
issues.

**Finder PATH gotcha:** an app launched from Finder doesn't get your
shell's PATH. `tools.py` therefore searches `/opt/homebrew/bin` and
`/usr/local/bin` explicitly, and passes a PATH that includes them to
subprocesses so yt-dlp can find deno and ffmpeg.

### 5.2 Download once, render many

The best audio stream (usually Opus/WebM or M4A) is downloaded into the
cache **as is**, without re-encoding. Every preview and the final save
are separate ffmpeg renders from that one source, so trim changes cost
milliseconds and the audio is encoded to MP3 only once, at save time.

### 5.3 Rendering

- Final save: `ffmpeg -ss <start> -to <end> -i <cache> -af "afade=t=in:d=…,afade=t=out:st=…:d=…" -c:a libmp3lame -q:a 0 -progress pipe:1 <path>.part`,
  then an atomic rename to `<path>`. Cancel kills ffmpeg and deletes the
  `.part` file.
- Previews: the same pipeline (same trim and fades), rendered from the
  cursor position to the trim end into a temp WAV for instant startup, then
  played by `afplay`. `afplay` can't pause or seek, so **Stop** terminates
  it and sets the cursor to where playback had reached (start position +
  elapsed time); **Start** renders again from the cursor. **From start**
  sets the cursor to the trim start; **From end** plays the last 10 s up
  to the trim end.
- The playback cursor is one time value in `main.py` state, drawn on both
  sliders (trim slider: absolute time; fade slider: time relative to the
  trim start), advanced by a Tk `after()` timer while playing, and set by
  clicking either slider's track.
- Fades come from the fade slider as lengths relative to the trim, so
  `trim.py` computes the fade-out start as trimmed length − fade-out
  length. When the trim shrinks, fades are clamped so they never overlap.
  This is unit-tested.

### 5.4 Progress parsing

- yt-dlp runs with `--newline --progress-template "download:PROG|%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s|%(progress.eta)s"`,
  and one line is parsed per update.
- ffmpeg runs with `-progress pipe:1`; `out_time_us` divided by the
  trimmed duration gives the percentage.
- Both parsers are pure functions with tests.

### 5.5 Error handling

- Every subprocess's stdout and stderr is captured and kept for the
  **Details** pane and the log file.
- A yt-dlp failure produces a friendly message ("YouTube download failed
  — yt-dlp may be out of date; run `brew upgrade yt-dlp`") and the
  attempt stops. (R3 later adds: check whether it's outdated, upgrade,
  retry once.)
- On startup, `tools.py` checks for Homebrew, yt-dlp, ffmpeg and deno
  (F16). Missing tools produce a dialog with the one command to run and a
  Copy button; a missing Homebrew points to the README.

## 6. Files on disk

| What | Where |
|------|-------|
| Settings (JSON) + log | `~/Library/Application Support/Karaoke Grabber/` |
| Download cache | `~/Library/Caches/Karaoke Grabber/`, pruned to the last ~10 videos |
| Preview clips | System temp directory, deleted on exit |
| Output | Wherever you choose in the Save dialog |

## 7. Testing

- **Unit:** timecode, naming, keys, trim argv, both progress parsers,
  tool lookup (with a fake filesystem), cache pruning.
- **Flow:** the UI state machine with a real `tk.Tk()` and mocked
  workers. For example: Save stays disabled until a key is chosen, the
  key resets on a new URL, and Cancel cleans up `.part` files.
- **No network in pytest.** A manual `tests/smoke_real_download.py`
  (not collected by pytest) runs the real tools end to end.
- CI details: [dev_environment.md](dev_environment.md).

## 8. Build plan

The V1 milestones (M0–M5), their steps and exit criteria live in
[build_plan.md](build_plan.md).

## 9. Architectural notes for Roadmap items

- **R1 Google Drive (if built):** a new `drive.py` using
  `google-auth-oauthlib` (desktop loopback OAuth),
  `google-api-python-client` and `keyring` (refresh token in the macOS
  Keychain). These would be the first runtime pip dependencies. Uploads
  run on a worker thread from the locally rendered MP3. See roadmap.md
  for the scope and token-expiry gotchas, and the no-code alternative of
  Google Drive for desktop.
- **R8 Precise trim values:** two-way binding between each slider handle
  and an editable Entry (`timecode.parse` + clamping), all in `main.py`
  state, with no engine changes.
- **R2 Transpose:** add `rubberband=pitch=<2^(n/12)>` to the `trim.py`
  filter chain. `keys.py` gains effective_key(governing_key, semitones)
  (B-flat + 2 → C), and naming.py uses the effective key.
- **R3 Updates:** a new `updates.py` that wraps
  `brew outdated --json=v2` and `brew upgrade`, run on a startup worker.
  `download.py` calls it on failure.
- **R7 / R4 Song title:** a new pure `songname.py` (heuristic), then an
  optional Claude call (`claude -p` CLI or the Anthropic API) behind the
  same interface.

## 10. Risks

| Risk | Mitigation |
|------|------------|
| YouTube changes break yt-dlp | Homebrew copy plus `brew upgrade`. Clear error message. R3 automates updating. |
| yt-dlp needs deno | Installed in M0. `tools.py` checks for it and explains if it's missing. |
| Age-restricted or sign-in-only videos | Out of scope for V1. Possible later: `--cookies-from-browser`. |
| A Finder-launched app can't find the tools | Explicit search paths and an augmented PATH (§5.1). Unit-tested. |
