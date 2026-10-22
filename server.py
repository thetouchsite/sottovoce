"""Sottovoce: drop a recording on the page, get the text back.

    python server.py                         then  http://127.0.0.1:8200
    python server.py --port 8300 --data D:\\calls --glossary D:\\calls\\names.txt

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
        Client call.md       to read
        Client call.txt      with timestamps: the source everything is rebuilt from
        info.json            duration, timings, model, language, what was dropped
        corrections.jsonl    every line corrected, with before and after
        summary.md           if you asked for one

The original is kept: if you lose it from your phone or your Downloads, the
copy is here next to its transcript. Folder names start with the date so they
sort themselves.

ONE AT A TIME. Jobs queue up instead of running together: two transcriptions in
parallel share the same pipeline and slow each other down (measured: 233 s
instead of 190 when two were running).

Everything stays on this machine: the uploaded file does not leave, the model
runs locally, there are no network calls during transcription. The page itself
loads nothing from the internet, not even its fonts.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import queue
import re
import shutil
import threading
import time
import uuid
from datetime import date

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

import summary as S
import transcribe as T

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "transcripts"            # set again by start() from --data
INCOMING = DATA / "_incoming"
AUDIO = (".mp4", ".m4a", ".mp3", ".wav", ".opus", ".ogg", ".3gp", ".aac",
         ".webm", ".flac", ".mov", ".mkv")

app = FastAPI(title="Sottovoce")

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
    """
    if INCOMING.exists():
        n = len(list(INCOMING.glob("*")))
        shutil.rmtree(INCOMING, ignore_errors=True)
        if n:
            print(f"  removed {n} uploads left over from a previous run")
    INCOMING.mkdir(parents=True, exist_ok=True)


def write_info(d: pathlib.Path, info: dict):
    (d / "info.json").write_text(json.dumps(info, indent=1, ensure_ascii=False),
                                 encoding="utf-8")


def process(job_id: str, upload: pathlib.Path, name: str, language: str | None) -> None:
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
                job["expected"] = round(audio_seconds / T.SPEED)

        t0 = time.time()
        segments, seconds, speech_s, corrected, phantoms, speech, used = T.run(
            original, language, progress)
        taken = round(time.time() - t0)

        (d / f"{stem}.txt").write_text(T.as_txt(segments), encoding="utf-8")
        (d / f"{stem}.md").write_text(T.as_md(segments, stem, seconds), encoding="utf-8")
        write_info(d, {
            "original": original.name,
            "transcribed_at": time.strftime("%Y-%m-%d %H:%M"),
            "model": T.MODEL,
            "language": used,
            "language_requested": language or "auto",
            "duration_s": round(seconds, 1),
            "seconds_taken": taken,
            "silence_s": round(seconds - speech_s),
            # A number, not the name -> count dictionary: the page prints it
            # and /api/reapply adds to it.
            "names_corrected": sum(corrected.values()),
            "names_by_name": corrected,
            "phantoms_dropped": [{"minute": T.mmss(s["start"]), "text": s["text"]}
                                 for s in phantoms],
            "words": sum(len(s["text"].split()) for s in segments),
            "segments": len(segments),
            "speech": [[round(a, 2), round(b, 2)] for a, b in speech],
        })
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
    global DATA, INCOMING
    if glossary is not None:
        T.GLOSSARY = glossary.resolve()
    DATA = data.resolve()
    INCOMING = DATA / "_incoming"
    DATA.mkdir(parents=True, exist_ok=True)
    sweep()
    if model:
        threading.Thread(target=warm_up, daemon=True).start()
    else:
        engine_state["off"] = True
    threading.Thread(target=counter, daemon=True).start()


# --- the job ------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    return {**engine_state, "model": T.MODEL, "queued": line_up.qsize()}


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...), language: str = Form("auto")):
    if engine_state["off"]:
        return JSONResponse({"error": "transcription is off: the server was started with --no-model"}, 503)
    if not engine_state["ready"]:
        return JSONResponse(
            {"error": engine_state["error"] or "the model is still loading"}, 503)
    lang = None if language in ("", "auto") else re.sub(r"[^a-z]", "", language.lower())[:3]
    job_id = uuid.uuid4().hex[:8]
    dest = INCOMING / f"{job_id}{pathlib.Path(file.filename).suffix or '.bin'}"
    dest.write_bytes(await file.read())
    ahead = line_up.qsize()
    jobs[job_id] = {"state": "running", "name": file.filename,
                    "stage": f"queued, {ahead} ahead" if ahead else "queued",
                    "started": time.time()}
    line_up.put((job_id, dest, file.filename, lang))
    return {"job": job_id}


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        return JSONResponse({"error": "unknown job"}, 404)
    return {**j, "elapsed": round(time.time() - j["started"])}


# --- history ------------------------------------------------------------------
# The folders on disk ARE the history: the server keeps no list of its own, it
# reads them again. So it survives a restart, and if the server dies half-way
# the finished transcriptions are still there.

def read_txt(f: pathlib.Path):
    """From the .txt to segments. The .txt is the source: no copies to keep in sync.

    The end of a segment is not written: it is taken from the start of the
    next one, which is precise enough to split paragraphs.
    """
    segments = []
    for line in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\[(\d+):(\d+)\]\s*(.+)$", line)
        if m:
            segments.append({"start": int(m[1]) * 60 + int(m[2]), "end": None,
                             "text": m[3].strip()})
    for a, b in zip(segments, segments[1:]):
        a["end"] = b["start"]
    if segments:
        segments[-1]["end"] = segments[-1]["start"]
    return segments


def audio_in(d: pathlib.Path) -> str | None:
    return next((f.name for f in d.iterdir() if f.suffix.lower() in AUDIO), None)


@app.get("/api/history")
def api_history():
    out = []
    for d in sorted(DATA.iterdir(), reverse=True):
        info = d / "info.json"
        if not d.is_dir() or not info.exists():
            continue
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # Words are counted from the .txt, not taken from info.json: that number
        # was written at transcription time and every correction makes it old
        # (a two-word name corrected into a one-word one). The same fact shown
        # in two places on the page must come from the same source.
        txt = next(d.glob("*.txt"), None)
        if txt is not None:
            data["words"] = sum(len(s["text"].split()) for s in read_txt(txt))
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
            m = re.match(r"^\[(\d+):(\d+)\]\s*(.*)$", line)
            if not m or not rx.search(m[3]):
                continue
            text = m[3]
            k = rx.search(text).start()
            a, b = max(0, k - around), min(len(text), k + len(q) + around)
            hits.append({"minute": f"{m[1]}:{m[2]}",
                         "seconds": int(m[1]) * 60 + int(m[2]),
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
    info = d / "info.json"
    if not d.is_dir() or not info.exists():
        return JSONResponse({"error": "not found"}, 404)
    data = json.loads(info.read_text(encoding="utf-8"))
    txt = next(d.glob("*.txt"), None)
    if txt is None:
        return JSONResponse({"error": "transcript missing"}, 404)
    segments = read_txt(txt)
    audio = audio_in(d)
    summary_md = d / "summary.md"
    return {"folder": d.name, "stem": txt.stem, "audio": audio,
            "name": data.get("original", txt.stem),
            "language": data.get("language"),
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
    d = folder(name)
    f = next(d.glob(f"*.{fmt}"), None) if fmt in ("txt", "md") and d.is_dir() else None
    if f is None or not f.exists():
        return JSONResponse({"error": "not found"}, 404)
    return FileResponse(f, filename=f.name, media_type="text/plain; charset=utf-8")


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


def rebuild_md(d: pathlib.Path, txt: pathlib.Path):
    """The .md is rebuilt from the .txt: one source, no copy to keep in line."""
    info = json.loads((d / "info.json").read_text(encoding="utf-8"))
    d.joinpath(f"{txt.stem}.md").write_text(
        T.as_md(read_txt(txt), txt.stem, info.get("duration_s") or 0), encoding="utf-8")


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
    """
    d = folder(name)
    txt = next(d.glob("*.txt"), None) if d.is_dir() else None
    if txt is None:
        return JSONResponse({"error": "transcript not found"}, 404)

    index, new = body.get("index"), (body.get("text") or "").strip()
    if index is None or not new:
        return JSONResponse({"error": "index and text are required"}, 400)

    lines = txt.read_text(encoding="utf-8").splitlines()
    if not 0 <= index < len(lines):
        return JSONResponse({"error": "no such line"}, 400)

    m = re.match(r"^(\[\d+:\d+\]\s*)(.*)$", lines[index])
    if not m:
        return JSONResponse({"error": "unreadable line"}, 400)
    before = m[2]
    if before.strip() == new:
        return {"unchanged": True}

    lines[index] = m[1] + new
    txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (d / "corrections.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"),
                            "minute": m[1].strip("[] "), "line": index,
                            "before": before, "after": new, "source": "manual"},
                           ensure_ascii=False) + "\n")
    rebuild_md(d, txt)
    return {"saved": True}


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

    txt = next(d.glob("*.txt"), None)
    if txt is None:
        return JSONResponse({"error": "transcript missing"}, 404)

    # The text goes without timestamps: a timestamp costs a token per line,
    # which over 550 lines is a tenth of the prompt spent on nothing, since
    # the summary does not need them.
    text = "\n".join(s["text"] for s in read_txt(txt))
    t0 = time.time()
    r = S.summarize(text)
    if "error" in r:
        return JSONResponse(r, 503)

    done.write_text(r["text"], encoding="utf-8")
    secs = round(time.time() - t0, 1)
    info = d / "info.json"
    if info.exists():
        data = json.loads(info.read_text(encoding="utf-8"))
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
    txt = next(d.glob("*.txt"), None) if d.is_dir() else None
    if txt is None:
        return JSONResponse({"error": "not found"}, 404)

    lines = txt.read_text(encoding="utf-8").splitlines()
    rules = T.glossary()
    at = time.strftime("%Y-%m-%d %H:%M")
    changes, new_lines, names = [], [], {}
    for i, line in enumerate(lines):
        m = re.match(r"^(\[\d+:\d+\]\s*)(.*)$", line)
        if not m:
            new_lines.append(line)
            continue
        piece = [{"text": m[2]}]
        done = T.apply_glossary(piece, rules)
        if done and piece[0]["text"] != m[2]:
            changes.append({"at": at, "minute": m[1].strip("[] "), "line": i,
                            "before": m[2], "after": piece[0]["text"],
                            "source": "glossary"})
            for right, n in done.items():
                names[right] = names.get(right, 0) + n
        new_lines.append(m[1] + piece[0]["text"])

    if not changes:
        return {"corrected": 0, "names": {}}

    txt.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    with (d / "corrections.jsonl").open("a", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    rebuild_md(d, txt)

    # The count has to be rewritten, or the page keeps saying no names were
    # corrected right after twenty-seven were.
    info = json.loads((d / "info.json").read_text(encoding="utf-8"))
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

@app.get("/")
def page():
    return FileResponse(ROOT / "app" / "index.html")


@app.get("/fonts/{name}")
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
    print(f"\n  Sottovoce on  http://127.0.0.1:{args.port}")
    print(f"  model: {T.MODEL}")
    print(f"  transcripts in: {DATA}")
    print("  browsing only: Whisper is not loaded (--no-model)\n" if args.no_model else
          "  (the first start loads 2.88 GB into VRAM: about twenty seconds)\n")
    # 127.0.0.1 only: the server hands out client recordings and transcripts
    # to whoever asks, and must not be reachable from the rest of the network.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
