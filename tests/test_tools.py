from karaokegrab import tools

ALL = {f"/opt/homebrew/bin/{n}" for n in ("yt-dlp", "ffmpeg", "ffprobe", "deno", "brew")}


def fake_fs(paths):
    return lambda p: p in paths


def test_all_found_in_homebrew_with_finder_minimal_path():
    # Finder-launched apps get roughly this PATH: no Homebrew on it.
    t = tools.locate(env_path="/usr/bin:/bin:/usr/sbin:/sbin", is_exe=fake_fs(ALL))
    assert t.ok
    assert t["yt-dlp"] == "/opt/homebrew/bin/yt-dlp"
    assert t.brew == "/opt/homebrew/bin/brew"
    assert t.install_command() == ""
    assert t.problem() == ""


def test_intel_prefix_and_path_fallback():
    fs = {"/usr/local/bin/yt-dlp", "/usr/local/bin/ffmpeg", "/usr/local/bin/ffprobe",
          "/Users/me/bin/deno", "/usr/local/bin/brew"}
    t = tools.locate(env_path="/usr/bin:/Users/me/bin", is_exe=fake_fs(fs))
    assert t.ok
    assert t["ffmpeg"] == "/usr/local/bin/ffmpeg"
    assert t["deno"] == "/Users/me/bin/deno"


def test_homebrew_prefix_wins_over_path():
    fs = {"/opt/homebrew/bin/ffmpeg", "/usr/bin/ffmpeg"}
    assert tools.find("ffmpeg", env_path="/usr/bin", is_exe=fake_fs(fs)) == "/opt/homebrew/bin/ffmpeg"


def test_missing_tools_give_one_brew_command():
    fs = {"/opt/homebrew/bin/yt-dlp", "/opt/homebrew/bin/brew"}
    t = tools.locate(env_path="/usr/bin", is_exe=fake_fs(fs))
    assert not t.ok
    assert t.missing == ["ffmpeg", "ffprobe", "deno"]
    # ffprobe comes with ffmpeg, so it isn't listed twice
    assert t.install_command() == "brew install ffmpeg deno"
    assert "brew install ffmpeg deno" in t.problem()


def test_missing_homebrew_points_to_readme():
    t = tools.locate(env_path="/usr/bin", is_exe=fake_fs(set()))
    assert t.brew is None
    assert t.install_command() == "brew install yt-dlp ffmpeg deno"
    assert "README" in t.problem()


def test_subprocess_env_puts_homebrew_first_without_duplicates():
    env = tools.subprocess_env({"PATH": "/usr/bin:/opt/homebrew/bin", "HOME": "/h"})
    assert env["PATH"].split(":") == ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]
    assert env["HOME"] == "/h"
