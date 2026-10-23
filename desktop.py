"""Sottovoce as a Windows program: one window, and an icon by the clock.

    pythonw desktop.py [--hidden] [--log FILE] [server options]

What the Start menu and desktop shortcuts run. The server runs inside this
process, as with `python server.py`; the page shows in a window of its own,
drawn by WebView2 (the engine of Edge, part of Windows), not in a browser.

    X                   hides the window. The server keeps working, a
                        transcription goes on, the icon stays by the clock.
    the icon            click: the window again. Right-click: the menu.
    Quit                the only way to stop it, and to free the GPU's memory.
    --hidden            start by the clock only: what "Start with Windows" runs.

A second double-click finds this copy running and brings its window back.
Without WebView2 the page opens in the browser, and the icon still works.
Windows only for now: on Linux and macOS, installer/start.sh opens the page
in the browser.
"""
import argparse
import ctypes
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
ICON = ROOT / "app" / "icon.ico"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_ID = "TouchSite.Sottovoce"

# The menu and the notices, in the language Windows speaks.
WORDS = {
    "open": ("Open Sottovoce", "Apri Sottovoce"),
    "calls": ("Folder of the calls", "Cartella delle call"),
    "startup": ("Start with Windows", "Avvia con Windows"),
    "quit": ("Quit", "Esci"),
    "still here": ("Sottovoce keeps working here, by the clock. To close it: Quit, in this icon's menu.",
                   "Sottovoce continua a lavorare qui, vicino all'orologio. Per chiuderlo: Esci, dal menu di questa icona."),
    "done": ("Transcribed", "Trascritta"),
    "failed": ("Transcription failed", "Trascrizione non riuscita"),
    "stop rec": ("Stop recording and transcribe", "Ferma la registrazione e trascrivi"),
    "stop later": ("Stop recording, transcribe later", "Ferma la registrazione, trascrivi dopo"),
    "saved": ("Recording saved: it waits in the list, to transcribe when you want.",
              "Registrazione salvata: la trovi nell'elenco, da trascrivere quando vuoi."),
    "transcribing": ("Recording stopped: it is being transcribed.", "Registrazione fermata: la sto trascrivendo."),
    "kept": ("Recording saved: it waits among the interrupted recordings.",
             "Registrazione salvata: la trovi tra le registrazioni interrotte."),
    "recording": ("A call is being recorded. Stop it first, or Quit again: it is saved and offered at the next start.",
                  "C'è una call in registrazione. Fermala prima, oppure Esci di nuovo: viene salvata e te la ripropone al prossimo avvio."),
    "after": ("Sottovoce closes as soon as the transcription ends. To close it now, Quit again.",
              "Sottovoce si chiude appena finisce la trascrizione. Per chiuderlo subito, Esci di nuovo."),
    "taken": ("Port {port} is used by another program: Sottovoce can't start.",
              "La porta {port} è usata da un altro programma: Sottovoce non può partire."),
}


def italian() -> bool:
    try:
        return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x10
    except (AttributeError, OSError):
        return False


def say(key, **kw) -> str:
    return WORDS[key][italian()].format(**kw)


# --- the parts that can be tested without a window -------------------------------

def split_args(argv):
    """(this program's options, the rest for the server)."""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--hidden", action="store_true")
    ap.add_argument("--log", type=pathlib.Path, default=ROOT / "sottovoce.log")
    ours, rest = ap.parse_known_args(argv)
    # The port is the server's option too: read here, left in the rest.
    port = argparse.ArgumentParser(add_help=False)
    port.add_argument("--port", type=int, default=8200)
    ours.port = port.parse_known_args(rest)[0].port
    return ours, rest


def startup_command(pythonw, server_args) -> str:
    """What Windows runs at sign-in: this program, by the clock only."""
    return subprocess.list2cmdline([str(pythonw), str(ROOT / "desktop.py"), "--hidden", *server_args])


def finished(seen, jobs):
    """Jobs that ended since the last look: [(name, "done" or "failed")]."""
    out = []
    for job_id, j in list(jobs.items()):
        if j["state"] in ("done", "error") and job_id not in seen:
            seen.add(job_id)
            out.append((j.get("name") or "", "done" if j["state"] == "done" else "failed"))
    return out


NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW


def no_console_windows(popen=subprocess.Popen):
    """Child programs (ffmpeg above all, also inside Whisper's pipeline) open
    no window. pythonw has no console to lend them, so Windows gives each one
    its own: a black window flashing at every step of a transcription. Here,
    once, for every child, ours and the libraries'."""
    start = popen.__init__

    def quiet(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = NO_WINDOW
        start(self, *args, **kwargs)

    popen.__init__ = quiet


def busy(jobs, queued) -> bool:
    """Whether quitting now would throw a transcription away."""
    return bool(queued) or any(j["state"] == "running" for j in list(jobs.values()))


def recording_icon(image):
    """The icon with a red dot: a call is being recorded. Seen by you only."""
    from PIL import ImageDraw
    img = image.convert("RGBA").copy()
    s = img.size[0]
    r = s * 0.22
    ImageDraw.Draw(img).ellipse([s - 2 * r - s * 0.02, s - 2 * r - s * 0.02, s - s * 0.02, s - s * 0.02],
                                fill="#e5484d", outline="#111113", width=max(1, int(s * 0.04)))
    return img


def answers(port) -> bool:
    """Whether a Sottovoce is already serving on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return r.read().strip() == b"ok"
    except OSError:
        return False


# --- Windows ------------------------------------------------------------------------

def pythonw() -> pathlib.Path:
    exe = pathlib.Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def startup_on() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Sottovoce")
        return True
    except OSError:
        return False


def set_startup(on, server_args):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "Sottovoce", 0, winreg.REG_SZ, startup_command(pythonw(), server_args))
        else:
            try:
                winreg.DeleteValue(k, "Sottovoce")
            except OSError:
                pass


def webview2_installed() -> bool:
    """The Evergreen runtime, per machine or per user: Windows 11 has it."""
    import winreg
    client = "Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root, path in [(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\WOW6432Node\\" + client),
                       (winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\" + client),
                       (winreg.HKEY_CURRENT_USER, "Software\\" + client)]:
        try:
            with winreg.OpenKey(root, path) as k:
                if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                    return True
        except OSError:
            pass
    return False


def tell(text):
    ctypes.windll.user32.MessageBoxW(None, text, "Sottovoce", 0x10 | 0x40000)


# --- the program ----------------------------------------------------------------------

def main(argv=None):
    ours, rest = split_args(sys.argv[1:] if argv is None else argv)
    url = f"http://127.0.0.1:{ours.port}"

    # A second double-click: the copy already running shows its window.
    if answers(ours.port):
        try:
            urllib.request.urlopen(urllib.request.Request(url + "/api/window/show", method="POST"), timeout=3)
        except OSError:
            webbrowser.open(url)          # a server started without a window
        return

    # pythonw has nowhere to print: the server's messages go to a file,
    # rewritten at every start.
    ours.log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(ours.log, "w", encoding="utf-8", buffering=1)
    # Its own name for Windows, so the taskbar shows Sottovoce's icon, not Python's.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    no_console_windows()

    import uvicorn
    import server
    args = server.options(rest)
    serving = uvicorn.Server(uvicorn.Config(server.app, host=server.configure(args),
                                            port=args.port, log_level="warning"))
    serve = threading.Thread(target=serving.run, daemon=True)
    serve.start()
    while serve.is_alive() and not answers(args.port):
        time.sleep(0.1)
    if not answers(args.port):
        tell(say("taken", port=args.port))
        return

    import pystray
    from PIL import Image

    quitting = threading.Event()
    state = {"window": None, "visible": not ours.hidden, "told": False, "leaving": False,
             "recording": False}
    plain = Image.open(ICON)
    images = {False: plain, True: recording_icon(plain)}

    def show(*_):
        w = state["window"]
        if w is None:
            webbrowser.open(url)
            return
        w.show()
        w.restore()
        state["visible"] = True

    def quit_app(*_):
        # During a transcription, Quit waits for it to end; Quit again closes
        # now. No dialog: one asked from the icon's thread froze while
        # Whisper kept Python busy, and a second click stacked another.
        # A call being recorded has no end to wait for: the first Quit says
        # so, the second saves it among the interrupted recordings.
        working = busy(server.jobs, server.line_up.qsize())
        if (working or server.capture) and not state["leaving"]:
            state["leaving"] = True
            icon.notify(say("recording" if server.capture else "after"), "Sottovoce")
            return
        server.stop_capture()
        quitting.set()
        serving.should_exit = True
        icon.stop()
        if state["window"] is not None:
            state["window"].destroy()

    def toggle_startup(*_):
        set_startup(not startup_on(), rest)

    def stop_recording(transcribe):
        def stop():
            rid = server.stop_capture()
            if rid is None:
                return
            if transcribe:
                done = server.finish_recording(rid, {})
                icon.notify(say("kept" if not isinstance(done, dict) else "transcribing"), "Sottovoce")
            else:
                server.keep_for_later(rid)
                icon.notify(say("saved"), "Sottovoce")
        threading.Thread(target=stop, daemon=True).start()

    icon = pystray.Icon("Sottovoce", plain, "Sottovoce", pystray.Menu(
        pystray.MenuItem(say("stop rec"), lambda *_: stop_recording(True),
                         visible=lambda _: server.capture is not None),
        pystray.MenuItem(say("stop later"), lambda *_: stop_recording(False),
                         visible=lambda _: server.capture is not None),
        pystray.MenuItem(say("open"), show, default=True),
        pystray.MenuItem(say("calls"), lambda *_: subprocess.Popen(["explorer", str(server.DATA)])),
        pystray.MenuItem(say("startup"), toggle_startup, checked=lambda _: startup_on()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(say("quit"), quit_app)))
    icon.run_detached()
    server.show_window = show
    server.quit_app = quit_app

    # A transcription that ends while the window is hidden says so by the clock.
    def watch():
        seen = set(server.jobs)
        while not quitting.is_set():
            for name, how in finished(seen, server.jobs):
                if not state["visible"]:
                    icon.notify(name, say(how))
            now = server.capture is not None
            if now != state["recording"]:          # the red dot, and Stop in the menu
                state["recording"] = now
                icon.icon = images[now]
                icon.update_menu()
            if state["leaving"] and not now and not busy(server.jobs, server.line_up.qsize()):
                quit_app()
            time.sleep(2)
    threading.Thread(target=watch, daemon=True).start()

    if not webview2_installed():
        if not ours.hidden:
            webbrowser.open(url)
        quitting.wait()
        time.sleep(1)
        os._exit(0)

    import webview
    webview.settings["ALLOW_DOWNLOADS"] = True
    window = webview.create_window("Sottovoce", url + "/?window", width=1360, height=880,
                                   min_size=(960, 640), background_color="#111113",
                                   hidden=ours.hidden)
    state["window"] = window

    def closing():
        if quitting.is_set():
            return True
        window.hide()
        state["visible"] = False
        # Put away, it falls silent: a call left playing behind a hidden
        # window is a voice from nowhere. From another thread: run_js waits
        # for the window's thread, which is this one, busy closing. Called
        # from here it hung the window, the icon and its menu.
        threading.Thread(target=window.run_js, args=("typeof silence === 'function' && silence()",),
                         daemon=True).start()
        if not state["told"]:
            icon.notify(say("still here"), "Sottovoce")
            state["told"] = True
        return False

    def loaded():
        # Right-click menus (copy, paste, spelling) in the text, as in a browser:
        # pywebview turns them off.
        from System import Action
        browser = window.native.browser.webview
        browser.Invoke(Action(lambda: setattr(browser.CoreWebView2.Settings,
                                              "AreDefaultContextMenusEnabled", True)))

    window.events.closing += closing
    window.events.loaded += loaded
    webview.start(gui="edgechromium", icon=str(ICON), private_mode=False,
                  storage_path=str(ours.log.parent / "webview"))
    quitting.set()
    serving.should_exit = True
    icon.stop()
    # The model's threads would keep the process alive: a moment for the
    # server to answer its last request, then out.
    time.sleep(1)
    os._exit(0)


if __name__ == "__main__":
    main()
