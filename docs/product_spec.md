# Karaoke Grabber — Product Spec

**Status:** DRAFT rev 0.5 — all open questions resolved; the key is optional
**Date:** 2026-10-03
**Owner:** markstahl
**Related:** [architecture.md](architecture.md) · [build_plan.md](build_plan.md) · [dev_environment.md](dev_environment.md) · [roadmap.md](roadmap.md)

---

## 1. Summary

**Karaoke Grabber** is a small, double-clickable macOS app that turns a
YouTube karaoke (backing) track into a trimmed, correctly named MP3 that's
ready to rehearse or perform with.

## 2. Problem

As a working singer, I often find the backing track I need on YouTube.
Getting it into a usable form today means several steps: run a
command-line downloader, convert the audio, trim off the channel intro and
outro in an audio editor, then rename the file to my convention. That's
fiddly, slow, and easy to get wrong in the rush before a rehearsal.

## 3. User & goals

**User:** me, a singer on a single Apple Silicon Mac. I'm comfortable
with simple apps and occasionally with the terminal, but I don't want to
use the terminal for this.

**Goals:**

- Go from a YouTube URL to a trimmed, named MP3 in **under a minute** for
  a typical 4-minute track.
- **No terminal needed** for the everyday workflow.
- Every saved file follows my naming convention:
  **`<Song Title> - AUDIO - <key>.mp3`**, or
  **`<Song Title> - AUDIO.mp3`** when I don't pick a key.

**Non-goals (V1):**

- A general-purpose video downloader, including video, format pickers or
  subtitles.
- Library management, playlists or batch downloads.
- Distributing the app to other people.

## 4. User workflow

1. **Paste** a YouTube link and click **Fetch**.
2. **Confirm** it's the right track from the title, channel, duration and
   thumbnail. The song title is prefilled from YouTube; I tidy it with the
   pencil button if needed.
3. **Trim** by dragging the start and end handles of the trim slider.
   This cuts the channel intro, the "subscribe!" outro, or a count-in I
   don't want. Optionally drag the fade slider's handles in to add a fade
   in and/or out (off by default). Listen with the preview buttons.
4. **Pick the key** from a dropdown, if I want it in the filename. It's
   optional; with no key, the filename leaves it out.
5. **Save.** A standard macOS Save dialog opens with the filename
   prefilled from the song title (and the key, if picked). I adjust it if
   needed and save.

## 5. V1 features

| # | Feature | Requirements |
|---|---------|--------------|
| F1 | **Fetch from URL** | Paste a YouTube URL, then click Fetch or press Return. Show the title, channel, duration and thumbnail. Clear message for an invalid or unavailable URL. |
| F15 | **Editable song title** | Prefilled with the YouTube video title. A pencil button next to the title opens a small sheet with a text field to edit it (Return saves, Esc cancels). Resets for each new URL. The title feeds the prefilled filename (F8). |
| F16 | **Prerequisite check** | On launch, the app checks for Homebrew, yt-dlp, ffmpeg and deno. If any are missing, it says which and shows the one command to run, with a Copy button (e.g. `brew install yt-dlp ffmpeg deno`). If Homebrew itself is missing, it points to the README's setup section. |
| F2 | **Audio only, MP3 out** | Saves high-quality MP3 (best variable bitrate, V0). No video. |
| F3 | **Download once, trim many** | The audio downloads once per URL. Changing the trim points or the key never downloads it again. |
| F4 | **Trim** | A slider allows you to trim the track. Visual representation of trim, with read-only numerical values (in seconds) updated on the fly.<br><br>Trim is applied to the preview (below) and on save. |
| F5 | **Preview by ear** | A row of buttons: **From start** moves the cursor to the trim start and plays. **Start** plays from the cursor. **Stop** pauses and leaves the cursor where it is. **From end** plays the last 10 seconds up to the trim end, leaving the cursor at the end. A playback cursor shows on both sliders, kept in sync; clicking either slider's track moves the cursor there.<br><br>The preview reflects the current trim settings, so it starts and ends based on the trim slider. |
| F6 | **Fades** | A second slider covering only the trimmed range; it updates as the trim changes. Its two handles move in from the ends to set the fade-in and fade-out, shown as read-only seconds relative to the trim, like the trim slider. Off by default (handles at the ends).<br><br>Preview reflects the current fade settings. |
| F7 | **Optional Key dropdown** | 24 keys, written as words: C, D-flat, D, E-flat, E, F, F-sharp, G, A-flat, A, B-flat, B, and C minor, C-sharp minor, D minor, E-flat minor, E minor, F minor, F-sharp minor, G minor, G-sharp minor, A minor, B-flat minor, B minor. Starts at **— none —** (no key) and resets for each new URL; choosing — none — clears a picked key.<br><br>The key is optional: with no key, it's left out of the filename (F8). |
| F8 | **Prefilled filename** | The Save dialog proposes `<Song Title> - AUDIO - <key>.mp3` from the song title (F15) and key, e.g. Defying Gravity - AUDIO - B-flat.mp3, or `<Song Title> - AUDIO.mp3` when no key is picked. V1 doesn't clean up the title automatically. Characters macOS doesn't allow in filenames (/ and :) are replaced. The dialog opens in the last-used folder. |
| F9 | **Save to local disk** | Saves only to the Mac. |
| F10 | **Progress & Cancel** | A full-width progress bar and status text under the Save button, for downloading and saving. Cancel works at every stage and never leaves a half-written file. |
| F11 | **Plain-English errors** | A friendly message, with a **Details** toggle that shows the tool output. If a download fails, the message suggests that yt-dlp may be out of date and how to update it, then the attempt stops. |
| F12 | **Mac app with icon** | `Karaoke Grabber.app` launches from /Applications or the Dock, with its own icon (§7). |
| F13 | **Small conveniences** | "Reveal in Finder" after saving. Space starts and stops preview playback. ⌘S saves. ⌘Q quits cleanly. |
| F14 | **Published on GitHub** | V1 pushed to a private GitHub repo with a meaningful README. See [dev_environment.md](dev_environment.md). |

## 6. UI

A single window (mockup):

![Karaoke Grabber main window mockup](ui_mockup.png)

Top to bottom:

- **URL and Fetch**, then the info card (thumbnail, editable song title with a pencil button, channel, duration) with the optional **Key** dropdown. Everything below is disabled until a fetch succeeds; the sliders and preview become active once the download finishes.
- **Trim:** a slider spanning the whole track. Its two handles set Start and End; under it, the read-only Start and End values in seconds and the trimmed length update as you drag.
- **Fade:** a second slider spanning only the trimmed range, so it rescales whenever the trim changes. Its handles move in from the ends; under it, the read-only fade-in and fade-out lengths in seconds, relative to the trim. Handles at the ends mean no fade, which is the default.
- **Preview:** From start, Start (from the cursor), Stop, From end. A playback cursor shows on both sliders at the same moment in the song.
- **Save:** a full-width **Save MP3…** button. While it's disabled, it says why, e.g. "fetch a video first". The save progress bar, status and Cancel sit beneath it.

## 7. App icon

A rounded-square macOS tile with a deep purple-to-magenta gradient and a
white retro (capsule) microphone, with a small white down-arrow
underneath. It's flat, has no text, and is legible at 16 px. It
deliberately avoids YouTube red and the play-button triangle. Approved;
may be tweaked later.

## 8. Roadmap (after V1)

These are planned but not in V1, listed in priority order. Details,
designs and the uncommitted Feature requests live in
[roadmap.md](roadmap.md).

- **R2 Transpose.** The Key dropdown stays the song's original (governing)
  key. A ± semitone control shifts the track without changing the tempo,
  and the UI shows the resulting effective key, which is also used in the
  prefilled filename.
- **R8 Precise trim values.** Tie each slider handle (trim and fade) to an
  editable value in seconds (a decimal number). Set either one and the other
  updates: start with the slider, then fine-tune the number if it isn't
  precise enough.
- **R9 Load audio from a file.** Open a song I already have (MP3, M4A,
  WAV and so on) instead of a YouTube link, just to trim, fade and save it.
- **R1 Save to Google Drive.** Local disk stays the default; a control
  switches the destination to Drive. The design includes Google account
  sign-in and a Drive folder picker. *Alternative:* install Google Drive
  for desktop and skip building this.
- **R3 Keep yt-dlp & ffmpeg up to date.** Update automatically on startup.
  When a download fails, check for a newer yt-dlp and update and retry.
- **R7 Song title from the video.** Clean up the prefilled YouTube title
  automatically, e.g. strip "(Karaoke Version)" and channel names.
- **R4 Ask Claude for the song name.** An AI-assisted title, used when the
  heuristic isn't sure.
- **R5 Loudness normalize.** Saved tracks all play at a similar volume.
- **R6 Waveform view.** Show the track's waveform behind the trim slider.

## 9. Open questions

None right now.

## Alternatives considered

- **A required key (rejected 2026-10-03).** V1 first made the Key
  dropdown required, with Save disabled until a key was picked, so no
  file could be saved without one. In use it got in the way, so the key
  became optional and is simply left out of the filename when not
  picked.
