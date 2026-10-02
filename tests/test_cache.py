import os

from karaokegrab import cache


def _make(video_id, mtime, root, name="audio.webm"):
    d = cache.video_dir(video_id, root)
    d.mkdir(parents=True)
    (d / name).write_bytes(b"data")
    os.utime(d, (mtime, mtime))
    return d


def test_paths_per_video(tmp_path):
    assert cache.video_dir("abc", tmp_path) == tmp_path / "abc"
    assert cache.info_path("abc", tmp_path) == tmp_path / "abc" / "info.json"
    assert cache.audio_template("abc", tmp_path) == str(tmp_path / "abc" / "audio.%(ext)s")
    # ids are used as folder names, so nothing odd gets through
    assert cache.video_dir("../x y", tmp_path) == tmp_path / "___x_y"


def test_default_root_is_the_cache_dir():
    assert cache.video_dir("abc") == cache.CACHE_DIR / "abc"


def test_find_audio_reuses_and_marks_used(tmp_path):
    d = _make("abc", 1_000, tmp_path)
    found = cache.find_audio("abc", tmp_path)
    assert found == d / "audio.webm"
    assert d.stat().st_mtime > 1_000


def test_find_audio_ignores_partials_and_empty_files(tmp_path):
    d = _make("abc", 1_000, tmp_path, name="audio.webm.part")
    (d / "audio.m4a").write_bytes(b"")
    assert cache.find_audio("abc", tmp_path) is None
    assert cache.find_audio("missing", tmp_path) is None


def test_remove_partials_keeps_finished_files(tmp_path):
    d = _make("abc", 1_000, tmp_path, name="audio.webm.part")
    (d / "audio.webm.ytdl").write_text("x")
    (d / "info.json").write_text("{}")
    cache.remove_partials("abc", tmp_path)
    assert sorted(p.name for p in d.iterdir()) == ["info.json"]


def test_prune_keeps_most_recent(tmp_path):
    for i in range(13):
        _make(f"v{i:02d}", 1_000 + i, tmp_path)
    removed = cache.prune(keep=10, root=tmp_path)
    assert sorted(d.name for d in removed) == ["v00", "v01", "v02"]
    assert len(list(tmp_path.iterdir())) == 10


def test_prune_never_removes_the_protected_video(tmp_path):
    _make("old", 1, tmp_path)
    _make("new", 2, tmp_path)
    cache.prune(keep=1, root=tmp_path, protect="old")
    assert sorted(d.name for d in tmp_path.iterdir()) == ["new", "old"]


def test_prune_without_cache_dir(tmp_path):
    assert cache.prune(root=tmp_path / "nope") == []
