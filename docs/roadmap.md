# Karaoke Grabber — Roadmap & Feature Requests

**Status:** BACKLOG. Nothing here is planned into a milestone yet; the
current product is defined in [product_spec.md](product_spec.md).
**Date:** 2026-10-06
**Owner:** markstahl

Work not yet in the product falls into two groups:

- **Roadmap.** Planned. Fairly sure these will happen.
  They're listed in rough priority order, which can differ from the
  numeric order of the IDs.
- **Feature requests.** Ideas worth considering, not committed.

IDs are stable: **R#** for Roadmap and **FR#** for Feature requests. An
item keeps its ID if it moves between groups. When an item is picked up,
it becomes part of the product spec and architecture, gets a milestone in
the build plan, and is removed from here (R2 Transpose is now F17,
milestone M6).

---

## Roadmap

### R3. Keep the Homebrew tools up to date

*(Highest priority: planned next.)*

Karaoke Grabber relies on four Homebrew tools: **yt-dlp**, **ffmpeg**,
**deno** and **rubberband**. R3 keeps all of them current without you
thinking about it.

- **On startup**, in the background, check Homebrew for newer versions
  (`brew outdated --json=v2 yt-dlp ffmpeg deno rubberband`). Anything
  outdated is upgraded with `brew upgrade` automatically. A status line
  shows "Updating yt-dlp…", and Fetch waits while yt-dlp is being
  upgraded, since that's the one that matters for downloads. ffmpeg
  upgrades can take a few minutes because Homebrew may pull in many
  dependencies, so they run without blocking anything.
- **When a download fails**, immediately check whether yt-dlp is outdated.
  - If it is: upgrade it and retry the download once.
  - If it isn't: show a warning (with the tool output under Details) and
    fail.
- Homebrew's public JSON API (`formulae.brew.sh/api/formula/<name>.json`)
  can be used as a fast "latest version" lookup without running
  `brew update` first.

### R11. Click track

*(High priority: planned right after R3.)*

Mix a metronome click into the saved MP3 (and the preview) so the track can
be rehearsed or played along with: a click on every beat, a louder or
higher one on beat 1.

**Preliminary research: feasible, medium-hard.** Mixing is trivial,
steady tempo is easy, and tempo changes are the hard part. Roughly 1–2
days for a steady-tempo click, plus 3–5 days if tempo changes and
retards must be right.

**1. Find the tempo and beat times.** This is the hard part.

| Option | Install | Beat times | Tempo changes | Verdict |
|---|---|---|---|---|
| Pure Python (no new dependencies): ffmpeg decodes to mono PCM, then onset envelope, autocorrelation for the tempo, and a dynamic-programming beat tracker (Ellis 2007) | none | yes | partly: a DP tracker follows gradual drift | Fine for steady karaoke tracks (most are MIDI-style, with a locked tempo). Weakest on rubato. |
| **aubio** (`aubiotrack`, Homebrew) | `brew install aubio` (pulls numpy + Python as dependencies) | yes, in seconds | causal tracker, slow to follow changes | Easiest tool, mediocre accuracy. |
| **librosa** `beat_track` | NumPy, SciPy, numba, soundfile (large) | yes | weak: published comparisons find it good for an average BPM but poor on changing tempo | Not worth the weight over the pure-Python option. |
| **madmom** (RNN + DBN beat/downbeat) | needs a compiler and old build tooling; poorly maintained, unlikely to build on Python 3.14 | yes, plus downbeats | best classical option | Accurate but fragile. Its DBN has a non-commercial licence, fine for personal use. |
| **beat_this** (JKU, 2024, no DBN post-processing) or **BeatNet** | PyTorch, hundreds of MB | yes, plus downbeats | good (no fixed-tempo assumption in beat_this) | Best accuracy by far; heavy for a PyInstaller `.app`. A separate optional "accurate mode" could use it. |
| **Essentia** `RhythmExtractor2013` | pip wheel; Python 3.14 wheels uncertain | yes | statistics over the whole track; follows tempo changes poorly | Reasonable alternative to madmom if a wheel exists. |

Recommended start: the pure-Python tracker, which keeps "no runtime
dependencies", with the beat list as the interface. A better tracker can
later replace it without touching the rest.

**2. Align the clicks.** Make the beat list explicit and let the user fix
it. A **Click** row shows the detected BPM, a **Nudge** (offset in ms, in
case the first beat is detected on the wrong side of the pickup), and a
**Beat 1** choice: which of the first beats is the downbeat, plus the time
signature (3, 4, 6). Count-in clicks before the music starts would need
beats before the first detected one, extrapolated at the opening tempo.
Beat times come from the original download, so they stay valid for any
trim: subtract the trim start. Transposing doesn't change tempo, so the
beat list is cached per video, next to the audio. Verification is by
ear and by a listening test on a handful of real tracks, plus a synthetic
test (a generated track at a known BPM, checked to a few ms).

**3. Inject the clicks.** Easy and already proven.

- Render the click track from the beat list with the standard library
  (`wave` + `array`: a ~20 ms 1 kHz decaying burst at each time, 48 kHz),
  or for a fixed tempo a single ffmpeg `aevalsrc` expression.
- Mix with ffmpeg: `[music][clicks]amix=inputs=2:normalize=0:duration=first`
  (`normalize=0` exists in the installed ffmpeg 9, so the music level is
  untouched). Tested here: output length and level are right.
- Click gain slider, and an option for **click on one side only** (click
  in the left channel, music in both, which is what in-ear monitor users
  usually want). Add the click after the fades so it isn't faded away.
- The preview WAV gets the same click, so you hear it before saving. The
  saved file name gets a suffix, e.g. `… - AUDIO + click.mp3`.
- Avoid ffmpeg's `adelay` per beat; it is clumsy with hundreds of beats.

**4. Corner cases.**

- **Tempo change or retard (ritardando).** A tracker that returns every
  beat time (not one BPM) follows gradual change by construction: the
  click is drawn at each detected beat. Check that the interval between
  clicks never jumps by more than ~25% between beats, and flag the track
  as "tempo not steady" when it does. Expect errors at the final retard,
  at fermatas (held notes) and at key changes with a new tempo. A way to
  fix these by hand (drag or delete a beat on the R6 waveform, or edit
  the list) is the realistic answer; automatic perfection isn't.
- **Half or double tempo** is the most common tracker error (a 70 BPM
  ballad reported as 140). Offer ×½ / ×2 buttons next to the BPM.
- **Intro with no beat** (rubato piano, a-cappella intro): start the
  clicks at the first confident beat, or at a time you choose, rather
  than inventing beats.
- **Swing and triplet feel:** beats come out right; subdivisions
  (clicking eighths) wouldn't, so only click the beat.
- **Time-signature changes** (rare in karaoke) can't be detected
  reliably. A manual "beat 1" re-pick covers it.
- **Speed and trim.** Beat times come from the original audio, so a
  trim only shifts them, and a transpose changes nothing. A speed change
  (milestone M7) scales every beat time by 1/speed, so the click follows
  the slowed or sped-up music for free.
- **Silence and fade-out ends:** stop clicking after the last confident
  beat.
- **Long-range sample accuracy** isn't an issue: the click track and the
  music share the 48 kHz clock. `rubberband`'s time-varying map
  (`--timemap`) would matter only for a different feature (tempo change,
  FR3), and it isn't sample-exact either.

*Questions:*

- Is the pure-Python tracker good enough, or is a heavier optional
  "accurate mode" (beat_this) worth a separate milestone?
- Click only on the saved MP3, or also while previewing? (Previewing is
  what makes nudging practical.)
- Should the click replace the count-in/pickup beats before the first
  note, or only run during the music?

### R8. Precise trim values

*(High priority: planned after R11.)*

V1 trims and fades with sliders and shows their values as read-only
seconds. R8 ties each slider handle (trim and fade) to an **editable**
value in seconds (a decimal
number, e.g. `4.35`). Setting either one updates the other: start with the
slider, and if it isn't precise enough, type the exact number. Typed
values are clamped to their slider's range, and End must stay after Start.

### R9. Load audio from a file

*(High priority: planned after R8, ahead of R1.)*

Besides a YouTube link, open an audio file you already have, just to trim,
fade, transpose and save it.

- An **Open file…** button next to Fetch (and ⌘O) picks a local file:
  MP3, M4A/AAC, WAV, AIFF, FLAC, Opus and anything else ffmpeg reads.
- The info card shows the file name and duration (from `ffprobe`). The
  song title is prefilled from the file's title tag, or from its name
  without the extension. There's no thumbnail or channel.
- Trim, fades, transpose, preview, key and Save work exactly as for a YouTube track.
  The original file is never changed: Save always writes a new MP3, and
  the Save dialog starts in the original file's folder.
- Nothing is downloaded or copied into the cache; ffmpeg reads the file
  where it is.

*Question:* also allow dragging a file onto the window? Tk needs the
`tkdnd` extension for that.

### R1. Save to Google Drive

**Default stays local disk.** A control in the save area, e.g. a
**Save to: ◉ This Mac ○ Google Drive** toggle that's remembered between
runs, switches the destination to Drive.

**Planned design (Drive API):**

- **Account binding.** A **Google account: [not connected ▾]** picker
  with "Connect account…". This runs Google's OAuth sign-in for desktop
  apps: your browser opens, you approve, and a local loopback page
  receives the token. The refresh token is stored in the **macOS
  Keychain**, not a file. The picker also offers "Disconnect" and
  "Switch account".
- **Folder picker.** A file-system-style chooser for Drive, with a folder
  tree and a "New Folder" button, built in Tk. Google's own Picker is a
  web widget and doesn't fit a Tk app. The last-used folder is
  remembered. For now there's no special handling of Shared drives; it
  shows My Drive.
- **Upload.** Render the MP3 locally first, then upload with a progress
  bar and Cancel. If the upload fails, the local copy is kept and you're
  told where it is.
- **Libraries:** `google-auth-oauthlib`, `google-api-python-client`, and
  `keyring` (for the Keychain).

**Setup gotchas to resolve in the spec:**

- You'll need a (free) **Google Cloud project** with the Drive API
  enabled and a "Desktop app" OAuth client ID. That's about 10 minutes of
  clicking, done once.
- **Scopes.** `drive.file` (only files the app creates) is the low-friction
  scope, but it can't *browse* your existing folders. A real folder picker
  needs `drive` or `drive.metadata.readonly`, which Google treats as
  restricted or sensitive.
- If the OAuth app is left in **"Testing"** mode, Google **expires the
  refresh token every 7 days**, so you'd have to reconnect weekly.
  Switching the app to "In production" without Google verification avoids
  that. You'd see a one-time "Google hasn't verified this app" warning,
  which is fine for personal use (up to 100 users).

**⭐ Alternative: don't build it.** Install **Google Drive for desktop**
(Google's free sync app) once, outside this project. Drive then mounts as
a normal writable location, `~/Library/CloudStorage/GoogleDrive-<you>/My Drive`,
and appears in the sidebar of **every macOS Save dialog**, including the
one Karaoke Grabber V1 already uses. Saving to Drive then just means
clicking "Google Drive" in the Save dialog. That needs no code, no
OAuth, no Cloud project and no token expiry, and it works offline
(files sync when you're back online).

- What you lose compared with the API design: the Drive app has to be
  installed and running, and there's no in-app account picker. The
  account is chosen in the Drive app itself, which can sign in to several
  accounts at once. Uploads happen in the background, so the app doesn't
  show upload progress.
- If that's acceptable, R1 becomes "install Drive for desktop" plus,
  optionally, a one-click **Save to Drive** shortcut that opens the Save
  dialog in your Drive folder. That's about an hour of work instead of
  several days.

### R7. Song title from the video

V1 prefills the editable song title with the raw YouTube title. R7 cleans it up automatically:

1. yt-dlp's `track` field, which YouTube fills in for some music uploads.
2. Otherwise, clean up the video title: strip karaoke noise such as
   `(Karaoke Version)`, `Instrumental`, `Backing Track`, `with Lyrics`,
   `Lower/Higher Key`, `in the Style of …` and `[HD]`; split on
   `-`, `|` and `–`; and choose the part that looks like the song.
3. Put the result in the editable song title (you can still change it).

The logic is a pure function, unit-tested against real karaoke titles you
supply.

### R4. Ask Claude for the song name

When the R7 heuristic isn't confident, or when you click a "✨ Ask Claude"
button, send the video title, channel and description to Claude and use
the name it returns. This could run through the Claude Code CLI
(`claude -p "…"`, which is already installed and logged in) or the
Anthropic API with an API key. I'll decide which when we spec it. This
pairs naturally with FR1 tier 2: one call can return both the song name
and a key guess.

### R5. Loudness normalize

Make every saved track play at about the same level (ffmpeg `loudnorm`),
so switching tracks at a gig doesn't need a volume grab.

### R6. Waveform view

Draw the track's actual waveform (decoded with ffmpeg) behind the V1 trim
slider on a Tk Canvas, so you can see the intro, the outro and any
silences while you drag the handles.

### R10. Links from other sites

*(Low priority: near the end of the Roadmap.)*

yt-dlp also works with Vimeo, SoundCloud and hundreds of other sites. V1
accepts YouTube links only; R10 lets through any link yt-dlp can handle,
with no promises. Some backing tracks live on SoundCloud.

---

## Feature requests

### FR1. Guess the key

In increasing order of difficulty:

1. **Parse the description and title.** Uploaders like Sing King and
   Karaoke Version often write "Key: Bb" or "(Original Key)". A regex is
   cheap and accurate when the key is there.
2. **Ask Claude** (pairs with R4). Claude can read the title and
   description and use what it knows about the song, e.g. "the original
   key of Defying Gravity is Db". Claude can't listen to audio through the
   API, so if the uploader transposed the track, this guess will be wrong.
3. **Analyze the audio.** A key-detection library such as `librosa`
   (chroma features with Krumhansl key profiles) or `essentia` listens to
   the actual track. It's typically right about 70–80% of the time on
   pop/theater material. It most often confuses relative major/minor and
   fifths, and it adds a large dependency (NumPy, SciPy).

This isn't too hard: tier 1 is an afternoon. Because a guess can be
wrong, it should only be shown as a **hint** next to the dropdown, e.g.
"Suggested: B-flat (from description)", never filled in automatically.
You still pick the key yourself.

### FR2. Download video

Save an MP4 with the on-screen lyrics, trimmed the same way as the audio.

### FR3. Tempo change

Practice slower (or faster) without changing pitch (`atempo`).

### FR4. Auto-suggest trim points

Detect leading and trailing silence or the channel intro (`silencedetect`)
and pre-fill Start/End.

### FR5. Batch / playlist download

Queue several URLs or a whole playlist, e.g. an audition set.

### FR6. Vocal removal

Turn a regular recording into a backing track (Demucs). This is a heavy ML
dependency and slow on a laptop.

### FR7. Add to Music.app

Import each saved track into Music.app automatically, optionally into a
"Karaoke" playlist.

### FR8. Self-contained app

Bundle yt-dlp, ffmpeg and deno inside the `.app` so it runs on a Mac
without Homebrew. This conflicts with R3's Homebrew-based updates.

### FR9. Adjustable MP3 quality

V1 always saves at the best variable bitrate (V0, ~245 kbps). Add a
setting to choose another quality, e.g. constant 320 kbps or a smaller
128 kbps file.

### FR10. Faster previews of very long videos

The preview is one WAV of the whole trimmed range, made in the background.
For a song that's ready in under a second, but for a very long video (a
full concert, say) it can take several seconds; V1 shows "Preparing
preview…" with progress while it waits. If that ever becomes a nuisance,
render the preview in pieces of about 60 s and start playing the first one
at once. Probably never needed for songs.

### FR11. Keep the play buttons responsive while the preview is remade

Every trim or fade change remakes the background preview, and the play
buttons are disabled until it's ready: about half a second for a song,
longer for long tracks or a busy Mac. Ideas, roughly from cheapest to
most work:

- **Queue the press.** Keep the play buttons enabled while the preview is
  being made; a press shows a small "preparing" state on the button and
  playback starts the moment the preview is ready.
- **Reuse the old preview when the change allows it.** Moving the trim end
  with no fade-out, or the trim start with no fade-in, only shortens the
  existing WAV, which is an instant cut instead of a new render.
- **Re-render only what changed.** A fade change affects just the first or
  last few seconds; render those and splice them onto the unchanged middle.
- **Cursor first.** Render the 15 s after the cursor first so playback can
  start almost at once, then the rest of the range.
- **A lighter preview.** Render the preview as 22 kHz mono instead of 48 kHz
  stereo, about an eighth of the data to write. The saved MP3 keeps full
  quality.
