"""proc.run against a real child process (the test's own Python; no network)."""

import sys
import threading
import time

from karaokegrab import proc


def test_streams_stdout_lines_and_keeps_stderr():
    seen = []
    code = "import sys; print('one'); print('two'); print('oops', file=sys.stderr); sys.exit(3)"
    r = proc.run([sys.executable, "-c", code], on_line=seen.append)
    assert seen == ["one", "two"]
    assert r.returncode == 3
    assert "oops" in r.stderr
    assert not r.ok
    assert r.output.startswith("$ " + sys.executable)


def test_cancel_kills_the_whole_process_group(tmp_path):
    # The child starts a grandchild, like yt-dlp starting ffmpeg; both must die.
    marker = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time;"
        f"g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(marker)!r}, 'w').write(str(g.pid));"
        "print('started', flush=True); time.sleep(60)"
    )
    cancel = proc.Cancel()

    def on_line(line):
        if line == "started":
            threading.Timer(0.1, cancel.set).start()

    t0 = time.monotonic()
    r = proc.run([sys.executable, "-c", code], on_line=on_line, cancel=cancel)
    assert r.cancelled
    assert not r.ok
    assert time.monotonic() - t0 < 10

    import os
    gpid = int(marker.read_text())
    for _ in range(50):
        try:
            os.kill(gpid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("grandchild still running")


def test_subprocess_gets_homebrew_on_path():
    r = proc.run([sys.executable, "-c", "import os; print(os.environ['PATH'])"])
    assert r.stdout.split(":")[0] == "/opt/homebrew/bin"
