"""The real window, on Windows: open it, press X, launch again, quit.

The unit tests in test_desktop.py can't see what happens between the window,
its thread and the icon. This runs desktop.py as the shortcut does and works
it through Windows' own messages. It caught a hang: after X the window, the
icon and its menu stopped answering, because closing waited on itself.
Skipped where there is no Windows or no pywebview.
"""
import ctypes
import pathlib
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from conftest import ROOT

if sys.platform != "win32":
    pytest.skip("the window is Windows only", allow_module_level=True)
pytest.importorskip("webview")
pytest.importorskip("pystray")

from ctypes import wintypes  # noqa: E402

user32 = ctypes.windll.user32
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
WM_CLOSE = 0x0010


def family(pid):
    """The process and its children: a venv's pythonw starts the real one."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"],
                         capture_output=True, text=True).stdout.split()
    return {pid, *map(int, out)}


def find_window(pids):
    """This test's window only: never another Sottovoce open on the machine."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(h, _):
        title, cls = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(h, title, 256)
        user32.GetClassNameW(h, cls, 256)
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
        if title.value == "Sottovoce" and cls.value.startswith("WindowsForms") and owner.value in pids:
            found.append(h)
            return False
        return True
    user32.EnumWindows(each, 0)
    return found[0] if found else None


def answers(h):
    """Whether the window's thread still handles messages."""
    out = wintypes.DWORD()
    return user32.SendMessageTimeoutW(h, 0, 0, 0, 0x2, 2000, ctypes.byref(out)) != 0


def wait(condition, seconds):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.2)
    return False


def up(url):
    try:
        return urllib.request.urlopen(url + "/health", timeout=1).read() in (b"ok", b"loading")
    except OSError:
        return False


def test_x_hides_a_second_launch_brings_it_back_quit_closes(data, tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    pythonw = pathlib.Path(sys.executable).with_name("pythonw.exe")      # as the shortcut runs it
    run = [str(pythonw if pythonw.exists() else sys.executable), str(ROOT / "desktop.py"),
           "--no-model", "--port", str(port), "--data", str(data / "transcripts"),
           "--log", str(tmp_path / "sottovoce.log")]
    proc = subprocess.Popen(run)
    try:
        assert wait(lambda: up(url), 60), "the server did not start"
        pids = family(proc.pid)
        assert wait(lambda: find_window(pids) and user32.IsWindowVisible(find_window(pids)), 30), "no window"
        h = find_window(pids)

        user32.PostMessageW(h, WM_CLOSE, 0, 0)                          # the X
        assert wait(lambda: not user32.IsWindowVisible(h), 10), "X did not hide it"
        time.sleep(1)
        assert answers(h), "the window hung after X"
        assert up(url), "the server stopped with the window"

        subprocess.run(run[:2] + ["--port", str(port)], timeout=30)   # the shortcut, again
        assert wait(lambda: user32.IsWindowVisible(h), 10), "a second launch did not bring it back"

        urllib.request.urlopen(urllib.request.Request(url + "/api/shutdown", method="POST"), timeout=5)
        assert wait(lambda: proc.poll() is not None, 15), "Quit did not close the program"
        assert wait(lambda: find_window(pids) is None, 10), "a window was left behind"
    finally:
        if proc.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
