"""The Windows program around the server (desktop.py): what can be checked
without opening a window. The window itself, the icon by the clock and the
start with Windows are tried by hand on Windows."""
import time

import desktop
import server


def test_its_own_options_are_taken_and_the_rest_go_to_the_server():
    ours, rest = desktop.split_args(["--hidden", "--data", "D:/calls", "--port", "8300", "--log", "x.log"])
    assert ours.hidden and ours.port == 8300 and str(ours.log) == "x.log"
    assert rest == ["--data", "D:/calls", "--port", "8300"]
    assert server.options(rest).port == 8300


def test_the_default_port_is_the_servers():
    ours, rest = desktop.split_args([])
    assert ours.port == 8200 and not ours.hidden and rest == []


def test_start_with_windows_runs_it_hidden_with_the_same_folders():
    cmd = desktop.startup_command(r"C:\Program Files\x\pythonw.exe", ["--data", r"C:\Users\Zoë Rossi\Sottovoce\transcripts"])
    assert cmd.startswith('"C:\\Program Files\\x\\pythonw.exe" ')
    assert "desktop.py" in cmd and " --hidden " in cmd
    assert cmd.endswith('--data "C:\\Users\\Zoë Rossi\\Sottovoce\\transcripts"')


def test_each_finished_transcription_is_announced_once():
    jobs = {"a": {"state": "running", "name": "Kickoff"}}
    seen = set()
    assert desktop.finished(seen, jobs) == []
    jobs["a"]["state"] = "done"
    jobs["b"] = {"state": "error", "name": "Supplier"}
    assert desktop.finished(seen, jobs) == [("Kickoff", "done"), ("Supplier", "failed")]
    assert desktop.finished(seen, jobs) == []


def test_quitting_waits_while_a_transcription_runs_or_waits():
    assert not desktop.busy({"a": {"state": "done"}}, 0)
    assert desktop.busy({"a": {"state": "running"}}, 0)
    assert desktop.busy({}, 1)


def test_a_second_launch_brings_the_window_back(client):
    assert client.post("/api/window/show").status_code == 404        # no window: a plain server
    shown = []
    server.show_window = lambda: shown.append(True)
    try:
        assert client.post("/api/window/show").json() == {"shown": True}
        assert shown == [True]
    finally:
        server.show_window = None


def test_the_power_button_quits_the_program_in_the_window(client):
    quit = []
    server.quit_app = lambda: quit.append(True)
    try:
        assert client.post("/api/shutdown").json() == {"stopped": True}
        for _ in range(50):
            if quit:
                break
            time.sleep(0.05)
        assert quit == [True]
    finally:
        server.quit_app = None


def test_child_programs_open_no_window_unless_asked_otherwise():
    class Popen:                               # stands in for subprocess.Popen
        def __init__(self, args, creationflags=0):
            self.flags = creationflags
    desktop.no_console_windows(Popen)
    assert Popen(["ffmpeg"]).flags == desktop.NO_WINDOW
    assert Popen(["x"], creationflags=0x200).flags == 0x200          # a caller's own choice stays
