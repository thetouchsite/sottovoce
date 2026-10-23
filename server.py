"""Sottovoce: drop a recording on the page, or record a call from it, and get the text back.

    python server.py                         then  http://127.0.0.1:8200
    python server.py --port 8300 --data D:\\calls --glossary D:\\calls\\names.txt
    python server.py --no-model              browse transcripts, no GPU needed
    python server.py --lan                   also open it from a phone on the same Wi-Fi, with a PIN

Why a server and not a script you drop files on: the model weighs 2.88 GB and
loading it from disk into VRAM takes about twenty seconds. Here that is paid
**once, at startup**, and then the model stays warm: from the second file on
you only pay for the transcription. A command-line script pays the twenty
seconds again for every file.

The work is not duplicated here: it comes from `transcribe.py`, which is also
the command-line program. Two copies of the same thing drift apart at the
first edit, and then nobody knows which one produced a text.

ONE FOLDER PER TRANSCRIPTION, with everything inside:

    transcripts/2026-10-22_Client call/
        Client call.mp4      the original recording, kept safe
        Client call.txt      [mm:ss] lines: the source everything is rebuilt from
        Client call.md       to read
        words.json           when every word was said, line by line
        info.json            duration, timings, model, language, what was dropped,
                             the names given to the voices
        corrections.jsonl    every line corrected, with before and after
        summary.md           if you asked for one
        followup.md          the follow-up email, if you asked for one

The original is kept: if you lose it from your phone or your Downloads, the
copy is here next to its transcript.

ADDED, THEN TRANSCRIBED. A file sent from the page is kept first, as a
folder with its recording and an info.json that says "waiting": it can be
renamed, listened to, deleted, and transcribed when you choose how. The state
lives on disk, not in the page, so a reload or a restart does not lose it.

ONE AT A TIME. Jobs queue up instead of running together: two transcriptions in
parallel share the same pipeline and slow each other down (measured: 233 s
instead of 190 when two were running).

Everything stays on this machine: the uploaded file does not leave, the model
runs locally, there are no network calls during transcription. The page itself
loads nothing from the internet, not even its fonts. (The API reference at
/docs is FastAPI's own page, and loads Swagger UI from a CDN when opened.)
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import secrets
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import uuid
from datetime import date

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, Response)

import recorder
import summary as S
import transcribe as T

VERSION = "1.7.0"
ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "transcripts"            # set again by start() from --data
INCOMING = DATA / "_incoming"
RECORDINGS = DATA / "_recordings"
AUDIO = (".mp4", ".m4a", ".mp3", ".wav", ".opus", ".ogg", ".3gp", ".aac",
         ".webm", ".flac", ".mov", ".mkv")

app = FastAPI(
    title="Sottovoce", version=VERSION,
    description="Local transcription of recorded calls with Whisper large-v3. "
                "Every call is a folder of plain files; this API reads and writes them.")

engine_state = {"ready": False, "error": None, "off": False}

# --- the PIN, when the page is open to the network ------------------------------
# With --lan the server answers other devices, and it hands out client calls
# to whoever asks. So another device must give a PIN once; then a cookie
# signed with a secret kept on this machine lets it in for a year, across
# restarts. This computer itself is never asked. Plain http: the PIN keeps
# out the curious on the same Wi-Fi, not someone listening on purpose.
PIN_FILE = ROOT / ".lan-pin"
lan = {"pin": None, "secret": b""}
pin_tries: dict[str, list[float]] = {}
LOCAL = ("127.0.0.1", "::1", "localhost")


def pin_setup(chosen: str | None = None) -> str:
    """The PIN for --lan: the one chosen, or the one kept, or a new one."""
    kept = json.loads(PIN_FILE.read_text(encoding="utf-8")) if PIN_FILE.exists() else {}
    pin = chosen or kept.get("pin") or f"{secrets.randbelow(10 ** 6):06d}"
    # A new PIN, a new secret: every device let in with the old one is out.
    secret = kept["secret"] if kept.get("pin") == pin and kept.get("secret") else secrets.token_hex(32)
    PIN_FILE.write_text(json.dumps({"pin": pin, "secret": secret}), encoding="utf-8")
    lan.update(pin=pin, secret=secret.encode())
    return pin


def pin_token() -> str:
    return hmac.new(lan["secret"], b"sottovoce-lan", hashlib.sha256).hexdigest()


@app.middleware("http")
async def pin_guard(request: Request, call_next):
    if lan["pin"] and (request.client is None or request.client.host not in LOCAL):
        path = request.url.path
        allowed = path in ("/pin", "/api/pin", "/health") or path.startswith("/fonts/")
        if not allowed and not hmac.compare_digest(request.cookies.get("sottovoce_pin", ""), pin_token()):
            if path.startswith("/api/"):
                return JSONResponse({"error": "PIN required"}, 401)
            return RedirectResponse("/pin", 303)
    return await call_next(request)


# --- who may talk to this server -----------------------------------------------
# Listening on 127.0.0.1 is not enough on its own. Any web page open in the
# browser can send requests there: a form posted to /api/shutdown stopped the
# server (checked), and with DNS rebinding (evil.example made to resolve to
# 127.0.0.1) a page could read /api/history as if it were its own. So:
#
#   Host    only the names this server is reached by: 127.0.0.1, localhost
#           and [::1] on its port, plus this computer's addresses with --lan.
#           A rebound name never matches.
#   Origin  a request that changes something (POST, PUT, PATCH, DELETE) is
#           refused when the browser says it comes from another site. Without
#           an Origin (a script, curl) it goes through: browsers always send
#           one on cross-site requests that change state.
allowed_hosts: set[str] | None = None      # set at startup; None when imported by tests or scripts
CHANGES = {"POST", "PUT", "PATCH", "DELETE"}


def hosts_for(port: int, addresses=()) -> set[str]:
    names = {"127.0.0.1", "localhost", "[::1]", *addresses}
    return {f"{n}:{port}".lower() for n in names}


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    host = (request.headers.get("host") or "").lower()
    if allowed_hosts is not None and host not in allowed_hosts:
        return PlainTextResponse("This server only answers to its own address.", 403)
    if request.method in CHANGES:
        origin = request.headers.get("origin")
        if origin is not None:
            if origin == "null" or urllib.parse.urlsplit(origin).netloc.lower() != host:
                return JSONResponse({"error": "refused: the request comes from another site"}, 403)
        elif request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"error": "refused: the request comes from another site"}, 403)
    return await call_next(request)


PIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sottovoce</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#171719;color:#fff;
    font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px;box-sizing:border-box}
  form{width:100%;max-width:320px;background:#131217;border-radius:6px;padding:28px 24px;
    box-shadow:0 12px 28px rgba(0,0,0,.2)}
  h1{font-size:21px;margin:0 0 6px} p{color:#8a8c92;margin:0 0 20px;font-size:13px}
  input{width:100%;box-sizing:border-box;height:46px;background:#171719;color:#fff;font-size:22px;
    letter-spacing:.3em;text-align:center;border:1px solid #3a3a3e;border-radius:8px}
  input:focus{outline:none;border-color:#4a8ad6}
  button{width:100%;height:42px;margin-top:14px;border:0;border-radius:999px;background:#fff;
    color:#000;font-weight:600;font-size:15px}
  .err{color:#e5566f;min-height:20px;margin:12px 0 0;font-size:13px}
</style></head><body>
<form id="f"><h1>Sottovoce</h1><p id="t">Enter the PIN shown on the computer where Sottovoce runs.
This device will be remembered.</p>
<input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="12" autofocus aria-label="PIN">
<button id="b" type="submit">Open</button><p class="err" id="e" role="alert"></p></form>
<script>
const it = (localStorage.getItem('sottovoce-ui') || navigator.language || '').startsWith('it');
if (it){ document.documentElement.lang = 'it';
  document.getElementById('t').textContent = 'Scrivi il PIN che compare sul computer dove gira Sottovoce. Questo dispositivo verrà ricordato.';
  document.getElementById('b').textContent = 'Apri'; }
document.getElementById('f').onsubmit = async e => {
  e.preventDefault();
  const r = await fetch('/api/pin', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({pin: document.getElementById('pin').value.trim()})});
  if (r.ok){ location.href = '/'; return; }
  const j = await r.json().catch(() => ({}));
  document.getElementById('e').textContent = r.status === 429
    ? (it ? 'Troppi tentativi: riprova tra qualche minuto.' : (j.error || 'Too many tries.'))
    : (it ? 'PIN sbagliato.' : 'Wrong PIN.');
};
</script></body></html>"""


@app.get("/pin", include_in_schema=False)
def pin_page():
    if not lan["pin"]:
        return RedirectResponse("/", 303)
    return HTMLResponse(PIN_PAGE)


@app.post("/api/pin", include_in_schema=False)
def api_pin(request: Request, body: dict):
    """Lets a device in. Five wrong PINs from one address: 15 minutes off."""
    if not lan["pin"]:
        return {"ok": True}
    who = request.client.host if request.client else "?"
    now = time.time()
    tries = [t for t in pin_tries.get(who, []) if now - t < 900]
    pin_tries[who] = tries
    if len(tries) >= 5:
        return JSONResponse({"error": "too many tries: wait 15 minutes"}, 429)
    if not hmac.compare_digest(str(body.get("pin") or "").strip(), lan["pin"]):
        tries.append(now)
        return JSONResponse({"error": "wrong PIN"}, 403)
    pin_tries.pop(who, None)
    r = JSONResponse({"ok": True})
    r.set_cookie("sottovoce_pin", pin_token(), max_age=365 * 24 * 3600, httponly=True, samesite="strict")
    return r
jobs: dict[str, dict] = {}
line_up: queue.Queue = queue.Queue()


def clean(name: str) -> str:
    """A file name Windows accepts, without losing readability."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name[:80] or "untitled"


def folder(name: str) -> pathlib.Path:
    """A transcription folder by name, never outside the data folder."""
    return DATA / pathlib.Path(name).name


class Idle:
    """Lets Whisper go T.IDLE seconds after the last transcription. Never
    while one runs or waits: the clock starts when the line is empty."""

    def __init__(self):
        self.last_busy = time.time()

    def check(self, now=None):
        now = now or time.time()
        if line_up.qsize() or any(j["state"] == "running" for j in list(jobs.values())):
            self.last_busy = now
        elif T.loaded() and now - self.last_busy > T.IDLE:
            T.release()
            print("  Whisper left the GPU: unused for ten minutes")


def unload_when_idle():
    idle = Idle()
    while True:
        time.sleep(30)
        idle.check()


def sweep():
    """Uploads left half-way by a previous run.

    If the server closes while transcribing, the uploaded file stays on disk.
    It is a client's audio, and it must not pile up silently.

    Recordings are NOT swept: an interrupted recording is the only copy of
    that call. The page offers to transcribe or delete it.
    """
    if INCOMING.exists():
        n = len(list(INCOMING.glob("*")))
        shutil.rmtree(INCOMING, ignore_errors=True)
        if n:
            print(f"  removed {n} uploads left over from a previous run")
    INCOMING.mkdir(parents=True, exist_ok=True)
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    # A transcription cut short by a restart: the recording is in its folder,
    # so it goes back to waiting instead of saying "transcribing" forever.
    for d in DATA.iterdir():
        f = d / "info.json"
        if d.is_dir() and f.exists():
            try:
                info = read_info(d)
            except (json.JSONDecodeError, OSError):
                continue
            if info.get("status") in ("queued", "transcribing"):
                info["status"] = "waiting"
                write_info(d, info)


def write_info(d: pathlib.Path, info: dict):
    """info.json, replaced whole: never seen half written.

    A transcription writes it from its own thread while the page reads the
    list. Written in place, a read landing between the truncation and the
    write found an empty file (it failed a test in CI once). So it is
    written next to it and swapped in one step. On Windows the swap is
    refused while someone has the file open, for the few milliseconds of a
    read: then it waits and tries again.
    """
    tmp = d / "info.json.tmp"
    tmp.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    for _ in range(40):
        try:
            os.replace(tmp, d / "info.json")
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, d / "info.json")


def read_info(d: pathlib.Path) -> dict:
    # On Windows, for the instant write_info swaps the file in, opening it
    # is refused: wait a moment instead of failing the page.
    for _ in range(40):
        try:
            return json.loads((d / "info.json").read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.05)
    return json.loads((d / "info.json").read_text(encoding="utf-8"))


# --- reading a call back --------------------------------------------------------
# The folders on disk ARE the history: the server keeps no list of its own, it
# reads them again. So it survives a restart, and if the server dies half-way
# the finished transcriptions are still there.

def read_call(d: pathlib.Path, duration: float | None = None):
    """The lines of a call, from its .txt, with words and ends when known.

    Each line remembers which line of the file it came from ("row"): the page
    sends back the position of the line it shows, and blank or unreadable
    lines in a file edited by hand must not shift a correction onto the wrong
    line.
    """
    txt = next(d.glob("*.txt"), None)
    if txt is None:
        return None, []
    segments = []
    for row, line in enumerate(txt.read_text(encoding="utf-8").splitlines()):
        p = T.parse_line(line)
        if p:
            s = {"start": p[0], "end": None, "text": p[2], "row": row}
            if p[1]:
                s["speaker"] = p[1]
            segments.append(s)

    words = []
    wf = d / "words.json"
    if wf.exists():
        try:
            words = json.loads(wf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            words = []
    # Word timings are trusted only if they still describe the same lines:
    # a .txt edited outside the page may have gained or lost one.
    if len(words) == len(segments):
        for s, w in zip(segments, words):
            if w and " ".join(x[2] for x in w) == " ".join(s["text"].split()):
                s["words"] = w

    if duration is None and (d / "info.json").exists():
        duration = read_info(d).get("duration_s") or 0
    for s, e in zip(segments, T.ends(segments, duration or 0)):
        s["end"] = round(e, 2)
        # Calls transcribed before word timings were kept get them estimated,
        # the same way the fast mode does: a click lands near the word instead
        # of only at the start of the line.
        if not s.get("words"):
            s["words"] = T.tidy(T.spread([{"text": s["text"], "timestamp": (s["start"], s["end"])}])[0])
    return txt, segments


def write_words(d: pathlib.Path, segments):
    (d / "words.json").write_text(
        json.dumps([s.get("words") for s in segments], ensure_ascii=False), encoding="utf-8")


def audio_in(d: pathlib.Path) -> str | None:
    return next((f.name for f in d.iterdir() if f.suffix.lower() in AUDIO), None)


def names_of(d: pathlib.Path) -> dict:
    """The names given to the voices of a call: {"Voice 1": "Maya", ...}."""
    if not (d / "info.json").exists():
        return {}
    return read_info(d).get("speaker_names") or {}


def speakers_of(segments, names=None):
    """Who speaks in a call, in order, with how long each one talks.

    Talk time is measured on the words, not on the lines: a line runs until
    the next one starts, and would count every pause as talking.
    """
    talk, lines = {}, {}
    for s in segments:
        sp = s.get("speaker")
        if not sp:
            continue
        w = s.get("words") or []
        talk[sp] = talk.get(sp, 0.0) + (w[-1][1] - w[0][0] if w else 0.0)
        lines[sp] = lines.get(sp, 0) + 1

    def order(sp):
        return (0, 0) if sp == "Me" else (1, 0) if sp == "Them" else (2, int(sp.split()[-1]))

    return [{"tag": sp, "name": (names or {}).get(sp), "seconds": round(talk[sp]),
             "lines": lines[sp]} for sp in sorted(talk, key=order)]


# --- the job ----------------------------------------------------------------------

def take(upload: pathlib.Path, name: str) -> pathlib.Path:
    """A new call folder for an uploaded file, and the file moved into it."""
    stem = clean(pathlib.Path(name).stem)
    d = DATA / f"{date.today():%Y-%m-%d}_{stem}"
    n = 2
    while d.exists():                      # two calls with the same name
        d = DATA / f"{date.today():%Y-%m-%d}_{stem} ({n})"
        n += 1
    d.mkdir(parents=True)
    original = d / f"{stem}{pathlib.Path(name).suffix}"
    shutil.move(str(upload), original)
    return original


def probe_seconds(f: pathlib.Path) -> float | None:
    """How long a recording lasts, from ffmpeg's own reading of its header.

    None when it can't be read: adding a file must not fail because its
    length is unknown.
    """
    try:
        r = subprocess.run([T.ffmpeg(), "-hide_banner", "-i", str(f)], capture_output=True, text=True)
    except Exception:
        return None
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return round(int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), 1) if m else None


def process(job_id: str, original: pathlib.Path, language: str | None,
            two_tracks: bool = False, precise: bool = False, voices: bool = False) -> None:
    job = jobs[job_id]
    d = original.parent
    # What the folder already knew (a name given, when it was added) stays.
    before = read_info(d) if (d / "info.json").exists() else {}
    keep = {k: before[k] for k in ("title", "uploaded_at") if k in before}
    try:
        stem = original.stem
        job["folder"] = d.name
        write_info(d, {**before, "status": "transcribing"})

        def progress(stage, audio_seconds):
            job["stage"] = stage
            if audio_seconds:
                job["duration"] = audio_seconds
            if stage in ("loading the model", "downloading the model"):
                job["expected"] = 0             # no estimate: the page shows a moving bar and the seconds
            elif audio_seconds:
                # An honest estimate: the speed measured end to end on a real
                # call. Not real progress (the pipeline does not expose it),
                # but it is off by a few seconds over four minutes. Counted
                # from now, so loading the model doesn't eat into it.
                job["expected"] = round(time.time() - job["started"]
                                        + audio_seconds / (T.SPEED_PRECISE if precise else T.SPEED)
                                        # telling voices apart: about 2.5 s a minute, on the CPU
                                        + (audio_seconds / 24 if voices else 0))

        t0 = time.time()
        r = T.run(original, language, progress, two_tracks=two_tracks, precise=precise,
                  voices=voices)
        taken = round(time.time() - t0)
        segments, seconds = r["segments"], r["seconds"]

        (d / f"{stem}.txt").write_text(T.as_txt(segments), encoding="utf-8")
        (d / f"{stem}.md").write_text(T.as_md(segments, stem, seconds), encoding="utf-8")
        write_words(d, segments)
        info = {
            **keep,
            "original": original.name,
            "transcribed_at": time.strftime("%Y-%m-%d %H:%M"),
            "model": T.MODEL,
            "language": r["language"],
            "language_requested": language or "auto",
            "duration_s": round(seconds, 1),
            "seconds_taken": taken,
            "silence_s": round(seconds - r["speech_seconds"]),
            # A number, not the name -> count dictionary: the page prints it
            # and /api/reapply adds to it.
            "names_corrected": sum(r["corrected"].values()),
            "names_by_name": r["corrected"],
            "phantoms_dropped": [{"minute": T.mmss(s["start"]), "text": s["text"]}
                                 for s in r["phantoms"]],
            "words": sum(len(s["text"].split()) for s in segments),
            "segments": len(segments),
            "speech": [[round(a, 2), round(b, 2)] for a, b in r["speech"]],
            "word_times": r["word_times"],
        }
        if two_tracks:
            info["two_tracks"] = True
        if "speakers_found" in r:
            info["speakers_found"] = r["speakers_found"]
        if two_tracks or "speakers_found" in r:
            info["lines_by_speaker"] = {x["tag"]: x["lines"] for x in speakers_of(segments)}
        write_info(d, info)
        job.update(state="done", stage="done")
    except Exception as e:
        job.update(state="error", error=f"{type(e).__name__}: {e}")
        # The recording stays in its folder: it can be transcribed again.
        if d.exists():
            write_info(d, {**before, "status": "failed", "error": job["error"]})


def counter():
    """One job at a time: two together slow each other down."""
    while True:
        args = line_up.get()
        try:
            process(*args)
        finally:
            line_up.task_done()


def start(data: pathlib.Path, glossary: pathlib.Path | None = None, model: bool = True):
    """Startup side effects, run once from __main__ after the options are read.

    With model=False the page browses existing transcripts and nothing is
    loaded: a way to try the interface, or read old calls, without a GPU.
    """
    global DATA, INCOMING, RECORDINGS
    if glossary is not None:
        T.GLOSSARY = glossary.resolve()
    DATA = data.resolve()
    INCOMING = DATA / "_incoming"
    RECORDINGS = DATA / "_recordings"
    DATA.mkdir(parents=True, exist_ok=True)
    sweep()
    # Whisper is loaded by the first transcription, not here: recording,
    # reading and correcting don't need it, and loading it at start took the
    # whole of Python for seconds and 3.4 GB of the GPU for the day.
    if model:
        engine_state["ready"] = True
        threading.Thread(target=unload_when_idle, daemon=True).start()
    else:
        engine_state["off"] = True
    threading.Thread(target=counter, daemon=True).start()


def refuse_if_off():
    if engine_state["off"]:
        return JSONResponse({"error": "transcription is off: the server was started with --no-model"}, 503)
    if not engine_state["ready"]:
        return JSONResponse({"error": engine_state["error"] or "the model is still loading"}, 503)
    return None


def language_of(language: str | None) -> str | None:
    if not language or language == "auto":
        return None
    return re.sub(r"[^a-z]", "", language.lower())[:3] or None


def enqueue(original: pathlib.Path, name: str, language: str | None, two_tracks=False,
            precise=False, voices=False) -> str:
    """Queues the recording already in its folder."""
    job_id = uuid.uuid4().hex[:8]
    ahead = line_up.qsize()
    d = original.parent
    info = read_info(d) if (d / "info.json").exists() else {"original": original.name}
    info.pop("error", None)
    write_info(d, {**info, "status": "queued"})
    jobs[job_id] = {"state": "running", "name": name, "folder": d.name,
                    "stage": f"queued, {ahead} ahead" if ahead else "queued",
                    "started": time.time()}
    line_up.put((job_id, original, language, two_tracks, precise, voices))
    return job_id


def busy(d: pathlib.Path) -> bool:
    """Whether a transcription is queued or running on this folder."""
    return any(j["state"] == "running" and j.get("folder") == d.name for j in jobs.values())


def voices_installed() -> bool:
    """Whether telling voices apart can run: its packages are optional."""
    return all(importlib.util.find_spec(m) is not None for m in ("sherpa_onnx", "onnxruntime", "scipy"))


@app.get("/api/status")
def api_status():
    import voices as V
    return {**engine_state, "model": T.MODEL, "loaded": T.loaded(), "queued": line_up.qsize(), "version": VERSION,
            # The page says "downloads 32 MB the first time" until it is on disk.
            "voices": voices_installed(), "voices_ready": V.ready()}


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...), language: str = Form("auto"),
                         two_tracks: bool = Form(False), precise: bool = Form(False),
                         voices: bool = Form(False)):
    """Adds a recording and transcribes it at once, in one call: for scripts.

    The page adds first (/api/uploads) and transcribes when asked
    (/api/transcribe/{name}). Several files: one request each, they run one
    after the other.
    """
    refused = refuse_if_off()
    if refused:
        return refused
    dest = INCOMING / f"{uuid.uuid4().hex[:8]}{pathlib.Path(file.filename).suffix or '.bin'}"
    dest.write_bytes(await file.read())
    original = take(dest, file.filename)
    return {"job": enqueue(original, file.filename, language_of(language), two_tracks, precise,
                           voices and voices_installed())}


@app.post("/api/uploads")
async def api_upload(file: UploadFile = File(...)):
    """Adds a recording without transcribing it: it waits in the list.

    Works without the model too: adding is only keeping a file.
    """
    dest = INCOMING / f"{uuid.uuid4().hex[:8]}{pathlib.Path(file.filename).suffix or '.bin'}"
    dest.write_bytes(await file.read())
    original = take(dest, file.filename)
    write_info(original.parent, {"original": original.name, "status": "waiting",
                                 "uploaded_at": time.strftime("%Y-%m-%d %H:%M"),
                                 "duration_s": probe_seconds(original)})
    return {"folder": original.parent.name}


@app.post("/api/transcribe/{name}")
async def api_transcribe_added(name: str, request: Request):
    """Transcribes a recording added before, with the choices made now."""
    d = folder(name)
    if not d.is_dir() or not (d / "info.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    refused = refuse_if_off()
    if refused:
        return refused
    if busy(d):
        return JSONResponse({"error": "it is already being transcribed"}, 409)
    if next(d.glob("*.txt"), None) is not None:
        return JSONResponse({"error": "it is already transcribed"}, 409)
    audio = audio_in(d)
    if audio is None:
        return JSONResponse({"error": "the recording is not in the folder"}, 404)
    body = await request.json() if await request.body() else {}
    info = read_info(d)
    return {"job": enqueue(d / audio, info.get("title") or audio,
                           language_of(body.get("language")),
                           two_tracks=bool(body.get("two_tracks") or info.get("two_tracks")),
                           precise=bool(body.get("precise")),
                           voices=bool(body.get("voices")) and voices_installed())}


@app.get("/api/calls/stamp")
def api_calls_stamp():
    """Changes when a call is added, removed or changed on disk: the page
    redraws its list when it does, whoever made the change (Stop in the
    icon's menu, a phone, another window). Cheap: a folder listing and a
    stat per call."""
    count, latest = 0, 0.0
    for d in DATA.iterdir() if DATA.exists() else []:
        if d.is_dir() and not d.name.startswith("_"):
            count += 1
            f = d / "info.json"
            if f.exists():
                latest = max(latest, f.stat().st_mtime)
    return {"stamp": f"{count}:{latest:.3f}"}


@app.get("/api/jobs")
def api_jobs():
    """The transcriptions running or waiting, whoever started them: Stop in
    the icon's menu, a phone, a page opened half-way. The page follows them
    all, not only the ones it asked for."""
    return {"jobs": [{"id": k, "name": j.get("name"), "folder": j.get("folder")}
                     for k, j in list(jobs.items()) if j["state"] == "running"]}


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        return JSONResponse({"error": "unknown job"}, 404)
    return {**j, "elapsed": round(time.time() - j["started"])}


# --- recording a call from the page ---------------------------------------------
# The page records two tracks (your microphone, the call's tab) and sends them
# here every few seconds while it records. A closed tab, a crashed browser or a
# laptop that goes to sleep then loses a few seconds, not the call: the pieces
# already sent are on disk, and the page offers to transcribe them.

RID = re.compile(r"^[0-9a-f]{12}$")


def recording(rid: str) -> pathlib.Path | None:
    """The recording's file: a .webm sent by the page, or a .wav recorded by
    the computer itself (recorder.py). Both end the same way."""
    if not RID.match(rid):
        return None
    wav = RECORDINGS / f"{rid}.wav"
    return wav if wav.exists() else RECORDINGS / f"{rid}.webm"


@app.post("/api/recordings")
async def api_recording_new(request: Request):
    body = await request.json() if await request.body() else {}
    rid = uuid.uuid4().hex[:12]
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    (RECORDINGS / f"{rid}.webm").write_bytes(b"")
    (RECORDINGS / f"{rid}.json").write_text(json.dumps({
        "started_at": time.strftime("%Y-%m-%d %H:%M"),
        "name": clean(body.get("name") or f"Call {time.strftime('%Y-%m-%d %H.%M')}"),
        "language": body.get("language") or "auto",
    }), encoding="utf-8")
    return {"id": rid}


@app.post("/api/recordings/{rid}/chunk")
async def api_recording_chunk(rid: str, request: Request):
    f = recording(rid)
    if f is None or not f.exists():
        return JSONResponse({"error": "unknown recording"}, 404)
    data = await request.body()
    with f.open("ab") as out:
        out.write(data)
    return {"bytes": f.stat().st_size}


@app.post("/api/recordings/{rid}/finish")
async def api_recording_finish(rid: str, request: Request):
    """Stops collecting and queues the recording for transcription, on two tracks."""
    return finish_recording(rid, await request.json() if await request.body() else {})


def finish_recording(rid: str, body: dict):
    f = recording(rid)
    if f is None or not f.exists():
        return JSONResponse({"error": "unknown recording"}, 404)
    empty = 0
    if f.suffix == ".wav":
        recorder.repair(f)                 # cut off mid-call, its header is behind
        empty = recorder.HEADER
    if f.stat().st_size <= empty:
        return JSONResponse({"error": "the recording is empty"}, 400)
    refused = refuse_if_off()
    if refused:
        return refused
    meta_f = RECORDINGS / f"{rid}.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
    choose = lambda k: body[k] if k in body else meta.get(k)          # noqa: E731
    name = clean(choose("name") or "Call") + f.suffix
    dest = INCOMING / f"{rid}{f.suffix}"
    shutil.move(str(f), dest)
    meta_f.unlink(missing_ok=True)
    original = take(dest, name)
    return {"job": enqueue(original, name, language_of(choose("language")), two_tracks=True,
                           precise=bool(choose("precise")),
                           voices=bool(choose("voices")) and voices_installed())}


@app.get("/api/recordings")
def api_recordings():
    """Recordings that were never finished: the page offers to save them."""
    out = []
    for meta_f in sorted(RECORDINGS.glob("*.json")) if RECORDINGS.exists() else []:
        f = recording(meta_f.stem)
        if f is None or not f.exists() or (capture and capture["id"] == meta_f.stem):
            continue                       # the one recording now is not interrupted
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        out.append({"id": meta_f.stem, **meta, "bytes": f.stat().st_size,
                    "idle_s": round(time.time() - f.stat().st_mtime)})
    return {"recordings": out}


@app.delete("/api/recordings/{rid}")
def api_recording_delete(rid: str):
    f = recording(rid)
    if f is None:
        return JSONResponse({"error": "unknown recording"}, 404)
    f.unlink(missing_ok=True)
    (RECORDINGS / f"{rid}.json").unlink(missing_ok=True)
    return {"deleted": True}


# --- recording from the computer itself (recorder.py) -----------------------------
# Your microphone and everything the computer plays, on the same two tracks
# as the page's: any call, nothing shared on screen. Only from the computer
# Sottovoce runs on: a phone on the Wi-Fi (--lan) must not switch on this
# computer's microphone.

capture = None             # {"id", "capture": recorder.Capture, "name"} while one runs
LOCAL = {"127.0.0.1", "::1"}


def from_here(request: Request):
    if (request.client.host if request.client else "") not in LOCAL:
        return JSONResponse({"error": "recording works only on the computer running Sottovoce"}, 403)
    return None


def open_in_files(path: pathlib.Path):
    """The folder, in the computer's own file manager."""
    import sys
    if sys.platform == "win32":
        os.startfile(path)                                      # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


@app.post("/api/folder")
async def api_folder(request: Request):
    """Opens the folder of the calls, or of one call (its recording and its
    texts), in Explorer. Only on the computer itself: a phone can't open the
    computer's windows."""
    refused = from_here(request)
    if refused:
        return refused
    body = await request.json() if await request.body() else {}
    d = folder(body["name"]) if body.get("name") else DATA
    if not d.is_dir():
        return JSONResponse({"error": "not found"}, 404)
    open_in_files(d)
    return {"opened": True}


@app.get("/api/capture")
def api_capture():
    now = None
    if capture:
        c = capture["capture"]
        now = {"id": capture["id"], "name": capture["name"], "seconds": round(c.seconds, 1),
               "levels": [round(v, 3) for v in c.levels], "error": c.error}
    return {"available": recorder.available(), "recording": now}


@app.post("/api/capture")
async def api_capture_start(request: Request):
    global capture
    refused = from_here(request)
    if refused:
        return refused
    if capture:
        return JSONResponse({"error": "already recording"}, 409)
    if not recorder.available():
        return JSONResponse({"error": "recording the computer's sound needs Windows"}, 503)
    body = await request.json() if await request.body() else {}
    rid = uuid.uuid4().hex[:12]
    RECORDINGS.mkdir(parents=True, exist_ok=True)
    name = clean(body.get("name") or f"Call {time.strftime('%Y-%m-%d %H.%M')}")
    meta_f = RECORDINGS / f"{rid}.json"
    # The choices travel with the recording: Stop from the icon by the clock,
    # or a recording saved after a crash, transcribes the way it was asked.
    meta_f.write_text(json.dumps({
        "started_at": time.strftime("%Y-%m-%d %H:%M"), "name": name,
        "language": body.get("language") or "auto", "precise": bool(body.get("precise")),
        "voices": bool(body.get("voices")), "from": "computer"}), encoding="utf-8")
    c = recorder.Capture(RECORDINGS / f"{rid}.wav")
    try:
        c.start()
    except Exception as e:
        meta_f.unlink(missing_ok=True)
        return JSONResponse({"error": f"the recording did not start: {e}"}, 503)
    capture = {"id": rid, "capture": c, "name": name}
    return {"id": rid}


def stop_capture():
    """Stops the recording and keeps its file, unfinished: what Quit does, so
    the next start offers it like any interrupted recording. Returns its id."""
    global capture
    if not capture:
        return None
    now, capture = capture, None
    now["capture"].stop()
    return now["id"]


@app.post("/api/capture/stop")
async def api_capture_stop(request: Request):
    refused = from_here(request)
    if refused:
        return refused
    if not capture:
        return JSONResponse({"error": "nothing is being recorded"}, 404)
    body = await request.json() if await request.body() else {}
    rid = stop_capture()
    if not body.get("keep", True):
        recording(rid).unlink(missing_ok=True)
        (RECORDINGS / f"{rid}.json").unlink(missing_ok=True)
        return {"discarded": True}
    if not body.get("transcribe", True):
        return keep_for_later(rid, body.get("name"))
    return finish_recording(rid, {k: body[k] for k in ("name", "language", "precise", "voices") if k in body})


def keep_for_later(rid: str, name: str | None = None):
    """A stopped recording kept as a call to transcribe later, like an added
    file: in the list, "Not transcribed", remembering its two tracks."""
    f = recording(rid)
    if f is None or not f.exists():
        return JSONResponse({"error": "unknown recording"}, 404)
    recorder.repair(f)
    meta_f = RECORDINGS / f"{rid}.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
    dest = INCOMING / f"{rid}{f.suffix}"
    shutil.move(str(f), dest)
    meta_f.unlink(missing_ok=True)
    original = take(dest, clean(name or meta.get("name") or "Call") + f.suffix)
    write_info(original.parent, {"original": original.name, "status": "waiting", "two_tracks": True,
                                 "uploaded_at": meta.get("started_at") or time.strftime("%Y-%m-%d %H:%M"),
                                 "duration_s": probe_seconds(original)})
    return {"folder": original.parent.name}


# --- history ----------------------------------------------------------------------

@app.get("/api/history")
def api_history():
    out = []
    running = {j["folder"]: j for j in jobs.values() if j["state"] == "running" and j.get("folder")}
    for d in DATA.iterdir():
        if not d.is_dir() or not (d / "info.json").exists():
            continue
        try:
            data = read_info(d)
        except (json.JSONDecodeError, OSError):
            continue
        # Words are counted from the .txt, not taken from info.json: that number
        # was written at transcription time and every correction makes it old
        # (a two-word name corrected into a one-word one). The same fact shown
        # in two places on the page must come from the same source.
        _, segments = read_call(d, data.get("duration_s"))
        data["words"] = sum(len(s["text"].split()) for s in segments)
        data.pop("speech", None)        # the map is for the strip, not the list
        data["name"] = data.get("title") or data.get("original") or d.name
        data["status"] = data.get("status") or "done"
        j = running.get(d.name)
        if j:
            data["status"] = "queued" if j["stage"].startswith("queued") else "transcribing"
            data.update(stage=j["stage"], expected=j.get("expected", 0),
                        elapsed=round(time.time() - j["started"]))
        out.append({"folder": d.name, **data})
    # Newest first by when it was transcribed, or added. Folder names only
    # carry the day: two calls of the same day would otherwise sort by title.
    out.sort(key=lambda e: (e.get("transcribed_at") or e.get("uploaded_at") or "", e["folder"]),
             reverse=True)
    return {"history": out}


@app.get("/api/search")
def api_search(q: str = "", around: int = 60):
    """Searches a word across every transcript.

    Reads the .txt files one by one: fifty calls are two megabytes, and a real
    index would be one more thing to keep in sync for nothing. At five hundred
    it will be time to rethink it.
    """
    q = q.strip()
    if len(q) < 2:
        return {"results": [], "query": q}
    rx = re.compile(re.escape(q), re.IGNORECASE)
    out = []
    for d in sorted(DATA.iterdir(), reverse=True):
        txt = next(d.glob("*.txt"), None) if d.is_dir() else None
        if txt is None:
            continue
        hits = []
        for line in txt.read_text(encoding="utf-8").splitlines():
            p = T.parse_line(line)
            if not p or not rx.search(p[2]):
                continue
            text = p[2]
            k = rx.search(text).start()
            a, b = max(0, k - around), min(len(text), k + len(q) + around)
            hits.append({"minute": T.mmss(p[0]), "seconds": p[0], "speaker": p[1],
                         "snippet": ("…" if a else "") + text[a:b]
                                    + ("…" if b < len(text) else "")})
        if hits:
            out.append({"folder": d.name, "count": len(hits), "lines": hits[:8]})
    return {"results": out, "query": q, "total": sum(r["count"] for r in out)}


def speech_of(d: pathlib.Path, data: dict, audio: str | None):
    """Where people speak in the call, for the strip: from info.json, or measured.

    New transcriptions save it while they work. Older ones did not, and it is
    measured here the first time they are opened (a few seconds, once) and
    written into info.json, so the next time it is already there.

    If it cannot be measured (recording gone, ffmpeg failing) this returns None
    and the page draws no speech layer, instead of drawing a fake one.
    """
    if data.get("speech") is not None:
        return data["speech"]
    if not audio:
        return None
    try:
        speech = [[round(a, 2), round(b, 2)] for a, b in T.speech_map(d / audio)]
    except Exception as e:
        print(f"  could not measure speech for {d.name}: {e}")
        return None
    data["speech"] = speech
    write_info(d, data)
    return speech


def names_in(txt: pathlib.Path):
    """How many times each glossary name appears in this transcript.

    It says which names matter in this call, which is what to look after: a
    name said eleven times and garbled ruins the reading, one said once does
    not.
    """
    text = txt.read_text(encoding="utf-8")
    seen, out = set(), []
    for _, right in T.glossary():
        if right in seen:
            continue
        seen.add(right)
        n = len(re.findall(rf"\b{re.escape(right)}\b", text, re.IGNORECASE))
        if n:
            out.append({"name": right, "count": n})
    out.sort(key=lambda x: -x["count"])
    return out


def corrections_of(d: pathlib.Path):
    """Where lines were corrected, for the strip.

    Read again from `corrections.jsonl` instead of keeping a separate count:
    the file is the source, and a second count would drift at the first
    correction made outside the page.
    """
    f = d / "corrections.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        m = re.match(r"^(\d+):(\d+)$", (c.get("minute") or "").strip())
        if m:
            out.append({"seconds": int(m[1]) * 60 + int(m[2]),
                        "source": c.get("source", "manual")})
    return out


@app.get("/api/history/{name}")
def api_open(name: str):
    d = folder(name)
    if not d.is_dir() or not (d / "info.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    data = read_info(d)
    txt, segments = read_call(d, data.get("duration_s"))
    audio = audio_in(d)
    if txt is None:
        # Added and not transcribed yet (or failed): what the page needs to
        # show the recording and transcribe it.
        if data.get("status") in ("waiting", "queued", "transcribing", "failed"):
            j = next((j for j in jobs.values() if j["state"] == "running"
                      and j.get("folder") == d.name), None)
            status = data["status"]
            if j:
                status = "queued" if j["stage"].startswith("queued") else "transcribing"
            return {"folder": d.name, "pending": True, "status": status, "audio": audio,
                    "name": data.get("title") or data.get("original") or d.name,
                    "duration": data.get("duration_s") or 0,
                    "uploaded_at": data.get("uploaded_at"), "error": data.get("error"),
                    "stage": j["stage"] if j else None,
                    "expected": j.get("expected", 0) if j else 0,
                    "elapsed": round(time.time() - j["started"]) if j else 0}
        return JSONResponse({"error": "transcript missing"}, 404)
    summary_md = d / "summary.md"
    names = data.get("speaker_names") or {}
    return {"folder": d.name, "stem": txt.stem, "audio": audio,
            "name": data.get("title") or data.get("original", txt.stem),
            "language": data.get("language"),
            "two_tracks": bool(data.get("two_tracks")),
            "word_times": data.get("word_times"),
            # Who speaks, with the names given to them; speakers_found is
            # there once the voices were told apart (1 when only one was).
            "speakers": speakers_of(segments, names),
            "speaker_names": names,
            "speakers_found": data.get("speakers_found"),
            "duration": data.get("duration_s") or 0,
            "seconds_taken": data.get("seconds_taken", 0),
            "segments": segments, "paragraphs": T.paragraphs(segments),
            "suspicious": T.suspicious(segments),
            "summary": summary_md.read_text(encoding="utf-8") if summary_md.exists() else None,
            "followup": (d / "followup.md").read_text(encoding="utf-8")
                        if (d / "followup.md").exists() else None,
            "names_corrected": data.get("names_corrected") or 0,
            # For the strip: where a phrase was dropped and where a line was
            # corrected. These are the places where the text was touched, and
            # the strip shows them on the real duration.
            "phantoms": data.get("phantoms_dropped") or [],
            "corrections": corrections_of(d),
            "names": names_in(txt),
            "speech": speech_of(d, data, audio)}


def notes(d: pathlib.Path, info: dict, stem: str, segments) -> tuple[str, str]:
    """The notes of a call, as one Markdown file for the client's folder.

    Who, when and how long; the summary, if there is one; then the whole
    transcript with names and minutes. Written in the language of the call:
    a file meant to sit next to the client's other documents, and to be read
    by whoever (or whatever) works on that client next.
    """
    it = info.get("language") == "it"
    t = (lambda i, e: i if it else e)
    names = info.get("speaker_names") or {}
    title = info.get("title") or stem
    day = d.name.split("_", 1)[0] if "_" in d.name else ""
    out = [f"# {title}", ""]
    facts = [f"{t('Data', 'Date')}: {day}" if day else None,
             f"{t('Durata', 'Duration')}: {T.mmss(info.get('duration_s') or 0)}",
             f"{t('Lingua', 'Language')}: {info.get('language') or '?'}"]
    out.append(" · ".join(x for x in facts if x))
    people = speakers_of(segments, names)
    if people:
        def label(x):
            if x["name"]:
                return x["name"] + (t(" (io)", " (me)") if x["tag"] == "Me" else "")
            return {"Me": t("Io", "Me"), "Them": t("Loro", "Them")}.get(x["tag"], x["tag"])
        out.append(f"{t('Partecipanti', 'People')}: "
                   + ", ".join(f"{label(x)} ({T.mmss(x['seconds'])})" for x in people))
    out += ["", f"## {t('Riassunto', 'Summary')}", ""]
    summary_md = d / "summary.md"
    if summary_md.exists():
        # one level down, under this file's own title
        body = re.sub(r"^(#{1,5}) ", lambda m: "#" + m[1] + " ",
                      summary_md.read_text(encoding="utf-8").strip(), flags=re.M)
        out.append(body)
    else:
        out.append(t("_Nessun riassunto: si può chiedere dalla pagina della call._",
                     "_No summary yet: it can be asked for on the call's page._"))
    out += ["", f"## {t('Trascrizione', 'Transcript')}", ""]
    for p in T.paragraphs(segments):
        by = f" · {T.who(p, names)}" if p.get("speaker") else ""
        out.append(f"**{T.mmss(p['start'])}{by}** — {p['text']}\n")
    return "\n".join(out).rstrip() + "\n", t("appunti", "notes")


@app.get("/api/history/{name}/download.{fmt}")
def api_download(name: str, fmt: str):
    """The transcript as .txt, .md, .srt, .vtt or .json.

    txt and md are the files in the folder. The others are written on the fly
    from the .txt and the word timings, so they always match the corrections.
    So is the .txt when the voices have names: the file keeps "[Voice 2]",
    the download says who Voice 2 is.
    """
    d = folder(name)
    if fmt == "notes" and d.is_dir() and (d / "info.json").exists():
        info = read_info(d)
        txt, segments = read_call(d, info.get("duration_s"))
        if txt is None:
            return JSONResponse({"error": "not found"}, 404)
        body, word = notes(d, info, txt.stem, segments)
        filename = f"{txt.stem} - {word}.md"
        return Response(body, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''"
                                 + urllib.parse.quote(filename)})
    if fmt not in T.FORMATS or not d.is_dir():
        return JSONResponse({"error": "not found"}, 404)
    names = names_of(d)
    if fmt == "md" or (fmt == "txt" and not names):
        f = next(d.glob(f"*.{fmt}"), None)
        if f is None:
            return JSONResponse({"error": "not found"}, 404)
        return FileResponse(f, filename=f.name, media_type="text/plain; charset=utf-8")
    info = read_info(d) if (d / "info.json").exists() else {}
    txt, segments = read_call(d, info.get("duration_s"))
    if txt is None:
        return JSONResponse({"error": "not found"}, 404)
    body = T.render(fmt, segments, txt.stem, info.get("duration_s") or 0, names,
                    language=info.get("language"), model=info.get("model"))
    kind = {"txt": "text/plain", "srt": "application/x-subrip", "vtt": "text/vtt",
            "json": "application/json"}[fmt]
    return Response(body, media_type=f"{kind}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{txt.stem}.{fmt}"'})


@app.get("/api/audio/{name}")
def api_audio(name: str):
    """The recording, for the player on the page.

    It is already in the job's folder: not duplicated, served from there.
    """
    d = folder(name)
    a = audio_in(d) if d.is_dir() else None
    if a is None:
        return JSONResponse({"error": "audio not found"}, 404)
    return FileResponse(d / a)


@app.post("/api/correct/{name}")
def api_correct(name: str, body: dict):
    """Saves a line corrected by hand. This is the operation that builds the asset.

    Every corrected line becomes a pair (audio, right text): the material to
    fine-tune Whisper one day on your own domain: your language, your names,
    your calls, recorded badly. It is collected from day one even if training
    comes in a year: a dataset cannot be recovered afterwards.

    The .txt is rewritten (it is the source everything else is rebuilt from),
    and the correction also goes into `corrections.jsonl`, which keeps the
    BEFORE and the AFTER. The right text alone would not be enough: to learn,
    you also need what the model had heard.

    `index` is the position of the line as the page shows it. The speaker tag
    and the timestamp stay; the word timings are realigned to the new text.
    """
    d = folder(name)
    if not d.is_dir():
        return JSONResponse({"error": "transcript not found"}, 404)
    txt, segments = read_call(d)
    if txt is None:
        return JSONResponse({"error": "transcript not found"}, 404)

    index, new = body.get("index"), " ".join((body.get("text") or "").split())
    if not isinstance(index, int) or not new:
        return JSONResponse({"error": "index and text are required"}, 400)
    if not 0 <= index < len(segments):
        return JSONResponse({"error": "no such line"}, 400)

    s = segments[index]
    rows = txt.read_text(encoding="utf-8").splitlines()
    m = T.PREFIX.match(rows[s["row"]])
    before = s["text"]
    if before == new:
        return {"unchanged": True}

    rows[s["row"]] = m[1] + new
    txt.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with (d / "corrections.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"),
                            "minute": T.mmss(s["start"]), "line": index,
                            "before": before, "after": new, "source": "manual"},
                           ensure_ascii=False) + "\n")
    if s.get("words"):
        s["words"] = T.realign(s["words"], new)
    s["text"] = new
    write_words(d, segments)
    _write_md(d, txt)
    return {"saved": True, "words": s.get("words")}


@app.post("/api/history/{name}/rename")
def api_rename(name: str, body: dict):
    """A new name for a call: its folder and its files follow.

    The day the folder started with stays: it is when the call happened, or
    was added, and the list sorts by it.
    """
    d = folder(name)
    if not d.is_dir() or not (d / "info.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    if busy(d):
        return JSONResponse({"error": "it is being transcribed: rename it when it is done"}, 409)
    title = " ".join(str(body.get("name") or "").split())
    if not title:
        return JSONResponse({"error": "the name is empty"}, 400)
    if len(title) > 120:
        return JSONResponse({"error": "a name is at most 120 characters"}, 400)
    stem = clean(title)
    day = d.name.split("_", 1)[0] if re.match(r"^\d{4}-\d{2}-\d{2}_", d.name) else f"{date.today():%Y-%m-%d}"
    target = DATA / f"{day}_{stem}"
    if target.name.lower() != d.name.lower() and target.exists():
        return JSONResponse({"error": "another call already has that name"}, 409)
    info = read_info(d)
    txt = next(d.glob("*.txt"), None)
    audio = audio_in(d)
    old = txt.stem if txt else (pathlib.Path(audio).stem if audio else None)
    try:
        if target != d:
            d.rename(target)               # first: if a file is in use, nothing moved
            d = target
        for f in list(d.iterdir()):
            if f.is_file() and old and f.stem == old and (f.suffix.lower() in AUDIO
                                                          or f.suffix in (".txt", ".md")):
                f.rename(f.with_name(stem + f.suffix))
    except OSError:
        return JSONResponse({"error": "a file of this call is in use (is it playing?): "
                                      "stop it and try again"}, 409)
    if audio:
        info["original"] = stem + pathlib.Path(audio).suffix
    info["title"] = title
    write_info(d, info)
    txt = next(d.glob("*.txt"), None)
    if txt is not None:
        _write_md(d, txt)
    return {"folder": d.name, "name": title}


@app.delete("/api/history/{name}")
def api_delete(name: str):
    """Deletes a call by moving its folder to _deleted/, not by erasing it.

    These are client recordings: a wrong tap must be recoverable, from the
    file explorer. Emptying _deleted/ is left to you.
    """
    d = folder(name)
    if not d.is_dir() or not (d / "info.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    if busy(d):
        return JSONResponse({"error": "it is being transcribed: wait for it to finish"}, 409)
    bin_ = DATA / "_deleted"
    bin_.mkdir(exist_ok=True)
    dest = bin_ / d.name
    if dest.exists():
        dest = bin_ / f"{d.name} ({time.strftime('%Y-%m-%d %H.%M.%S')})"
    try:
        shutil.move(str(d), str(dest))
    except OSError:
        return JSONResponse({"error": "a file of this call is in use (is it playing?): "
                                      "stop it and try again"}, 409)
    return {"deleted": True, "kept_in": f"_deleted/{dest.name}"}


def _write_md(d: pathlib.Path, txt: pathlib.Path):
    """The .md is rebuilt from the .txt: one source, no copy to keep in line.

    It is the file meant for reading, so it carries the voices' names.
    """
    info = read_info(d)
    _, segments = read_call(d, info.get("duration_s"))
    d.joinpath(f"{txt.stem}.md").write_text(
        T.as_md(segments, txt.stem, info.get("duration_s") or 0, info.get("speaker_names")),
        encoding="utf-8")


# --- voices -------------------------------------------------------------------

def _name_problem(name: str) -> str | None:
    if len(name) > 40:
        return "a name is at most 40 characters"
    if any(c in name for c in "[]\n\r"):
        return "a name cannot contain brackets or line breaks"
    return None


@app.post("/api/speakers/{name}")
def api_speakers(name: str, body: dict):
    """Names for the voices of a call: {"names": {"Voice 1": "Maya"}}.

    Kept in info.json, not written into the lines: the .txt says "[Voice 1]"
    and stays that way, so a wrong name is undone by changing one word. An
    empty name takes the label back.
    """
    d = folder(name)
    if not d.is_dir() or not (d / "info.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    txt, segments = read_call(d)
    if txt is None:
        return JSONResponse({"error": "transcript missing"}, 404)
    given = body.get("names")
    if not isinstance(given, dict):
        return JSONResponse({"error": "names is required, as {label: name}"}, 400)
    present = {x["tag"] for x in speakers_of(segments)}
    info = read_info(d)
    names = dict(info.get("speaker_names") or {})
    for tag, value in given.items():
        if tag not in present:
            return JSONResponse({"error": f"nobody is labelled {tag!r} in this call"}, 400)
        value = " ".join(str(value or "").split())
        problem = _name_problem(value)
        if problem:
            return JSONResponse({"error": problem}, 400)
        if value and value != tag:
            names[tag] = value
        else:
            names.pop(tag, None)
    info["speaker_names"] = names
    write_info(d, info)
    _write_md(d, txt)
    return {"speaker_names": names, "speakers": speakers_of(segments, names)}


_voices_busy = threading.Lock()


@app.post("/api/voices/{name}")
def api_voices(name: str):
    """Tells the voices apart in a call already transcribed.

    Needs the recording, not the model: it works with --no-model too. The
    words keep their times; only who said them changes, and lines are split
    where the voice changes inside one. On two tracks "Me" stays "Me".

    The lines change, so names given before are dropped (Voice 2 may now be
    someone else) and so is the summary, which was written on the old labels.
    """
    d = folder(name)
    if not d.is_dir() or not (d / "info.json").exists():
        return JSONResponse({"error": "not found"}, 404)
    if not voices_installed():
        return JSONResponse({"error": "telling voices apart needs: pip install sherpa-onnx onnxruntime scipy"}, 503)
    audio = audio_in(d)
    if audio is None:
        return JSONResponse({"error": "the recording is not in the folder"}, 404)
    txt, segments = read_call(d)
    if txt is None or not segments:
        return JSONResponse({"error": "transcript missing"}, 404)
    if not _voices_busy.acquire(blocking=False):
        return JSONResponse({"error": "voices are already being told apart in another call"}, 409)
    try:
        info = read_info(d)
        two = bool(info.get("two_tracks"))
        words, speakers, breaks = [], [], set()
        for s in segments:
            breaks.add(len(words))
            for w in s["words"]:
                words.append(list(w))
                speakers.append("Me" if s.get("speaker") == "Me" else ("Them" if two else None))
        import tempfile
        t0 = time.time()
        if two:
            _, track, _ = T.read_two_tracks(d / audio)
        else:
            import soundfile as sf
            with tempfile.TemporaryDirectory() as tmp:
                wav = pathlib.Path(tmp) / "audio.wav"
                T.prepare(d / audio, wav)
                track, _ = sf.read(str(wav), dtype="float32")
        labels, found = T.tell_voices(words, track, speakers if two else None, breaks=breaks)
        info["speakers_found"] = found
        info["voices_seconds"] = round(time.time() - t0)
        if found < 2:
            write_info(d, info)
            return {"speakers_found": found, "changed": False}

        lines = T.lines_from_words(words, labels, breaks)
        # Phantom lines were dropped at transcription; what is left keeps its
        # text exactly, so the lines are rebuilt from the words alone.
        txt.write_text(T.as_txt(lines), encoding="utf-8")
        write_words(d, lines)
        info["speaker_names"] = {k: v for k, v in (info.get("speaker_names") or {}).items()
                                 if k == "Me"}
        info["segments"] = len(lines)
        info["lines_by_speaker"] = {x["tag"]: x["lines"] for x in speakers_of(lines)}
        write_info(d, info)
        _write_md(d, txt)
        (d / "summary.md").unlink(missing_ok=True)
        (d / "followup.md").unlink(missing_ok=True)
        return {"speakers_found": found, "changed": True, "lines": len(lines)}
    finally:
        _voices_busy.release()


# --- the summary --------------------------------------------------------------
# Written by an LLM running on this machine, spoken to over the OpenAI
# protocol. Not loaded inside this process: see summary.py for why.

@app.get("/api/llm")
def api_llm():
    """Who is answering, if anyone. The page hides the button otherwise.

    A button that errors is worse than a button that is not there: the first
    makes the program look broken, the second makes the feature look absent.
    """
    s = S.available()
    return {"available": bool(s), **(s or {})}


@app.post("/api/summary/{name}")
def api_summary(name: str, redo: bool = False):
    """The summary of the call, saved next to its transcript.

    Redone only on request. Once written it is on disk, and regenerating it at
    every opening would cost fifteen seconds to get *almost* the same thing:
    "almost" because an LLM is not deterministic, and two different summaries
    of the same call make you doubt both.
    """
    d = folder(name)
    if not d.is_dir():
        return JSONResponse({"error": "not found"}, 404)

    done = d / "summary.md"
    if done.exists() and not redo:
        return {"text": done.read_text(encoding="utf-8"), "from_disk": True}

    txt, segments = read_call(d)
    if txt is None:
        return JSONResponse({"error": "transcript missing"}, 404)

    # The text goes without timestamps: a timestamp costs a token per line,
    # which over 550 lines is a tenth of the prompt spent on nothing. Who spoke
    # goes with it when it is known: "who does what" is half of a summary.
    names = names_of(d)
    text = "\n".join((f"{T.who(s, names)}: " if s.get("speaker") else "") + s["text"]
                     for s in segments)
    t0 = time.time()
    r = S.summarize(text)
    if "error" in r:
        return JSONResponse(r, 503)

    done.write_text(r["text"], encoding="utf-8")
    secs = round(time.time() - t0, 1)
    if (d / "info.json").exists():
        data = read_info(d)
        data["summary"] = {"model": r["model"], "via": r["program"],
                           "tokens_read": r["tokens_read"], "seconds": secs,
                           "at": time.strftime("%Y-%m-%d %H:%M")}
        write_info(d, data)
    return {**r, "seconds": secs, "from_disk": False}


@app.post("/api/followup/{name}")
def api_followup(name: str, body: dict | None = None, redo: bool = False):
    """The follow-up email of the call, saved next to it as followup.md.

    Written by the local LLM, from you to the others, in the call's language.
    With {"text": ...} it saves your edited version instead: the email is
    yours to change, and a draft kept only in the page would be lost at the
    next click.
    """
    d = folder(name)
    if not d.is_dir():
        return JSONResponse({"error": "not found"}, 404)
    done = d / "followup.md"
    if body and isinstance(body.get("text"), str):
        done.write_text(body["text"].strip() + "\n", encoding="utf-8")
        return {"text": done.read_text(encoding="utf-8"), "saved": True}
    if done.exists() and not redo:
        return {"text": done.read_text(encoding="utf-8"), "from_disk": True}
    txt, segments = read_call(d)
    if txt is None:
        return JSONResponse({"error": "transcript missing"}, 404)
    names = names_of(d)
    known = any(s.get("speaker") for s in segments)
    text = "\n".join((f"{T.who(s, names)}: " if s.get("speaker") else "") + s["text"]
                     for s in segments)
    me = names.get("Me") or ("Me" if any(s.get("speaker") == "Me" for s in segments) else None)
    others = [T.who({"speaker": x["tag"]}, names) for x in speakers_of(segments, names)
              if x["tag"] != "Me"]
    t0 = time.time()
    r = S.followup(text, me, others, known)
    if "error" in r:
        return JSONResponse(r, 503)
    done.write_text(r["text"] + "\n", encoding="utf-8")
    return {**r, "seconds": round(time.time() - t0, 1), "from_disk": False}


# --- the glossary -------------------------------------------------------------
# The table of names is a text file, and stays a text file: it opens in any
# editor and reads the same in two years. The page is a convenient way to
# write it, not its format.

@app.post("/api/reapply/{name}")
def api_reapply(name: str):
    """Applies the glossary again to a transcript already done.

    The glossary grows: you discover a garbled name while reading, and add the
    line afterwards. Without this, the benefit only reaches future calls and
    the old ones stay wrong forever, which is also the surest way never to
    trust the archive.

    Goes through the same apply_glossary() as the transcription, and writes to
    `corrections.jsonl` like a hand correction: the before is kept, so it is
    reversible and ends up in the material for fine-tuning.
    """
    d = folder(name)
    if not d.is_dir():
        return JSONResponse({"error": "not found"}, 404)
    txt, segments = read_call(d)
    if txt is None:
        return JSONResponse({"error": "not found"}, 404)

    rows = txt.read_text(encoding="utf-8").splitlines()
    rules = T.glossary()
    at = time.strftime("%Y-%m-%d %H:%M")
    changes, names = [], {}
    for i, s in enumerate(segments):
        before = s["text"]
        done = T.apply_glossary([s], rules)
        if done and s["text"] != before:
            rows[s["row"]] = T.PREFIX.match(rows[s["row"]])[1] + s["text"]
            changes.append({"at": at, "minute": T.mmss(s["start"]), "line": i,
                            "before": before, "after": s["text"], "source": "glossary"})
            for right, n in done.items():
                names[right] = names.get(right, 0) + n

    if not changes:
        return {"corrected": 0, "names": {}}

    txt.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with (d / "corrections.jsonl").open("a", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    write_words(d, segments)
    _write_md(d, txt)

    # The count has to be rewritten, or the page keeps saying no names were
    # corrected right after twenty-seven were.
    info = read_info(d)
    info["names_corrected"] = (info.get("names_corrected") or 0) + sum(names.values())
    write_info(d, info)

    # The summary was written on the old text: it no longer holds.
    (d / "summary.md").unlink(missing_ok=True)
    (d / "followup.md").unlink(missing_ok=True)
    return {"corrected": sum(names.values()), "lines": len(changes), "names": names}


@app.get("/api/glossary")
def api_glossary():
    """The table, with how many times each name appears across the calls.

    It counts occurrences of the RIGHT name in the texts: how much that name
    weighs in the work, not how many times the rule fired. The second number
    would be more flattering and less useful: the reader needs to know which
    names matter, to look after those.
    """
    texts = []
    for d in DATA.iterdir():
        t = next(d.glob("*.txt"), None) if d.is_dir() else None
        if t is not None:
            texts.append(t.read_text(encoding="utf-8"))

    f = T.glossary_file()
    out = []
    for line in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []):
        line = line.split("#")[0].strip()
        if "<-" not in line:
            continue
        right, variants = line.split("<-", 1)
        right = right.strip()
        rx = re.compile(rf"\b{re.escape(right)}\b", re.IGNORECASE)
        out.append({"right": right,
                    "variants": [v.strip() for v in variants.split(",") if v.strip()],
                    "count": sum(len(rx.findall(t)) for t in texts)})
    return {"rules": out, "file": str(f)}


@app.post("/api/glossary")
def api_glossary_add(body: dict):
    """Adds a line to the table.

    Never rewrites the existing lines nor their order: the file is written by
    hand by a person, with their comments, and a program reordering it would
    delete them.
    """
    right = (body.get("right") or "").strip()
    variants = [str(v).strip() for v in (body.get("variants") or []) if str(v).strip()]
    if not right or not variants:
        return JSONResponse({"error": "the right name and at least one variant are required"}, 400)
    if "<-" in right or any("<-" in v for v in variants):
        return JSONResponse({"error": "<- separates the two columns and cannot be in a name"}, 400)
    if any("," in v for v in variants):
        return JSONResponse({"error": "commas separate the variants and cannot be inside one"}, 400)
    # A variant equal to the right name corrects nothing and would loop.
    if any(v.lower() == right.lower() for v in variants):
        return JSONResponse({"error": "a variant equal to the right name corrects nothing"}, 400)

    f = T.glossary_file()
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    with f.open("a", encoding="utf-8") as out:
        if not text:
            out.write("# Right <- how it gets written wrong, another variant\n")
        elif not text.endswith("\n"):
            out.write("\n")
        out.write(f"{right} <- {', '.join(variants)}\n")
    return {"added": True}


# --- the page and the rest ----------------------------------------------------

@app.get("/", include_in_schema=False)
def page():
    # Checked with the server at every load: after an update the window,
    # which keeps its cache between starts, showed the page from before.
    return FileResponse(ROOT / "app" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/fonts/{name}", include_in_schema=False)
def font(name: str):
    """Fonts live in the repo, not on Google Fonts.

    A page that calls an outside server when it opens contradicts the one
    promise of this program (nothing leaves this machine) and would not open
    without a network. Public Sans, SIL Open Font License 1.1, 26 KB.
    """
    f = ROOT / "app" / "fonts" / pathlib.Path(name).name
    if f.suffix != ".woff2" or not f.is_file():
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(f, media_type="font/woff2",
                        headers={"Cache-Control": "public, max-age=604800"})


@app.get("/health", response_class=PlainTextResponse)
def health():
    return "ok" if engine_state["ready"] or engine_state["off"] else "loading"


@app.post("/api/shutdown")
def api_shutdown():
    """Closes the server, and the model with it: the VRAM is free again.

    There is no "unload the model but stay up": it lives inside this process,
    and staying up without it would mean paying the twenty seconds of loading
    again at the next file. All or nothing.

    Refuses while a job is running: stopping half-way would throw away minutes
    of transcription already done.
    """
    if any(j["state"] == "running" for j in jobs.values()) or line_up.qsize():
        return JSONResponse({"error": "a transcription is running: wait for it to finish"}, 409)
    if capture:
        return JSONResponse({"error": "a call is being recorded: stop it first"}, 409)

    def shortly():
        time.sleep(0.4)          # time to answer the page
        if quit_app is not None:
            quit_app()
            return
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=shortly, daemon=True).start()
    return {"stopped": True}


# --- the desktop window ------------------------------------------------------------
#
# desktop.py runs this server inside a window with an icon by the clock. A
# second double-click on the shortcut finds the server already up and asks it,
# here, to bring that window back instead of starting another copy.

show_window = None        # set by desktop.py; None when the server runs on its own
quit_app = None           # the same: the power button then closes the program, icon and all


@app.post("/api/window/show")
def api_window_show():
    if show_window is None:
        return JSONResponse({"error": "no window: this server runs without one"}, 404)
    show_window()
    return {"shown": True}


# --- starting up --------------------------------------------------------------------

def options(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Sottovoce local server.")
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--data", type=pathlib.Path, default=ROOT / "transcripts",
                    help="where transcriptions are kept (default: ./transcripts)")
    ap.add_argument("--glossary", type=pathlib.Path, default=None,
                    help="the name glossary (default: ./glossary.txt)")
    ap.add_argument("--no-model", action="store_true",
                    help="browse transcripts without loading Whisper (no GPU needed)")
    ap.add_argument("--no-llm", action="store_true",
                    help="no built-in model for summaries and emails (a running LM Studio or "
                         "Ollama is still used)")
    ap.add_argument("--lan", action="store_true",
                    help="reachable from other devices on your network, e.g. your phone, "
                         "with a PIN asked once per device")
    ap.add_argument("--pin", default=None,
                    help="the PIN for --lan (default: one made up the first time, then kept)")
    return ap.parse_args(argv)


def configure(args) -> str:
    """Everything before serving: the data, the model, who may connect.
    Returns the address to listen on."""
    global allowed_hosts
    # Browsing only means no GPU work at all: the built-in LLM stays off too.
    S.builtin_allowed = not (args.no_model or args.no_llm)
    start(args.data, args.glossary, model=not args.no_model)
    print(f"\n  Sottovoce {VERSION} on  http://127.0.0.1:{args.port}")
    print(f"  model: {T.MODEL}")
    print(f"  transcripts in: {DATA}")
    print(f"  API reference: http://127.0.0.1:{args.port}/docs")
    print("  browsing only: Whisper is not loaded (--no-model)\n" if args.no_model else
          "  Whisper loads with the first transcription (2.9 GB of the GPU) and leaves\n"
          "  ten minutes after the last one\n")
    # 127.0.0.1 by default: the server hands out client recordings and
    # transcripts to whoever reaches it. --lan opens it to the local network
    # on purpose, for reading and uploading from a phone, behind a PIN (see
    # pin_guard), and says so every time it starts.
    host = "127.0.0.1"
    allowed_hosts = hosts_for(args.port)
    if args.lan:
        import socket
        host = "0.0.0.0"
        # The address of the interface that leads to the network. A UDP
        # "connect" only picks the route: no packet is sent. Listing every
        # address instead also shows virtual adapters (WSL, Hyper-V) that a
        # phone can't reach.
        ips = []
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))
                ips = [s.getsockname()[0]]
        except OSError:
            pass
        # Every address of this computer is a name it may be reached by on
        # the network (and its own name), never a name someone else chose.
        own = set(ips)
        try:
            own |= set(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
        allowed_hosts = hosts_for(args.port, own | {socket.gethostname()})
        pin = pin_setup(args.pin)
        print("  ON YOUR NETWORK: other devices on this Wi-Fi can open it, with the PIN.")
        for ip in ips or ["<this computer's IP>"]:
            print(f"  from your phone:  http://{ip}:{args.port}")
        print(f"  PIN: {pin}      (asked once per device; this computer is never asked)")
        print("  Plain http: fine at home or in the office, not on public Wi-Fi.")
        print("  Windows may ask whether Python can use private networks: say yes.\n")
    return host


if __name__ == "__main__":
    import uvicorn

    args = options()
    uvicorn.run(app, host=configure(args), port=args.port, log_level="warning")
