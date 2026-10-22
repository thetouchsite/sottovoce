"""Sottovoce: drop a recording on the page, or record a call from it, and get the text back.

    python server.py                         then  http://127.0.0.1:8200
    python server.py --port 8300 --data D:\\calls --glossary D:\\calls\\names.txt
    python server.py --no-model              browse transcripts, no GPU needed

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

The original is kept: if you lose it from your phone or your Downloads, the
copy is here next to its transcript.

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
import importlib.util
import json
import pathlib
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import date

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

import summary as S
import transcribe as T

VERSION = "1.2.0"
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
jobs: dict[str, dict] = {}
line_up: queue.Queue = queue.Queue()


def clean(name: str) -> str:
    """A file name Windows accepts, without losing readability."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return name[:80] or "untitled"


def folder(name: str) -> pathlib.Path:
    """A transcription folder by name, never outside the data folder."""
    return DATA / pathlib.Path(name).name


def warm_up():
    """Loads the model at startup, in a thread, so the page opens at once."""
    try:
        T.engine()
        engine_state["ready"] = True
    except Exception as e:
        engine_state["error"] = f"{type(e).__name__}: {e}"


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


def write_info(d: pathlib.Path, info: dict):
    (d / "info.json").write_text(json.dumps(info, indent=1, ensure_ascii=False),
                                 encoding="utf-8")


def read_info(d: pathlib.Path) -> dict:
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

def process(job_id: str, upload: pathlib.Path, name: str, language: str | None,
            two_tracks: bool = False, precise: bool = False, voices: bool = False) -> None:
    job = jobs[job_id]
    try:
        stem = clean(pathlib.Path(name).stem)
        d = DATA / f"{date.today():%Y-%m-%d}_{stem}"
        n = 2
        while d.exists():                      # two calls with the same name
            d = DATA / f"{date.today():%Y-%m-%d}_{stem} ({n})"
            n += 1
        d.mkdir(parents=True)
        original = d / f"{stem}{pathlib.Path(name).suffix}"
        shutil.move(str(upload), original)
        job["folder"] = d.name

        def progress(stage, audio_seconds):
            job["stage"] = stage
            if audio_seconds:
                job["duration"] = audio_seconds
                # An honest estimate: the speed measured end to end on a real
                # call. Not real progress (the pipeline does not expose it),
                # but it is off by a few seconds over four minutes.
                job["expected"] = round(audio_seconds / (T.SPEED_PRECISE if precise else T.SPEED))

        t0 = time.time()
        r = T.run(original, language, progress, two_tracks=two_tracks, precise=precise,
                  voices=voices)
        taken = round(time.time() - t0)
        segments, seconds = r["segments"], r["seconds"]

        (d / f"{stem}.txt").write_text(T.as_txt(segments), encoding="utf-8")
        (d / f"{stem}.md").write_text(T.as_md(segments, stem, seconds), encoding="utf-8")
        write_words(d, segments)
        info = {
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
        upload.unlink(missing_ok=True)


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
    if model:
        threading.Thread(target=warm_up, daemon=True).start()
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


def enqueue(path: pathlib.Path, name: str, language: str | None, two_tracks=False,
            precise=False, voices=False) -> str:
    job_id = uuid.uuid4().hex[:8]
    ahead = line_up.qsize()
    jobs[job_id] = {"state": "running", "name": name,
                    "stage": f"queued, {ahead} ahead" if ahead else "queued",
                    "started": time.time()}
    line_up.put((job_id, path, name, language, two_tracks, precise, voices))
    return job_id


def voices_installed() -> bool:
    """Whether telling voices apart can run: its packages are optional."""
    return all(importlib.util.find_spec(m) is not None for m in ("sherpa_onnx", "onnxruntime", "scipy"))


@app.get("/api/status")
def api_status():
    import voices as V
    return {**engine_state, "model": T.MODEL, "queued": line_up.qsize(), "version": VERSION,
            # The page says "downloads 32 MB the first time" until it is on disk.
            "voices": voices_installed(), "voices_ready": V.ready()}


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...), language: str = Form("auto"),
                         two_tracks: bool = Form(False), precise: bool = Form(False),
                         voices: bool = Form(False)):
    """Queues a recording. Several files: one request each, they run one after the other."""
    refused = refuse_if_off()
    if refused:
        return refused
    dest = INCOMING / f"{uuid.uuid4().hex[:8]}{pathlib.Path(file.filename).suffix or '.bin'}"
    dest.write_bytes(await file.read())
    return {"job": enqueue(dest, file.filename, language_of(language), two_tracks, precise,
                           voices and voices_installed())}


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
    return RECORDINGS / f"{rid}.webm" if RID.match(rid) else None


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
    f = recording(rid)
    if f is None or not f.exists():
        return JSONResponse({"error": "unknown recording"}, 404)
    if f.stat().st_size == 0:
        return JSONResponse({"error": "the recording is empty"}, 400)
    refused = refuse_if_off()
    if refused:
        return refused
    meta_f = RECORDINGS / f"{rid}.json"
    meta = json.loads(meta_f.read_text(encoding="utf-8")) if meta_f.exists() else {}
    body = await request.json() if await request.body() else {}
    name = clean(body.get("name") or meta.get("name") or "Call") + ".webm"
    language = language_of(body.get("language") or meta.get("language"))
    dest = INCOMING / f"{rid}.webm"
    shutil.move(str(f), dest)
    meta_f.unlink(missing_ok=True)
    return {"job": enqueue(dest, name, language, two_tracks=True,
                           precise=bool(body.get("precise")),
                           voices=bool(body.get("voices")) and voices_installed())}


@app.get("/api/recordings")
def api_recordings():
    """Recordings that were never finished: the page offers to save them."""
    out = []
    for meta_f in sorted(RECORDINGS.glob("*.json")) if RECORDINGS.exists() else []:
        f = meta_f.with_suffix(".webm")
        if not f.exists():
            continue
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


# --- history ----------------------------------------------------------------------

@app.get("/api/history")
def api_history():
    out = []
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
        out.append({"folder": d.name, **data})
    # Newest first by when it was transcribed. Folder names only carry the
    # day: two calls of the same day would otherwise sort by their titles.
    out.sort(key=lambda e: (e.get("transcribed_at") or "", e["folder"]), reverse=True)
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
    if txt is None:
        return JSONResponse({"error": "transcript missing"}, 404)
    audio = audio_in(d)
    summary_md = d / "summary.md"
    names = data.get("speaker_names") or {}
    return {"folder": d.name, "stem": txt.stem, "audio": audio,
            "name": data.get("original", txt.stem),
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
            "names_corrected": data.get("names_corrected") or 0,
            # For the strip: where a phrase was dropped and where a line was
            # corrected. These are the places where the text was touched, and
            # the strip shows them on the real duration.
            "phantoms": data.get("phantoms_dropped") or [],
            "corrections": corrections_of(d),
            "names": names_in(txt),
            "speech": speech_of(d, data, audio)}


@app.get("/api/history/{name}/download.{fmt}")
def api_download(name: str, fmt: str):
    """The transcript as .txt, .md, .srt, .vtt or .json.

    txt and md are the files in the folder. The others are written on the fly
    from the .txt and the word timings, so they always match the corrections.
    So is the .txt when the voices have names: the file keeps "[Voice 2]",
    the download says who Voice 2 is.
    """
    d = folder(name)
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
    s = S.who_answers()
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
    return FileResponse(ROOT / "app" / "index.html")


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

    def shortly():
        time.sleep(0.4)          # time to answer the page
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=shortly, daemon=True).start()
    return {"stopped": True}


if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser(description="Sottovoce local server.")
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--data", type=pathlib.Path, default=ROOT / "transcripts",
                    help="where transcriptions are kept (default: ./transcripts)")
    ap.add_argument("--glossary", type=pathlib.Path, default=None,
                    help="the name glossary (default: ./glossary.txt)")
    ap.add_argument("--no-model", action="store_true",
                    help="browse transcripts without loading Whisper (no GPU needed)")
    args = ap.parse_args()

    start(args.data, args.glossary, model=not args.no_model)
    print(f"\n  Sottovoce {VERSION} on  http://127.0.0.1:{args.port}")
    print(f"  model: {T.MODEL}")
    print(f"  transcripts in: {DATA}")
    print(f"  API reference: http://127.0.0.1:{args.port}/docs")
    print("  browsing only: Whisper is not loaded (--no-model)\n" if args.no_model else
          "  (the first start loads 2.88 GB into VRAM: about twenty seconds)\n")
    # 127.0.0.1 only: the server hands out client recordings and transcripts
    # to whoever asks, and must not be reachable from the rest of the network.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
