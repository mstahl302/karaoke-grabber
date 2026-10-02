import json

import pytest

from karaokegrab import fetch
from conftest import result


def test_parse_saved_sample(video_json):
    info = fetch.parse_info(video_json)
    assert info.id == "jNQXAC9IVRw"
    assert info.title == "Me at the zoo"
    assert info.channel == "jawed"
    assert info.duration == 19.0
    assert info.thumbnail_url.startswith("https://i.ytimg.com/")
    assert info.url == "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def test_channel_falls_back_to_uploader(video_json):
    del video_json["channel"]
    video_json["uploader"] = "Sing King"
    assert fetch.parse_info(video_json).channel == "Sing King"


def test_playlist_rejected():
    with pytest.raises(fetch.FetchError, match="playlist"):
        fetch.parse_info({"_type": "playlist", "id": "PL1", "entries": []})


@pytest.mark.parametrize("fields", [{"is_live": True}, {"live_status": "is_upcoming"}])
def test_live_stream_rejected(video_json, fields):
    video_json.update(fields)
    with pytest.raises(fetch.FetchError, match="live stream"):
        fetch.parse_info(video_json)


def test_missing_duration_rejected(video_json):
    video_json["duration"] = None
    with pytest.raises(fetch.FetchError, match="how long"):
        fetch.parse_info(video_json)


# Real yt-dlp error lines (2026.08.19).
@pytest.mark.parametrize("stderr, expected", [
    ("ERROR: [generic] 'not a url' is not a valid URL", "doesn't look like a web address"),
    ("ERROR: [youtube] xxxxxxxxxxx: This video is unavailable", "unavailable"),
    ("ERROR: [youtube] abc: Video unavailable. This video is private", "private"),
    ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [youtube] abc: Sign in to confirm your age.", "age-restricted"),
    ("ERROR: [generic] foo: Unable to download webpage: HTTP Error 404: Not Found", "Nothing was found"),
    ("ERROR: Unable to download webpage: <urlopen error [Errno 8] nodename nor servname provided>",
     "internet connection"),
    ("ERROR: something new and strange", "brew upgrade yt-dlp"),
])
def test_friendly_errors(stderr, expected):
    assert expected in fetch.friendly_error(stderr)


def test_fetch_info_runs_ytdlp_and_parses(fake_run, video_json):
    fake_run.on(lambda a: "-J" in a, lambda a, ol, c: result(a, stdout=json.dumps(video_json)))
    info = fetch.fetch_info("/bin/yt-dlp", "  https://youtu.be/jNQXAC9IVRw  ")
    assert info.id == "jNQXAC9IVRw"
    assert fake_run.calls == [["/bin/yt-dlp", "-J", "--no-playlist", "--no-warnings",
                               "https://youtu.be/jNQXAC9IVRw"]]


def test_fetch_info_failure_keeps_details(fake_run):
    fake_run.on(lambda a: True, lambda a, ol, c: result(
        a, returncode=1, stderr="ERROR: [youtube] x: This video is unavailable"))
    with pytest.raises(fetch.FetchError) as e:
        fetch.fetch_info("yt-dlp", "https://youtu.be/x")
    assert "unavailable" in e.value.message
    assert "$ yt-dlp -J" in e.value.details
    assert "This video is unavailable" in e.value.details


def test_fetch_info_cancelled_returns_none(fake_run):
    fake_run.on(lambda a: True, lambda a, ol, c: result(a, returncode=-15, cancelled=True))
    assert fetch.fetch_info("yt-dlp", "https://youtu.be/x") is None


def test_empty_url_needs_no_subprocess(fake_run):
    with pytest.raises(fetch.FetchError, match="Paste"):
        fetch.fetch_info("yt-dlp", "   ")
    assert fake_run.calls == []


def test_thumbnail_written_as_png(fake_run, tmp_path):
    stem = tmp_path / "v" / "thumb"
    stem.parent.mkdir()

    def write_png(argv, on_line, cancel):
        assert argv[argv.index("--convert-thumbnails") + 1] == "png"
        stem.with_suffix(".png").write_bytes(b"\x89PNG")
        return result(argv)

    fake_run.on(lambda a: "--write-thumbnail" in a, write_png)
    assert fetch.fetch_thumbnail("yt-dlp", tmp_path / "info.json", stem) == stem.with_suffix(".png")
    # Second call reuses the file without running yt-dlp again.
    assert fetch.fetch_thumbnail("yt-dlp", tmp_path / "info.json", stem) == stem.with_suffix(".png")
    assert len(fake_run.calls) == 1


def test_thumbnail_failure_is_not_fatal(fake_run, tmp_path):
    fake_run.on(lambda a: True, lambda a, ol, c: result(a, returncode=1))
    assert fetch.fetch_thumbnail("yt-dlp", tmp_path / "i.json", tmp_path / "thumb") is None
