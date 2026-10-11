# Karaoke Grabber — User's Guide

Karaoke Grabber turns a karaoke (backing) track on YouTube into an MP3
you can rehearse and perform with: trimmed to start and end where you
want, with optional fades, in the key you sing it in, and named the way
you name your tracks.

![The Karaoke Grabber window with a track ready to save](docs/screenshot_main.png)

## Before the first time

Karaoke Grabber uses four free tools that do the downloading and audio
work. If any are missing when it opens, it shows a small window saying
which, with the one command that installs them:

![The window that lists missing tools, with a Copy button](docs/guide_tools.png)

1. Click **Copy**.
2. Open **Terminal** (in Applications ▸ Utilities), paste with ⌘V and
   press Return. It takes a minute or two.
3. Back in Karaoke Grabber, click **Check again**.

If it says Homebrew itself is missing, click **Open brew.sh** and follow
the one-line install there first.

The first time you open the app, macOS may say it can't check it.
Right-click the app, choose **Open**, then **Open** again. You only do
this once.

## Getting a track

1. On YouTube, find the karaoke video and copy its link from the address
   bar (it looks like `https://www.youtube.com/watch?v=…` or
   `https://youtu.be/…`).
2. Paste it into the box at the top of Karaoke Grabber and press Return,
   or click **Fetch**.
3. The progress bar walks through the steps: looking up the video, getting
   the thumbnail, downloading the audio. A song takes a few seconds. You
   can **Cancel** at any time.
4. Check the card: thumbnail, title, channel and length. If it's the wrong
   video, just paste another link.

Only a link to a single YouTube video works. If the box holds anything
else, like extra words, a playlist link, or a link from another site,
Karaoke Grabber says so right under the box:

![A message under the link box explaining why a link was refused](docs/guide_bad_link.png)

## Trimming by ear

- The **Trim** slider covers the whole track. Drag the left handle past
  the channel intro or count-in you don't want, and the right handle in
  from the end to cut the outro. Start, End and the trimmed length show
  underneath.
- After every change, Karaoke Grabber prepares a new preview in the
  background. It takes about half a second for a song, while the play
  buttons are grey.
- Listen:
  - **From start** plays from the trim start, so you hear exactly where
    your track will begin.
  - The **round button** plays from the black cursor, or pauses. **Space**
    does the same.
  - **From end** plays the last 10 seconds, so you hear exactly where it
    ends.
- Click anywhere on either slider's track to move the cursor there, even
  while it's playing.

## Fades

The **Fade** slider covers just the trimmed part. Drag its left handle in
for a fade-in and its right handle in for a fade-out; the lengths show
underneath. Handles at the ends mean no fade, which is the default. Listen
with **From start** and **From end**.

## Title and key

- The title comes from YouTube. Click the purple pencil button to tidy it, for
  example to remove "(Karaoke Version)". Return saves, Esc cancels.
- Pick the **Key** if you want it in the file name. It's optional; leave it
  at "none" and the key is simply left out. The list uses short names
  (B♭ for B-flat, C♯m for C-sharp minor); the file name spells them out.

## Transposing

If you sing the song in a different key, shift it with **Transpose**,
next to the Key:

- Click **+** to raise it a semitone or **−** to lower it, up to 9 either
  way. The tempo stays the same.
- With a key picked, it shows the key you'll hear: a B-flat track at
  **+2 → C**.
- The first time for each shift takes a few seconds while the progress bar
  shows "Transposing +2…". Click several times in a row and it waits until
  you stop. **Cancel** goes back to the shift you had.
- The preview and the saved MP3 are both transposed. Going back to 0, or
  to the last shift you made, is instant.

![Transposing a B-flat track up 3 semitones to D-flat, with progress and Cancel](docs/guide_transpose.png)

## Saving

Click **Save MP3…** or press ⌘S. The Mac's Save window opens with the name
filled in:

- `Defying Gravity - AUDIO - D-flat.mp3` with a key: the key you'll hear,
  so a B-flat track raised 2 is saved as `… - AUDIO - C.mp3`;
- `Defying Gravity - AUDIO.mp3` without one, or
  `Defying Gravity - AUDIO (+2).mp3` if it's transposed.

It opens in the folder you saved to last time. Saving takes a few
seconds; **Cancel** stops it and nothing is written.

![Saving, with the progress bar and Cancel button](docs/guide_saving.png)

When it's done, click **Reveal in Finder** to see the file. The MP3 is
the trimmed, faded track at high quality, ready for Music, a playlist or
a gig.

## Shortcuts

| Key | Does |
|-----|------|
| Return (in the link box) | Fetch |
| Space | Play or pause the preview |
| = or + | Transpose up a semitone |
| − | Transpose down a semitone |
| 0 | Back to the original key |
| ⌘S | Save MP3… |
| ⌘Q | Quit (stops anything still running) |

Space, =, +, − and 0 work whenever you're not typing in the link box;
click anywhere else in the window first.

## When something goes wrong

- **"yt-dlp may be out of date"**: YouTube changed something. Open
  Terminal, run `brew upgrade yt-dlp`, and try again.
- **"Couldn't reach YouTube" or "the internet connection dropped"**: check
  your connection, then click Fetch again.
- **"The disk is full" or "can't be written to"**: save somewhere else.
- Every error has a **Details** link with the technical output, in case
  you want to look closer or send it to someone.
