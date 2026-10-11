# Karaoke Grabber — Architecture

**Status:** v1.2 shipped 2026-10-11 (adds speed, F18). v1.1 shipped 2026-10-11 (transposition, F17); v1.0 shipped 2026-10-04.
**Date:** 2026-10-11
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
| Audio processing | **ffmpeg / ffprobe** (Homebrew), called as a subprocess | Decoding, trimming, fades, MP3 encoding (libmp3lame) and preview clips. |
| Pitch and speed | **rubberband** (Homebrew command-line tool), called as a subprocess | Studio-quality pitch shift without changing tempo, and tempo change without changing pitch, in one pass. A small install; ffmpeg's own `rubberband` filter would need Homebrew's `ffmpeg-full`, about 100 extra packages. |
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
main.py                 Tkinter UI + workflow state machine; --self-test
karaokegrab/
  __main__.py           command-line version: python -m karaokegrab URL --key B-flat --transpose 2 --speed 75 --start 4.5 --end 339
  tools.py              locate yt-dlp / ffmpeg / ffprobe / deno / rubberband; report what's missing
  links.py              pure: one well-formed http(s) link only; YouTube video links only; spot playlist-only links
  fetch.py              yt-dlp -J → VideoInfo (id, title, channel, duration, thumbnail); title prefills the song title
  download.py           yt-dlp best-audio download into the cache; progress parsing; cancel
  transpose.py          prepare the cached audio for a shift and a speed with rubberband (via a decoded WAV); cache the result; progress; cancel
  keys.py               pure: the 24 key names in words (filename) and short (dropdown: B♭, C♯m); the key you hear after a shift
  naming.py             pure: (song title, key?, shift, speed) → "<Song Title> - AUDIO - <key>.mp3", "… - AUDIO.mp3", "… - AUDIO (+2).mp3", "… - AUDIO - C (75%).mp3", "… - AUDIO (+2, 75%).mp3"; / and : replaced
  timecode.py           pure: format seconds for the read-only trim values (parsing arrives with R8)
  trim.py               pure: TrimSpec(start, end, fade_in, fade_out) → ffmpeg argv; scaling the spec from the song's timeline onto a sped-up or slowed-down copy
  render.py             run ffmpeg for the final MP3 and the preview WAV; progress; cancel
  player.py             preview playback via afplay; cut the preview at the cursor; report elapsed time
  cache.py              one cache folder per video id (audio, info.json, thumb.png, processed audio); prune to last ~10
  proc.py               run one external tool: stream stdout, keep stderr, cancel (kills its process group)
  settings.py           JSON settings (last save folder) + log file
  selftest.py           check the tools and a real lookup, download, transpose + speed change and save, without the window
  widgets.py            colour-filled Label-based button, round play/pause button and pencil button (aqua ignores tk.Button colours)
  rangeslider.py        two-handle Canvas slider with a cursor marker (Trim and Fade); pixel ↔ seconds math is pure
tests/                  pytest; subprocess mocked; no network
assets/                 icon.svg (source) → icon.icns via make_icon.py
docs/                   product_spec, architecture, build_plan, dev_environment, roadmap
build.sh / run.sh       PyInstaller build / build-and-open
```

## 4. Workflow and data flow

```
 URL ──Fetch──▶ fetch.py (yt-dlp -J) ──▶ VideoInfo ──▶ info card
                     │
                     └──▶ download.py (yt-dlp -f bestaudio) ──▶ cache/<id>/audio.<ext>
                                                                    │
   Transpose n, speed s ─────────────────────────▶ transpose.py ────┤ n = 0, s = 100%: the audio as downloaded
                                           (ffmpeg → WAV, rubberband    │ otherwise: cache/<id>/shift<n>-speed<s>.flac
                                            -p n -T s, → 16-bit FLAC)   ▼
                                                                      source
                                                                        │
   Sliders/Fades ─▶ trim.py (÷ s) ─▶ ffmpeg argv ──┬──▶ render.py ──▶ preview WAV ──▶ player.py (afplay)
                                                    │
   Key + n + s ──▶ keys.py ──▶ naming.py ──▶ Save dialog ──▶ path ──┴──▶ render.py ──▶ <path>.part ──rename──▶ <path>.mp3
```

**UI states:**

`Idle → Fetching → Downloading → Ready → Saving → Saved` (back to
`Ready`), and `Ready ⇄ Preparing audio`. Also `Error`, and `Cancelled → Idle`.

- *Ready* turns on the trim, transpose, speed and preview controls and
  enables **Save**. The key is optional.
- *Preparing audio* makes the source for a new shift or speed; the
  sliders, preview and Save wait, and the progress bar and Cancel show.
  Cancel goes back to *Ready* with the previous shift and speed.
- Cancel during Fetching or Downloading clears the info card and goes to
  *Cancelled*. Cancel during Saving keeps the download and goes back to
  *Ready*, so you can save again.
- A new URL resets the song title (to the new YouTube title), the trim slider (to the full length), the fades (to none), the key (to none), the shift (to 0) and the speed (to 100%).

## 5. Key design decisions

### 5.1 Use the Homebrew tools instead of Python packages

yt-dlp breaks whenever YouTube changes something, and fixes ship often.
If PyInstaller froze yt-dlp into the `.app`, every fix would need a
rebuild. Calling the Homebrew copy means a fix is just
`brew upgrade yt-dlp`, which Roadmap R3 automates. The same goes for
ffmpeg and rubberband: keeping them out of the bundle avoids app size,
licensing and code-signing issues.

**Finder PATH gotcha:** an app launched from Finder doesn't get your
shell's PATH. `tools.py` therefore searches `/opt/homebrew/bin` and
`/usr/local/bin` explicitly, and passes a PATH that includes them to
subprocesses so yt-dlp can find deno and ffmpeg.

### 5.2 Download once, process once per setting, render many

The best audio stream (usually Opus/WebM or M4A) is downloaded into the
cache **as is**, without re-encoding. The download reuses the metadata
saved by Fetch (`--load-info-json`), so YouTube is looked up only once per
URL.

Everything after that renders from one **source**: the downloaded audio
when the shift is 0 and the speed 100%, otherwise a processed copy of the
whole track made once for that shift and speed (§5.3). Every preview and the final save are separate
ffmpeg renders from the source, so trim and fade changes cost
milliseconds, and the audio is encoded to MP3 only once, at save time.

### 5.3 Transposition and speed

- **One processed copy of the whole track.** Pitch shifting and tempo
  change are the slow steps, so they aren't part of each render.
  `transpose.py` decodes the cached audio to a 48 kHz stereo WAV with
  ffmpeg, runs `rubberband -p <n> -T <s>` on it (pitch in semitones, tempo
  as a fraction: 0.75 for 75%; one pass does both), converts rubberband's
  24-bit output to 16-bit FLAC, and keeps the result as
  `cache/<id>/shift<n>-speed<s>.flac` (e.g. `shift2-speed75.flac`). A
  shift alone keeps the track's length; a speed divides it (75% makes a
  4:00 song 5:20). rubberband's default (R2) engine shifts a 5-minute
  song in about 12 s; slowing it to 50% takes about 20 s. Its finer R3
  engine (`--fine`) took 80 s for a shift alone, too long to wait for. A
  copy is about 5 MB per minute of output (a 5-minute song at 50% makes
  about 50 MB).
- **Only the latest copy is kept** per video, besides the download
  itself: going back to 0 and 100% needs nothing, and another setting
  takes a few seconds to make. The temporary WAV is deleted straight
  away.
- **Changing the shift or the speed** pauses playback, waits until the
  controls have been still for 600 ms, cancels a preparation already
  running, makes the copy (unless it's the one already cached), then
  remakes the preview. Progress comes from rubberband's own percentage
  output.
- **The speed box.** A `ttk.Spinbox` from 50 to 150 in steps of 5 with a
  "%" label, on the Key row after a gap. Its arrows go through the same
  600 ms wait as − / +. A typed value is applied on Return or when the box
  loses focus: whole numbers are clamped to 50–150, anything else
  restores the last value.
- **The song's timeline.** Trim, fades and the playback cursor are always
  positions in the song as published, whatever the speed, so changing the
  speed never moves a trim point. Renders divide them by the speed to
  find the same moment in the processed copy (`TrimSpec.scaled(1 / s)`),
  so fades stretch with the music; the player's position is multiplied
  back, so the cursor moves at the song's pace. "From end" plays the last
  10 s as heard. The trimmed length shows the saved length too when the
  speed isn't 100%.
- **The key you hear.** The 12 major and 12 minor keys in `keys.py` are
  each listed in chromatic order from C, so the effective key is the
  entry *n* steps along, wrapping around: B-flat + 2 → C,
  A minor − 3 → F-sharp minor. Spellings always come from the Key list.
  `naming.py` uses the effective key; with no key and a shift, it adds
  "(+2)" or "(-2)" instead, with a plain hyphen so it's easy to type. The
  window shows a real minus sign (−2). A speed other than 100% joins the
  brackets: "C (75%)", "(+2, 75%)", "(75%)".

### 5.4 Rendering

- Final save: `ffmpeg -ss <start> -t <length> -i <source> -af "afade=t=in:st=0:d=…,afade=t=out:st=…:d=…" -c:a libmp3lame -q:a 0 -progress pipe:1 -f mp3 <path>.part`,
  then an atomic rename to `<path>`. Cancel kills ffmpeg and deletes the
  `.part` file.
- Previews: one WAV of the whole trimmed range (same source, trim and
  fades as the save), rendered in the background as soon as the source is
  ready and again after every trim, fade, shift or speed change. A change kills a
  render in progress; while a handle is being dragged, the new render
  waits until it has been still for 250 ms. The play buttons are disabled
  until the preview is ready (about 0.4–0.7 s for a song).
- `afplay` can't seek, so playing from the cursor cuts the tail of the
  preview WAV from that point (`player.slice_wav`, a byte copy of a few
  milliseconds) and plays that; pause kills `afplay` and keeps the cursor
  where playback reached. The preview itself survives pausing, moving the
  cursor and saving, so replaying is instant.
- The preview render keeps the source timestamps (`-copyts`), with the
  fades at their absolute times in the track, so it is sample-for-sample
  the matching part of the final render. **From start** plays from the
  trim start, the round button plays from the cursor (or the trim start if
  the cursor is at the end), **From end** plays the last 10 s. Clicking a
  slider's track while a preview plays continues from there.
- The playback cursor is one time value in `main.py` state, drawn on both
  sliders (trim slider: absolute time; fade slider: time relative to the
  trim start), advanced by a Tk `after()` timer while playing, and set by
  clicking either slider's track.
- Fades come from the fade slider as lengths relative to the trim, so
  `trim.py` computes the fade-out start as trimmed length − fade-out
  length. When the trim shrinks, fades are clamped so they never overlap.
  This is unit-tested.

### 5.5 Progress parsing

- yt-dlp runs with `--newline --progress-template "download:PROG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.eta)s"`,
  and one line is parsed per update. The exact total is used when yt-dlp
  knows it, otherwise the estimate.
- ffmpeg runs with `-progress pipe:1`; `out_time_us` divided by the
  expected duration gives the percentage.
- rubberband prints its progress as a percentage; preparing audio shows
  the decode as the first 10%, rubberband as the next 85% and the 16-bit
  conversion as the last 5%.
- All three parsers are pure functions with tests.

### 5.6 Error handling

- Every subprocess's stdout and stderr is captured and kept for the
  **Details** pane and the log file.
- A yt-dlp failure produces a friendly message ("YouTube download failed
  — yt-dlp may be out of date; run `brew upgrade yt-dlp`") and the
  attempt stops. (R3 later adds: check whether it's outdated, upgrade,
  retry once.)
- On startup, `tools.py` checks for Homebrew, yt-dlp, ffmpeg, deno and
  rubberband (F16). Missing tools produce a dialog with the one command to
  run and a Copy button; a missing Homebrew points to the README.
- Links are checked on the Tk thread before any yt-dlp call (`links.py`):
  the box must hold exactly one well-formed `http(s)://` link to a single
  YouTube video. Anything else, playlist-only links (yt-dlp would first
  list the whole playlist) and other sites are rejected at once.
- Fetch problems (a bad link, lookup or download failures, missing tools)
  show in a band right under the link box, with their own **Details**;
  save, transpose, speed and preview problems use the status line at the
  bottom. A failed preparation goes back to the previous shift and speed.
- Download and save failures are told apart: a network drop, a full disk
  or an unwritable folder each get their own message instead of
  "update yt-dlp". Every error keeps the tool output for **Details** and
  the log.
- If the cached audio disappears while the app is open (macOS can clear
  caches), Preview, Transpose, Speed or Save downloads it again (or
  remakes the processed copy) and then carries on.
- Quitting during a save cancels ffmpeg, waits briefly for the worker and
  deletes the `.part` file; quitting while preparing audio deletes the
  half-made copy.

### 5.7 Progress and appearance

- One progress bar runs across the whole Fetch, with a message at each
  stop: looking up (3%), thumbnail (8%), downloading (10–95%, real
  progress), finishing (98%). Preparing audio shows "Transposing +2…",
  "Changing the speed to 75%…" or "Preparing +2 at 75%…" with real
  progress, and the background preview "Preparing preview…". The bar
  is hidden when nothing is running. A **Cancel** button sits beside it
  while fetching, preparing audio and saving.
- Clicking anywhere outside a text field takes keyboard focus out of it
  (Canvas sliders don't take focus themselves), and focus leaves the link
  box when a fetch finishes, so the plain-key shortcuts work: **Space**
  plays and pauses; **=** / **+** (and keypad +) and **−** (and keypad −)
  press the transpose + / − buttons, so they share the 600 ms wait; **0**
  sets the shift back to 0; **]** and **[** step the speed by 5% (through
  the same wait) and **`\`** sets it back to 100%. They're bound with
  `bind_all` and ignored while an Entry or the speed box has focus, or the
  control is disabled. ⌘+ / ⌘− are left
  for zoom, as in every Mac app.
- The window keeps its light look in Dark Mode
  (`::tk::unsupported::MacWindowStyle appearance … aqua` on every window),
  because its cards, sliders and buttons use fixed light colours that
  Dark Mode's light-coloured text would make unreadable.

## 6. Files on disk

| What | Where |
|------|-------|
| Settings (JSON) + log | `~/Library/Application Support/Karaoke Grabber/` |
| Download cache: the audio as downloaded, its metadata, thumbnail and the latest processed (transposed and/or sped-up or slowed-down) copy | `~/Library/Caches/Karaoke Grabber/<video id>/`, pruned to the last ~10 videos |
| Preview clips and the WAV decoded for rubberband | System temp directory, deleted after use and on exit |
| Output | Wherever you choose in the Save dialog |

## 7. Testing

- **Unit:** timecode, naming (with and without a key, shift or speed),
  keys (the effective key for every key and shift, minor stays minor),
  trim argv and the timeline scaling at several speeds, transpose argv, the three progress parsers, tool lookup (with a
  fake filesystem), cache pruning.
- **Flow:** the UI state machine with a real `tk.Tk()` and mocked
  workers. For example: Save works without a key, the key and shift reset
  on a new URL, changing the shift transposes once and remakes the
  preview, a speed change keeps the trim points, typed speeds are clamped,
  Cancel while preparing audio restores the previous shift and speed, and
  Cancel cleans up `.part` files.
- **No network in pytest.** `--self-test` runs the real tools end to end
  (lookup, download, transpose and slow down, save); run it inside the built app with
  `env -i` to prove the Finder launch.
- CI details: [dev_environment.md](dev_environment.md).

## 8. Build plan

The milestones, their steps and exit criteria live in
[build_plan.md](build_plan.md): M0–M5 built v1.0, M6 added transposition
for v1.1, and M7 adds speed for v1.2.

## 9. Architectural notes for Roadmap items

- **R3 Updates:** a new `updates.py` that wraps
  `brew outdated --json=v2 yt-dlp ffmpeg deno rubberband` and
  `brew upgrade`, run on a startup worker. `download.py` calls it on
  failure.
- **R8 Precise trim values:** two-way binding between each slider handle
  and an editable Entry (`timecode.parse` + clamping), all in `main.py`
  state, with no engine changes.
- **R9 Load audio from a file:** an **Open file…** control beside Fetch.
  `ffprobe` gives the duration and any title tag, which fill a
  `VideoInfo`-like source with no thumbnail; `audio` points at the file
  itself, so there's no download and no cache copy (a transposed copy
  goes in a cache folder keyed by the file's path). Trim, transpose,
  speed, render, player and naming are unchanged.
- **R1 Google Drive (if built):** a new `drive.py` using
  `google-auth-oauthlib` (desktop loopback OAuth),
  `google-api-python-client` and `keyring` (refresh token in the macOS
  Keychain). These would be the first runtime pip dependencies. Uploads
  run on a worker thread from the locally rendered MP3. See roadmap.md
  for the scope and token-expiry gotchas, and the no-code alternative of
  Google Drive for desktop.
- **R7 / R4 Song title:** a new pure `songname.py` (heuristic), then an
  optional Claude call (`claude -p` CLI or the Anthropic API) behind the
  same interface.

## 10. Risks

| Risk | Mitigation |
|------|------------|
| YouTube changes break yt-dlp | Homebrew copy plus `brew upgrade`. Clear error message. R3 automates updating. |
| yt-dlp needs deno | `tools.py` checks for it and explains if it's missing. |
| Transposed audio sounds unnatural | rubberband is the reference-quality library; shifts are limited to ±9 semitones; you hear the result before saving. |
| Transposing a long track takes a while | Done once per shift and speed, in the background, with progress and Cancel; only the latest copy is cached. |
| Slowed-down audio sounds smeared | The range stops at 50%, where rubberband still sounds natural; you hear it before saving. |
| Slow speeds make big cache files | 16-bit FLAC (half of rubberband's 24-bit output), only the latest copy per video, and the cache keeps ~10 videos. |
| Age-restricted or sign-in-only videos | Out of scope. Possible later: `--cookies-from-browser`. |
| A Finder-launched app can't find the tools | Explicit search paths and an augmented PATH (§5.1). Unit-tested; `--self-test` proves it in the built app. |

## 11. Open questions

None right now.

## Alternatives considered

- **Pitch shifting inside ffmpeg (rejected 2026-10-06).** Homebrew's
  `ffmpeg-full` has the rubberband library built in as an ffmpeg filter,
  so transposing could have been one more filter in each render. It brings
  about 100 extra Homebrew packages, and running the filter on every
  preview would make each one slow. ffmpeg's built-in `asetrate` +
  `atempo` filters need nothing new but sound noticeably worse. The
  rubberband command-line tool became part of the base platform instead,
  making one shifted copy per shift (§5.3).
- **Speed with ffmpeg's `atempo` (rejected 2026-10-11).** `atempo` changes
  the tempo during each render, so there'd be nothing to prepare, but it
  sounds noticeably worse on music than rubberband, and rubberband already
  makes a copy for transposing, so the speed rides along in the same pass.
- **Trim and fades as heard (rejected 2026-10-11).** The sliders could
  show the slowed-down or sped-up track, so every value would be the time
  you hear. But every trim point would move whenever the speed changed,
  and a track trimmed at 100% would need trimming again at 75%. They stay
  on the song's own timeline instead (§5.3).
