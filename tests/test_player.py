from pathlib import Path

from karaokegrab.player import Player


class FakeProc:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make():
    procs, clock = [], Clock()

    def popen(argv, **kw):
        p = FakeProc()
        p.argv = argv
        procs.append(p)
        return p

    return Player(afplay="/usr/bin/afplay", popen=popen, clock=clock), procs, clock


def test_play_runs_afplay_and_tracks_position():
    pl, procs, clock = make()
    assert not pl.playing and pl.stop() is None
    pl.play(Path("/tmp/clip.wav"), offset=42.0)
    assert procs[0].argv == ["/usr/bin/afplay", "/tmp/clip.wav"]
    assert pl.playing
    clock.now += 3.5
    assert pl.position() == 45.5


def test_stop_returns_where_playback_reached():
    pl, procs, clock = make()
    pl.play(Path("c.wav"), offset=10.0)
    clock.now += 2.0
    assert pl.stop() == 12.0
    assert procs[0].terminated
    assert not pl.playing and not pl.finished


def test_playing_again_stops_the_previous_clip():
    pl, procs, clock = make()
    pl.play(Path("a.wav"), 0)
    pl.play(Path("b.wav"), 5)
    assert procs[0].terminated and not procs[1].terminated
    assert pl.offset == 5


def test_finished_when_the_clip_ends_by_itself():
    pl, procs, clock = make()
    pl.play(Path("c.wav"), 0)
    procs[0].returncode = 0
    assert pl.finished and not pl.playing
    pl.reset()
    assert not pl.finished
