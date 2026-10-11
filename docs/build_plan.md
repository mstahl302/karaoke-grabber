# Karaoke Grabber — Build Plan

**Status:** v1.1 shipped 2026-10-11 (M0–M6). v1.0 shipped 2026-10-04 (M0–M5).
**Date:** 2026-10-11
**Owner:** markstahl
**Related:** [product_spec.md](product_spec.md) · [architecture.md](architecture.md) · [dev_environment.md](dev_environment.md) · [roadmap.md](roadmap.md)

This is the working plan: the milestones, the steps in each one, and how
we know each one is done. M0–M5 built v1.0; later milestones are appended
as features come off the roadmap. What the app does is in the product
spec; how it's built is in the architecture doc. Work not yet planned is
in the roadmap.

---

## 1. How we work

- **Milestones in order, M0 → M6.** Each one ends with something you can
  run and with the test suite green, locally and in CI.
- **Git: one local branch per milestone.** Work happens on a local
  branch (e.g. `m1-core-engine`), with as many commits as are useful. When
  the milestone's exit criteria are checked off, the branch is squashed
  into one commit and fast-forwarded onto `main`, so `main` gets one clean
  commit per milestone. Then `main` is pushed to GitHub. Development and
  merging are local; there are no GitHub pull requests.
- **Tests come with the code.** Pure modules get unit tests as they're
  written. UI behavior gets flow tests with a real `tk.Tk()` and mocked
  workers. Nothing in pytest touches the network.
- **Docs stay current.** If the build changes a decision, the spec or
  architecture doc is updated in the same piece of work, along with its
  Claude Doc mirror.
- **Demo at the end of each milestone.** I show you the result (CLI
  output, screenshots, or the running app) before starting the next one.

## 2. Overview

| # | Milestone | Goal | Features | Size |
|---|-----------|------|----------|------|
| M0 | Environment | Tools, repo, skeleton, CI green | F14 (repo) | S |
| M1 | Core engine | URL → trimmed, faded MP3 from the command line | F2, F3, engine for F1/F4/F6/F8 | L |
| M2 | Basic UI | Fetch, title, key, save the full track from the window | F1, F7, F8, F9, F10, F11, F15 | L |
| M3 | Trim, fade + preview | Both sliders, playback cursor, preview buttons | F4, F5, F6 | L |
| M4 | Polish | Shortcuts, Finder reveal, prerequisite check, error details, cache, robustness | F11, F13, F16 | M |
| M5 | Ship | Icon, `.app`, README, user guide, `v1.0` on GitHub | F12, F14 | M |
| M6 | Transpose (v1.1) | Shift a track by semitones, effective key in the name, `v1.1` | F17; F3, F5, F8, F10, F16 | L |

Size is a rough relative effort: S (an hour or two), M (half a day),
L (a day or more).

## 3. M0 — Environment

**Goal:** a clean, reproducible setup with a passing (trivial) test in CI.
Details of each step are in [dev_environment.md](dev_environment.md).
Claude runs every M0 step.

- [x] Rename the project folder from `~/Development/youtube-downloader`
      to `~/Development/karaoke-grabber`: update the mirror headers in
      the Claude Docs and `.claude-docs.json`, carry over Claude's project
      memory, and continue in a session opened in the new folder
- [x] `brew install yt-dlp ffmpeg deno`, then run the verify commands
- [x] Manual toolchain smoke test: download one real track with yt-dlp,
      trim and fade it with ffmpeg, listen to the result
- [x] `git init`, `.gitignore`, LICENSE, README stub
- [x] Create the venv, install the dev requirements, confirm Tk 9
- [x] Skeleton: `main.py`, `karaokegrab/__init__.py`, one passing test
- [x] Create the private GitHub repo, push, confirm CI is green
- [x] Commit `docs/` and `.claude-docs.json`

**Exit criteria:** `python -m pytest` passes locally and in CI; the
smoke-test MP3 plays correctly.

## 4. M1 — Core engine

**Goal:** everything except the window, driven from a tiny CLI:

```bash
python -m karaokegrab "<url>" --key B-flat --start 4.5 --end 339 --fade-out 2
```

Build order follows the dependencies: pure helpers first, then the
modules that run external tools.

| Step | Module | Work | Tests |
|------|--------|------|-------|
| 1.1 | `tools.py` | Find `yt-dlp`, `ffmpeg`, `ffprobe`, `deno` in `/opt/homebrew/bin`, `/usr/local/bin` and `PATH`. Report each missing tool with its `brew install` command. Build the PATH passed to subprocesses. | Fake filesystem: found, missing, Finder-style minimal PATH. |
| 1.2 | `timecode.py` | Format seconds as `4.5 s` and `5:34.5`. (Parsing arrives with R8.) | Rounding, hours, zero. |
| 1.3 | `keys.py` | The 24 key names in dropdown order. | Count, uniqueness, order. |
| 1.4 | `naming.py` | `(song title, key) → "<Song Title> - AUDIO - <key>.mp3"` (no key: `"<Song Title> - AUDIO.mp3"`): replace `/` and `:`, trim and collapse whitespace, cap the length. | Odd characters, empty title, long title. |
| 1.5 | `fetch.py` | `yt-dlp -J --no-playlist <url>` → `VideoInfo` (id, title, channel, duration, thumbnail URL). Fetch the thumbnail as PNG. Friendly errors for invalid, private, or unavailable videos. | Parse saved JSON samples; error mapping. |
| 1.6 | `cache.py` | Cache path per video id, reuse when present, prune to the 10 most recent. | Temp dirs: reuse, prune order. |
| 1.7 | `download.py` | `yt-dlp -f bestaudio` into the cache with `--newline --progress-template`. Parse progress, support cancel (kill the process group, delete partial files). | Progress-line parser; cancel cleanup with a fake process. |
| 1.8 | `trim.py` | `TrimSpec(start, end, fade_in, fade_out)`: validate and clamp (fades never overlap, End after Start). Build ffmpeg argv for the final MP3 and for a preview WAV from a cursor position. | Argv snapshots; fade-out start math; clamping. |
| 1.9 | `render.py` | Run ffmpeg with `-progress pipe:1`, parse progress, write `<path>.part` then rename. Cancel kills ffmpeg and deletes the `.part`. | Progress parser; rename and cleanup with a fake process. |
| 1.10 | `settings.py` | JSON settings (last save folder) and a log file in Application Support. | Load defaults, round-trip, corrupt-file fallback. |
| 1.11 | `__main__.py` | The CLI above, wiring 1.1–1.10 together with text progress. | One end-to-end test with all subprocesses mocked. |

**Exit criteria:** the CLI turns a real URL into a trimmed, faded,
correctly named MP3 that plays in Music.app; a second run with different
trim values doesn't download again; tests and CI are green.

## 5. M2 — Basic UI

**Goal:** the full V1 flow in the window, saving the whole track (no trim
or fade yet).

1. **Window skeleton.** Sections in mockup order (URL, info card, Trim,
   Fade, Preview, Save), with the not-yet-built sections disabled. Minimum
   window size. Follow the `macos-tkinter` skill for Tk 9 on macOS.
2. **Worker pattern.** One background worker at a time, reporting through
   a queue that the UI drains with `after()`. Workers never touch widgets.
3. **State machine.** `Idle → Fetching → Downloading → Ready → Saving →
   Saved`, plus `Error` and `Cancelled`. The state decides which controls
   are enabled.
4. **URL + Fetch (F1).** Return triggers Fetch. Fetch starts the metadata
   lookup, then the download into the cache.
5. **Info card.** Thumbnail, channel and duration from `VideoInfo`.
6. **Editable song title (F15).** Prefilled from the YouTube title. The
   pencil button opens a sheet with a text field: Return saves, Esc
   cancels. Resets for each new URL.
7. **Key dropdown (F7).** Read-only combobox, optional (starts at — none —), resets
   for each new URL.
8. **Save (F8, F9, F10).** Full-width button, disabled with a reason
   ("fetch a video first") until the state is Ready. (The key was
   required at first; it became optional on 2026-10-03.)
   Opens the native Save dialog with the prefilled name in the last-used
   folder, then renders the MP3 with progress and Cancel.
9. **Errors (F11).** A friendly message with a Details toggle showing the
   tool output. A download failure suggests updating yt-dlp.
10. **Flow tests.** Save disabled until a key is chosen; title and key
    reset on a new URL; Cancel leaves no `.part` file; the error path shows
    Details.

**Exit criteria:** from the window, paste → fetch → edit title → pick key
→ save produces a correctly named full-length MP3; Cancel works during
download and save; tests and CI green.

## 6. M3 — Trim, fade + preview

**Goal:** the trimming and listening experience from the mockup.

1. **RangeSlider widget.** A reusable Canvas widget with two handles, a
   highlighted range, and an optional cursor marker. Its pixel ↔ seconds
   math is a pure helper with unit tests. Handles can't cross, and there's
   a minimum gap.
2. **Trim slider (F4).** Spans the whole track. Read-only Start, End and
   trimmed length update while dragging.
3. **Fade slider (F6).** Spans only the trimmed range and rescales when
   the trim changes. Handles move in from the ends. Read-only fade-in and
   fade-out lengths relative to the trim. Fades are clamped so they never
   overlap. Default: no fade.
4. **Playback cursor.** One time value in UI state, drawn on both sliders
   (absolute on the trim slider, relative on the fade slider). Clicking
   anywhere on either slider's track moves the cursor there.
5. **Player (`player.py`, F5).** Render a preview WAV from the cursor to
   the trim end (with the current fades) and play it with `afplay`. A Tk
   timer advances the cursor while playing.
   - **From start:** cursor to the trim start, then play.
   - **Start:** play from the cursor.
   - **Stop:** end playback; the cursor stays where playback reached.
   - **From end:** play the last 10 s up to the trim end.
   - Changing the trim or fades while playing stops playback.
6. **Save uses trim and fades.** The final render applies the same
   `TrimSpec` as the preview.
7. **Tests.** Slider math, fade clamping and rescaling, cursor mapping
   between the two sliders, player state transitions with a fake
   `afplay`.

**Exit criteria:** you can trim off an intro and outro by ear, add fades,
preview from any point, and the saved MP3 matches what the preview
played.

## 7. M4 — Polish

- [x] "Reveal in Finder" after saving (`open -R`) (F13)
- [x] Shortcuts: Return = Fetch, Space = play/pause, ⌘S = Save, ⌘Q quits
      cleanly and kills any running yt-dlp, ffmpeg or afplay (F13)
- [x] Prerequisite check on launch (F16): Homebrew, yt-dlp, ffmpeg and
      deno; a dialog with the one command to run and a Copy button; a
      missing Homebrew points to the README
- [x] Step-by-step progress (F10): one bar runs across the whole Fetch,
      with a short message at each stop, so a long download never looks stuck:
  - "Looking up the video…" at 3%
  - "Getting the thumbnail…" at 8%
  - "Downloading the audio… 45%" from 10% to 95%, with real progress
  - "Finishing…" at 98%, then "Ready." and the bar hides
  - The background preview shows "Preparing preview…" with ffmpeg's real
    progress
  - Saving keeps "Saving… 62%"; a **Cancel** button beside the bar stays in
    view for the whole Fetch and Save
- [x] Details pane and log file wired into every error path (F11)
- [x] Cache pruning on startup
- [x] Remember the last save folder across launches (done in M2)
- [x] Light and dark mode check (the window keeps its light look in Dark
      Mode); window resizing behaves (the title rewraps)
- [x] Edge cases, each with a clear message:
  - Playlist-only links (`playlist?list=…`) rejected at once, before
    yt-dlp spends time listing the playlist. A video link inside a
    playlist still fetches just that video.
  - YouTube links only (youtube.com, youtu.be, m., music., /shorts/);
    other sites get "Only YouTube links for now" (Roadmap R10 lifts this)
  - Only one well-formed `https://` link to a single YouTube video is
    accepted; extra words, channel pages and the like are rejected
  - Videos under 1 s rejected; live, upcoming and just-ended streams
    rejected (done in M1)
  - No network at Fetch (done in M1), and a network drop during the
    download says so instead of suggesting a yt-dlp update
  - Save folder full or not writable: a clear message
  - Quitting during a save leaves no `.part` file
  - Cached audio deleted while the app is open: download it again
  - Real-link check of `youtu.be/…`, `/shorts/…`, `music.youtube.com`,
    `m.youtube.com` and `&t=90s` links

- [x] From the first hands-on test (2026-10-04):
  - Preview prepared in the background after the download and after every
    slider change (a running preparation is killed and restarted); play
    buttons disabled until it's ready; the preview persists, so moving the
    cursor and playing or pausing is instant (F5)
  - One round play/pause button (▶ / ❚❚, no words) between From start and
    From end, replacing Start and Stop (F5)
  - Space works after clicking a slider (F13)
  - Fetch errors in a band right under the link box (F1, F11)
  - Cancel is a button beside the progress bar (F10)

**Exit criteria:** a week of normal use with no crashes or confusing
states; tests and CI green.

## 8. M5 — Ship

1. **Icon (F12).** Draw `assets/icon.svg` from product spec §7 and show it
   for approval. `assets/make_icon.py` renders it with the macOS `sips`
   tool (transparent corners, correct gradients; PyMuPDF turns gradients
   black and Quick Look adds a white background), sizes it with `sips` and
   packs it with `iconutil` into `assets/icon.icns`, which is checked in.
   No Pillow or PyMuPDF needed.
2. **Build.** `build.sh` (PyInstaller, `--windowed`, arm64,
   `--icon assets/icon.icns`) and `run.sh` (create the venv if missing,
   build, open), adapted from Music Printer. Info.plist: bundle id
   `com.mstahl302.karaokegrabber`, name "Karaoke Grabber" (so the menu bar
   doesn't say "Python"), version 1.0. Ad-hoc signed, so the first launch
   needs right-click ▸ Open once.
3. **Prove the built app.** Launch it **from Finder** (not the terminal) to
   prove the Homebrew tools are found without the shell's PATH; run the
   full workflow; quit with ⌘Q and from the Dock; check the
   missing-tools dialog in the built app. Ends with an interactive test.
4. **Docs.** The full README (outline in dev_environment.md §6) with a
   screenshot of the Defying Gravity track, and a USER_GUIDE.md written
   for a singer: the workflow step by step with screenshots, plus "when
   downloads stop working". Both get Claude Doc mirrors.
5. **Install.** Copy the app to /Applications and add it to the Dock
   (approved 2026-10-04).
6. **Release.** Tag `v1.0`, push, confirm CI green. Mark every doc's status
   line as V1 and sync the Claude Docs.

**Exit criteria:** the app launches from the Dock on a clean login and
completes the full workflow; `v1.0` is on GitHub.

**Done 2026-10-04:** the owner confirmed the app from the Dock after a fresh
login, and `v1.0` was tagged and pushed.

## 9. M6 — Transpose (v1.1)

**Goal:** shift a track up or down by semitones without changing its
tempo, hear it in the preview, and save it named with the key you'll hear
(product spec F17; architecture §5.3). Released as `v1.1`.

1. **Setup and a quick trial.** `brew install rubberband`. Time
   `rubberband -p 2` on the Defying Gravity track with its default engine
   and with `--fine` (the newer, slower engine), listen to both, and pick
   one. Confirm it writes FLAC, how it reports progress, and that the
   length is unchanged to the sample.
2. **`keys.py`:** `effective_key(key, n)`, n steps along the chromatic
   list, wrapping; minor stays minor. Tests: every key at every shift from
   −9 to +9, plus the spec's examples (B-flat +2 → C).
3. **`naming.py`:** `(title, key, shift)` → `… - AUDIO - <effective key>.mp3`,
   `… - AUDIO.mp3`, or `… - AUDIO (+2).mp3` / `(−2)`. Tests.
4. **`tools.py`:** rubberband in the tool list; the install command and the
   missing-tools dialog include it. Tests.
5. **`transpose.py`:** the decode argv (ffmpeg → 48 kHz stereo WAV in the
   temp folder) and the rubberband argv; a progress parser; `transpose()`
   running both with cancel, writing `cache/<id>/shift<n>.flac` via a
   `.part` file and keeping only the latest shift. Tests with fake
   processes: argv, progress, cancel cleanup, reuse of the cached shift.
6. **Rendering from the source:** the preview and save render from the
   downloaded audio or the shifted copy. CLI `--transpose N`.
   `--self-test` also transposes. Tests.
7. **UI (F17):** in the Key row, **−**, the shift, **+** and the
   resulting key (e.g. "+2 → C", or "+2" with no key). A new *Transposing*
   state: clicks wait until − / + have been still for 400 ms, a running
   transposition is cancelled, progress reads "Transposing +2… n%", Cancel
   restores the previous shift, then the preview is remade. Disabled until
   the download is in and while busy; resets to 0 for a new URL. The Save
   name uses the effective key. Keys: = / + / keypad + up, − / keypad −
   down, 0 resets; ignored while typing in a text field.
   After the first interactive test: a narrow Key dropdown with short
   names (B♭, C♯m; the filename keeps the words), the Key and Transpose
   row centred across the bottom of the card with fixed widths so the
   window never resizes, and a drawn pencil button (tip down to the left).
8. **Flow tests:** shift changes transpose once and remake the preview;
   rapid clicks make one transposition; Cancel restores the shift; the
   filename uses the effective key; the shift resets on a new URL; a
   transposition failure shows Details and keeps the previous shift; the
   keys transpose but not while typing in the link box.
9. **Docs and mockup:** the README (requirements, usage) and the User's
   Guide (a "Transpose" section with a screenshot), dev_environment.md's
   install command, and their Claude Docs. The product spec, architecture
   and mockup are updated before building starts.
10. **Ship v1.1:** version 1.1; build the app; `--self-test` in the built
    app with `env -i`; reinstall it in /Applications; interactive test;
    tag `v1.1` and push.

**Exit criteria:** a B-flat track raised 2 semitones previews in C at the
same tempo and saves as `<Song Title> - AUDIO - C.mp3`; changing the
shift, Cancel and a new URL behave as specified; tests and CI green;
`v1.1` is on GitHub.

## 10. Feature traceability

Every feature in the product spec, and the milestone that delivers it.

| Feature | Milestone |
|---------|-----------|
| F1 Fetch from URL | M1 (engine), M2 (UI) |
| F2 Audio only, MP3 out | M1 |
| F3 Download once, trim many | M1; M6 (also across shifts) |
| F4 Trim | M1 (engine), M3 (UI) |
| F5 Preview by ear | M3, M4; M6 (transposed preview) |
| F6 Fades | M1 (engine), M3 (UI) |
| F7 Key dropdown (the original key) | M2 |
| F8 Prefilled filename | M1 (naming), M2 (dialog); M6 (effective key) |
| F9 Save to local disk | M2 |
| F10 Progress & Cancel | M2, M4; M6 (transposing) |
| F11 Plain-English errors | M2, M4 |
| F12 Mac app with icon | M5 |
| F13 Small conveniences | M4 |
| F14 Published on GitHub | M0 (repo), M5 (release) |
| F15 Editable song title | M2 |
| F16 Prerequisite check | M1 (`tools.py`), M4 (dialog); M6 (rubberband) |
| F17 Transpose | M6 |

## 11. Open questions

None right now.
