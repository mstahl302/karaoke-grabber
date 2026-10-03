# Karaoke Grabber — Roadmap & Feature Requests

**Status:** BACKLOG. Nothing here is in V1. Scope for V1 is defined in
[product_spec.md](product_spec.md).
**Date:** 2026-10-03
**Owner:** markstahl

Work after V1 falls into two groups:

- **Roadmap.** Planned. Fairly sure these will happen once V1 ships.
  They're listed in rough priority order, which can differ from the
  numeric order of the IDs.
- **Feature requests.** Ideas worth considering, not committed.

IDs are stable: **R#** for Roadmap and **FR#** for Feature requests. An
item keeps its ID if it moves between groups. When an item is picked up,
it gets its own spec file in `docs/`.

---

## Roadmap

### R2. Transpose (key change)

*(Highest priority: planned first after V1.)*

- The **Key dropdown is the governing key**: the song's original key, as
  in V1.
- A **± semitone** control (e.g. `−2 … +2`, default 0) shifts the track
  without changing the tempo, using ffmpeg's `rubberband` filter
  (Homebrew's plain `ffmpeg` doesn't include it, but `ffmpeg-full` does).
  The preview plays the transposed audio.
- The UI shows the **effective key** next to the control, e.g. "B-flat
  +2 → C". The effective key is what goes into the prefilled filename:
  `Song Title - AUDIO - C.mp3`. Minor keys stay minor, and names use the
  same spellings as the Key dropdown.

*Question:* a range limit (±6)?

### R8. Precise trim values

*(High priority: planned right after R2. The IDs are stable, so this sits out of numeric order.)*

V1 trims and fades with sliders and shows their values as read-only
seconds. R8 ties each slider handle (trim and fade) to an **editable**
value in seconds (a decimal
number, e.g. `4.35`). Setting either one updates the other: start with the
slider, and if it isn't precise enough, type the exact number. Typed
values are clamped to their slider's range, and End must stay after Start.

### R9. Load audio from a file

*(High priority: planned after R8, ahead of R1.)*

Besides a YouTube link, open an audio file you already have, just to trim,
fade and save it.

- An **Open file…** button next to Fetch (and ⌘O) picks a local file:
  MP3, M4A/AAC, WAV, AIFF, FLAC, Opus and anything else ffmpeg reads.
- The info card shows the file name and duration (from `ffprobe`). The
  song title is prefilled from the file's title tag, or from its name
  without the extension. There's no thumbnail or channel.
- Trim, fades, preview, key and Save work exactly as for a YouTube track.
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

### R3. Keep yt-dlp and ffmpeg up to date

- **On startup**, in the background, check Homebrew for newer versions
  of **yt-dlp** and **ffmpeg** (`brew outdated --json=v2 yt-dlp ffmpeg`).
  If either is outdated, run `brew upgrade` on it automatically. A status
  line shows "Updating yt-dlp…", and Fetch waits while yt-dlp is being
  upgraded. ffmpeg upgrades can take a few minutes because Homebrew may
  pull in many dependencies, so they run without blocking anything.
- **When a download fails**, immediately check whether yt-dlp is outdated.
  - If it is: upgrade it and retry the download once.
  - If it isn't: show a warning (with the tool output under Details) and
    fail.
- Homebrew's public JSON API (`formulae.brew.sh/api/formula/<name>.json`)
  can be used as a fast "latest version" lookup without running
  `brew update` first.

### R7. Song title from the video

*(Planned right after R3. The IDs are stable, so this sits out of
numeric order.)*

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
