import pytest

from karaokegrab import download, fetch, links, render
from conftest import result


V = "dQw4w9WgXcQ"


@pytest.mark.parametrize("text, url", [
    (f"https://www.youtube.com/watch?v={V}", f"https://www.youtube.com/watch?v={V}"),
    (f"  https://youtu.be/{V}?t=12  ", f"https://youtu.be/{V}?t=12"),     # spaces are fine
    (f"check this: https://youtu.be/{V}", None),                          # extra words are not
    (f"https://youtu.be/{V} thanks", None),
    (f"youtu.be/{V}", None),                                              # no https://
    (f"www.youtube.com/watch?v={V}", None),
    ("ftp://youtube.com/x", None),
    ("https://", None),
    ("", None),
])
def test_well_formed(text, url):
    assert links.well_formed(text) == url


@pytest.mark.parametrize("url, yes", [
    (f"https://www.youtube.com/watch?v={V}", True),
    (f"https://m.youtube.com/watch?v={V}", True),
    (f"https://music.youtube.com/watch?v={V}", True),
    (f"https://youtube.com/shorts/{V}", True),
    (f"https://youtu.be/{V}", True),
    ("https://vimeo.com/123", False),
    (f"https://notyoutube.com/watch?v={V}", False),
    (f"https://youtube.com.evil.example/watch?v={V}", False),
])
def test_is_youtube(url, yes):
    assert links.is_youtube(url) is yes


@pytest.mark.parametrize("url, yes", [
    ("https://www.youtube.com/playlist?list=PL123", True),
    ("https://www.youtube.com/watch?list=PL123", True),
    (f"https://www.youtube.com/watch?v={V}&list=PL123", False),   # a video inside a playlist
    (f"https://youtu.be/{V}?list=PL123", False),
    (f"https://www.youtube.com/watch?v={V}", False),
    ("https://vimeo.com/playlist?list=1", False),
])
def test_is_playlist_only(url, yes):
    assert links.is_playlist_only(url) is yes


@pytest.mark.parametrize("url, yes", [
    (f"https://www.youtube.com/watch?v={V}", True),
    (f"https://www.youtube.com/watch?v={V}&t=90s", True),
    (f"https://youtu.be/{V}", True),
    (f"https://youtu.be/{V}?si=abc", True),
    (f"https://www.youtube.com/shorts/{V}", True),
    (f"https://www.youtube.com/live/{V}", True),
    (f"https://www.youtube.com/embed/{V}", True),
    ("https://www.youtube.com/", False),
    ("https://www.youtube.com/@SingKingKaraoke", False),
    ("https://www.youtube.com/results?search_query=karaoke", False),
    ("https://www.youtube.com/watch", False),
    ("https://www.youtube.com/watch?v=", False),
    ("https://youtu.be/", False),
])
def test_is_video(url, yes):
    assert links.is_video(url) is yes


# --- check_url: instant rejections, before any yt-dlp call -------------------

def test_check_url_allows_surrounding_spaces_only():
    assert fetch.check_url(f"  https://youtu.be/{V}  ") == f"https://youtu.be/{V}"


@pytest.mark.parametrize("text, message", [
    ("   ", "Paste a YouTube link first."),
    (f"check this: https://youtu.be/{V}", fetch.NOT_A_LINK),
    (f"youtu.be/{V}", fetch.NOT_A_LINK),
    ("hello there", fetch.NOT_A_LINK),
    ("https://www.youtube.com/playlist?list=PL123", fetch.PLAYLIST),
    ("https://vimeo.com/123", fetch.NOT_YOUTUBE),
    ("https://www.youtube.com/@SingKingKaraoke", fetch.NOT_A_VIDEO),
])
def test_check_url_rejects(text, message):
    with pytest.raises(fetch.FetchError) as e:
        fetch.check_url(text)
    assert e.value.message == message


def test_playlist_is_rejected_without_running_ytdlp(fake_run):
    with pytest.raises(fetch.FetchError):
        fetch.fetch_info("yt-dlp", "https://www.youtube.com/playlist?list=PL123")
    assert fake_run.calls == []


def test_very_short_video_rejected(video_json):
    video_json["duration"] = 0.6
    with pytest.raises(fetch.FetchError, match="too short"):
        fetch.parse_info(video_json)


# --- friendlier download and save errors ---------------------------------------

@pytest.mark.parametrize("output, message", [
    ("ERROR: Unable to download webpage: <urlopen error [Errno 8] nodename nor servname>", download.NETWORK),
    ("ERROR: The read operation timed out", download.NETWORK),
    ("ERROR: [download] Got error: Connection reset by peer", download.NETWORK),
    ("ERROR: unable to download video data: HTTP Error 403: Forbidden", download.FAILED),
])
def test_download_errors(output, message):
    assert download.friendly_error(output) == message


def test_download_network_drop_message(fake_run):
    fake_run.on(lambda a: True, lambda a, ol, c: result(
        a, returncode=1, stderr="ERROR: The read operation timed out"))
    with pytest.raises(download.DownloadError) as e:
        download.download("yt-dlp", "abc", "https://youtu.be/abc")
    assert e.value.message == download.NETWORK


@pytest.mark.parametrize("output, message", [
    ("Error writing trailer: No space left on device", render.DISK_FULL),
    ("x.mp3.part: Permission denied", render.NOT_WRITABLE),
    ("Read-only file system", render.NOT_WRITABLE),
    ("Invalid data found when processing input", render.FAILED),
])
def test_render_errors(output, message):
    assert render.friendly_error(output, render.FAILED) == message


def test_check_writable(tmp_path):
    assert render.check_writable(tmp_path) == ""
    assert render.check_writable(tmp_path / "missing") == render.NOT_WRITABLE
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert render.check_writable(locked) == render.NOT_WRITABLE
    finally:
        locked.chmod(0o700)
