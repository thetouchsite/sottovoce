"""The summary of a call, and the follow-up email, written by an LLM running on this machine.

TWO WAYS, THE FIRST THAT IS THERE. If a local LLM server is running (LM
Studio, Ollama, `llama-server`), it is spoken to over the OpenAI protocol:
whoever switched one on chose their model. If none is, a small model built in
does the job, the way Whisper does: Qwen3 4B Instruct (Apache-2.0, no
account), downloaded from Hugging Face the first time (8 GB), loaded on the
GPU when asked, and unloaded after ten minutes unused. Nothing to install
for whoever clones the repo.

OR THE ONE YOU PICK. Whoever already has LM Studio or Ollama, with models in
it, can pick one of those models in the page, once. Then the program need not
be opened by hand: Sottovoce starts its server when a summary is asked, the
program loads the model on the first request and lets it go when it is no
longer used. See "the programs already on this computer" below.

The reason it is not kept loaded is VRAM. Whisper takes about 6 GB, the
built-in model another 8: keeping both all the time, for something asked for
once at the end of a call, is paying rent on a room you open once a day.

MEASURED on the example calls (RTX 5090 laptop, 24 GB): the built-in model
wrote the follow-up of a one-minute Italian call in 26 s and the summary of
an 11-minute English one in 13 s, in 7.8 GB; Gemma 4 E4B in LM Studio took
5 to 17 s. Gemma 4 E4B in this form weighs 16 GB: too much next to Whisper.

MIND THE BACKEND, NOT THE MODEL. On 22 October 2026, a real call, 3,760
prompt tokens, same card:

    llama.cpp Vulkan, 9B model     6.8 tok/s prompt  ->  about 9 minutes
    llama.cpp CUDA,   4B model     whole summary     ->  13.5 to 16 seconds

Not the same model, so not a clean comparison; but a 9B model is about twice
as slow as a 4B one, not thirty times. The rest is the build: the RTX 5090 is
sm_120 and the Vulkan build does not use it properly. It does not fail, it
crawls silently, the same trap as installing the default PyTorch from PyPI.
If summaries take minutes, suspect the build.

    python summary.py                    who is answering
    python summary.py call.md            summarize a file
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

# In order of likelihood, not preference. The first that answers wins: whoever
# switched one on chose that one.
PORTS = [(1234, "LM Studio"), (11434, "Ollama"), (8080, "llama-server"),
         (8081, "llama-server"), (1235, "llama-server")]

PROBE_TIMEOUT = 0.6     # a local server that is on answers in milliseconds
JOB_TIMEOUT = 600       # a long summary on a slow machine
MAX_TOKENS = 2500       # reasoning models spend half of it thinking

INSTRUCTIONS = (
    "You summarize business calls. "
    "Write in the same language as the transcript. "
    "Do not invent anything: if something was not said, do not write it. "
    "The transcript is automatic and contains errors: where a name looks "
    "garbled, leave it as it is instead of guessing."
)

REQUEST = (
    "This is the automatic transcript of a business call.\n\n"
    "Write, in the language of the transcript and in this order:\n"
    "1. three lines of synthesis, no bullet points\n"
    "2. a '##' heading meaning 'Decided': what was concluded\n"
    "3. a '##' heading meaning 'To do': the actions, with who does them if it was said\n"
    "4. a '##' heading meaning 'Open': what is still unresolved\n\n"
    "If a section has no content, say that nothing came up instead of "
    "filling it.\n\n"
    "--- TRANSCRIPT ---\n{text}\n--- END ---"
)


FOLLOWUP_INSTRUCTIONS = (
    "You write the follow-up email after a business call, on behalf of the "
    "person who recorded it. Write in the same language as the transcript. "
    "Do not invent anything: no dates, prices, names or commitments that were "
    "not said. Where a detail would be needed but is missing, write a "
    "placeholder in square brackets, like [date]. The transcript is automatic "
    "and contains errors: where a name looks garbled, leave it as it is."
)

FOLLOWUP_REQUEST = (
    "This is the automatic transcript of a business call. {who}\n\n"
    "Write the follow-up email that {sender} sends to {recipient} after the "
    "call, in the language of the transcript:\n"
    "- first line: the subject, introduced by the word for 'Subject' in that "
    "language (for example 'Oggetto:' in Italian)\n"
    "- a greeting and one line of thanks for the call\n"
    "- what was decided, as a short list\n"
    "- the next steps: who does what and by when, only as it was said\n"
    "- what is still open, if anything\n"
    "- a short closing, signed {signature}\n"
    "Keep it short, and in the tone of the call: formal if they spoke "
    "formally, informal if not. Plain text: no markdown, no headings.\n\n"
    "--- TRANSCRIPT ---\n{text}\n--- END ---"
)


# --- the model built in ---------------------------------------------------------

BUILTIN = os.environ.get("SOTTOVOCE_LLM", "Qwen/Qwen3-4B-Instruct-2507")
BUILTIN_GB = 8          # to download once, and to find free on the GPU
IDLE = 600              # seconds unused before it leaves the GPU
builtin_allowed = True  # the server turns it off with --no-model and --no-llm
_builtin = {"model": None, "tok": None, "last": 0.0}
_builtin_lock = threading.Lock()


def builtin() -> dict | None:
    """The built-in model, if it can run here: a CUDA GPU, and allowed."""
    if not builtin_allowed:
        return None
    try:
        import torch
        if not torch.cuda.is_available():
            return None
    except ImportError:
        return None
    return {"program": "Sottovoce", "model": BUILTIN.split("/")[-1], "builtin": True,
            "downloaded": _downloaded()}


def _downloaded() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(BUILTIN, "config.json"), str)
    except Exception:
        return False


def _unload_when_idle():
    while True:
        time.sleep(30)
        with _builtin_lock:
            if _builtin["model"] is not None and time.time() - _builtin["last"] > IDLE:
                import gc
                import torch
                _builtin.update(model=None, tok=None)
                gc.collect()
                torch.cuda.empty_cache()
                return


def _builtin_ask(instructions: str, request: str) -> dict:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    with _builtin_lock:
        if _builtin["model"] is None:
            free, _ = torch.cuda.mem_get_info()
            if free < (BUILTIN_GB + 1) * 2 ** 30:
                return {"error": f"the built-in model needs about {BUILTIN_GB + 1} GB free on the "
                                 f"GPU and {free / 2 ** 30:.1f} GB are: run LM Studio or Ollama "
                                 "with a smaller model instead"}
            tok = AutoTokenizer.from_pretrained(BUILTIN)
            model = AutoModelForCausalLM.from_pretrained(BUILTIN, dtype=torch.bfloat16,
                                                         device_map="cuda")
            _builtin.update(model=model, tok=tok)
            threading.Thread(target=_unload_when_idle, daemon=True).start()
        model, tok = _builtin["model"], _builtin["tok"]
        ids = tok.apply_chat_template(
            [{"role": "system", "content": instructions}, {"role": "user", "content": request}],
            add_generation_prompt=True, return_tensors="pt", return_dict=True).to(model.device)
        out = model.generate(**ids, max_new_tokens=1200, do_sample=False)
        text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        _builtin["last"] = time.time()
    if not text:
        return {"error": "the built-in model answered with nothing"}
    return {"text": text, "model": BUILTIN.split("/")[-1], "program": "Sottovoce",
            "tokens_read": int(ids["input_ids"].shape[1]),
            "tokens_written": int(out.shape[1] - ids["input_ids"].shape[1])}


# --- the programs already on this computer -------------------------------------------
#
# LM Studio: its command line, `lms`, lists the models (`lms ls --json`) and
# starts the server without the window (`lms server start`). The model is
# loaded by the first request that names it (LM Studio's just-in-time
# loading, on by default) and unloaded IDLE seconds after the last one (the
# request's "ttl"). If just-in-time loading was turned off, `lms load` does it.
#
# Ollama: the models are read from its folder, so it need not be running to
# say what it has; `ollama serve` starts it, and it loads a model when asked
# and lets it go after five minutes, by itself.
#
# What Sottovoce started, it stops when it quits (stop_started): the model it
# loaded, the server it switched on, and LM Studio's background service if it
# was the one to wake it. `lms daemon status`, asked before anything else,
# says whether the service was up: it is the one command that doesn't wake it.

# What the user picked in the page. program None: the first server that
# answers, else the built-in model, as before there was a choice.
choice = {"program": None, "model": None}

LMSTUDIO_PORT = 1234     # its default; `lms server status` says if it was changed
OLLAMA_PORT = 11434
START_TIMEOUT = 60       # LM Studio's service, woken from cold, takes a few seconds
_started: dict[str, subprocess.Popen | None] = {}       # Ollama's `serve`, if started here
_lmstudio = {"service_was_up": None, "server": False, "models": set()}


def _hidden() -> dict:
    """No console window flashing up for the programs started here."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def lms() -> str | None:
    """LM Studio's command line, where LM Studio puts it."""
    exe = "lms.exe" if os.name == "nt" else "lms"
    home = pathlib.Path.home() / ".lmstudio" / "bin" / exe
    return shutil.which("lms") or (str(home) if home.exists() else None)


def ollama() -> str | None:
    """Ollama, on the PATH or where its Windows setup puts it."""
    if shutil.which("ollama"):
        return shutil.which("ollama")
    setup = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(setup) if os.name == "nt" and setup.exists() else None


def _cli(args: list[str], timeout: float = 60) -> str:
    if args and args[0] == lms() and _lmstudio["service_was_up"] is None:
        _lmstudio["service_was_up"] = False             # if asking fails, it wasn't up
        status = subprocess.run([args[0], "daemon", "status", "--json"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30, **_hidden()).stdout
        _lmstudio["service_was_up"] = (_json_in(status) or {}).get("status") == "running"
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, **_hidden())
    return r.stdout


def _lmstudio_loaded() -> set[str]:
    try:
        return {m.get("identifier") for m in _json_in(_cli([lms(), "ps", "--json"], 30)) or []
                if isinstance(m, dict)}
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()


def _json_in(text: str):
    """The JSON in what `lms` prints: it may say "Waking up LM Studio service..." first."""
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    return json.loads(text[min(starts):]) if starts else None


def lmstudio_models() -> list[dict]:
    """LM Studio's language models: [{"id", "name", "gb"}]. Embedding models
    are left out: they cannot write."""
    cli = lms()
    if not cli:
        return []
    try:
        data = _json_in(_cli([cli, "ls", "--json"])) or []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [{"id": m["modelKey"], "name": m.get("displayName") or m["modelKey"],
             "gb": round((m.get("sizeBytes") or 0) / 1e9, 1)}
            for m in data if isinstance(m, dict) and m.get("type") == "llm" and m.get("modelKey")]


def lmstudio_port() -> int:
    global LMSTUDIO_PORT
    cli = lms()
    if cli:
        try:
            LMSTUDIO_PORT = int((_json_in(_cli([cli, "server", "status", "--json"], 30)) or {})
                                .get("port") or LMSTUDIO_PORT)
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            pass
    return LMSTUDIO_PORT


def ollama_folder() -> pathlib.Path:
    return pathlib.Path(os.environ.get("OLLAMA_MODELS") or pathlib.Path.home() / ".ollama" / "models")


def ollama_models() -> list[dict]:
    """Ollama's models from their manifests on disk:
    manifests/<registry>/<namespace>/<model>/<tag>, "library" being its own."""
    root = ollama_folder() / "manifests"
    out = []
    for f in sorted(root.glob("*/*/*/*")) if root.is_dir() else []:
        if not f.is_file():
            continue
        registry, space, name, tag = f.relative_to(root).parts
        full = name if space == "library" else f"{space}/{name}"
        if registry != "registry.ollama.ai":
            full = f"{registry}/{full}"
        if "embed" in full.lower():
            continue
        try:
            size = sum(layer.get("size", 0) for layer in
                       json.loads(f.read_text(encoding="utf-8")).get("layers", []))
        except (OSError, ValueError, AttributeError):
            size = 0
        out.append({"id": f"{full}:{tag}", "name": f"{full}:{tag}", "gb": round(size / 1e9, 1)})
    return out


def _answers(port: int) -> bool:
    return _models_at(port) is not None


def _models_at(port: int) -> list[str] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=PROBE_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None
    return [m.get("id") for m in data.get("data", []) if m.get("id")]


def programs() -> list[dict]:
    """What can write on this computer, for the page's choice: the built-in
    model, and LM Studio and Ollama with their models if they are installed."""
    b = builtin()
    out = [{"program": "Sottovoce", "builtin": True, "usable": b is not None,
            "models": [{"id": BUILTIN.split("/")[-1], "name": BUILTIN.split("/")[-1], "gb": BUILTIN_GB}],
            "downloaded": _downloaded()}]
    if lms():
        out.append({"program": "LM Studio", "models": lmstudio_models(),
                    "running": _answers(lmstudio_port())})
    if ollama() or ollama_models():
        out.append({"program": "Ollama", "models": ollama_models(), "installed": bool(ollama()),
                    "running": _answers(OLLAMA_PORT)})
    return out


def start(program: str) -> int:
    """The program's server, switched on if it is off. Returns its port;
    raises RuntimeError with the reason if it cannot."""
    if program == "LM Studio":
        cli = lms()
        if not cli:
            raise RuntimeError("LM Studio is not installed on this computer")
        port = LMSTUDIO_PORT if _answers(LMSTUDIO_PORT) else lmstudio_port()
        if not _answers(port):
            _cli([cli, "server", "start"], START_TIMEOUT)
            _lmstudio["server"] = True
    elif program == "Ollama":
        exe = ollama()
        port = OLLAMA_PORT
        if not _answers(port):
            if not exe:
                raise RuntimeError("Ollama is not installed on this computer")
            _started["Ollama"] = subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL,
                                                  stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL, **_hidden())
    else:
        raise RuntimeError(f"unknown program {program!r}")
    deadline = time.time() + START_TIMEOUT
    while not _answers(port):
        if time.time() > deadline:
            raise RuntimeError(f"{program} did not start in {START_TIMEOUT} seconds")
        time.sleep(0.5)
    return port


def stop_started():
    """Stops what Sottovoce started, when it quits: the computer is left as
    it was found. A server, a model or a service that was there before is
    left alone."""
    steps = [["unload", m] for m in sorted(_lmstudio["models"])]
    if _lmstudio["server"]:
        steps.append(["server", "stop"])
    if _lmstudio["service_was_up"] is False:
        steps.append(["daemon", "down"])
    for step in steps if lms() else []:
        try:
            _cli([lms(), *step], 30)
        except (OSError, subprocess.SubprocessError):
            pass
    _lmstudio.update(service_was_up=None, server=False, models=set())
    for program, proc in list(_started.items()):
        try:
            if proc is not None:
                proc.terminate()
        except OSError:
            pass
        _started.pop(program, None)


def _chosen() -> dict | None:
    """The program picked in the page, as who_answers() describes a server,
    with "starts" if it will be switched on first. None if it is not here."""
    program, m = choice["program"], choice["model"]
    if program == "LM Studio" and lms():
        port = LMSTUDIO_PORT
    elif program == "Ollama" and ollama():
        port = OLLAMA_PORT
    else:
        return None
    return {"port": port, "program": program, "model": m, "models": [m], "chosen": True,
            "starts": not _answers(port)}


def available() -> dict | None:
    """Who would write: the one picked, else a local server that is on, else
    the built-in model."""
    if choice["program"] == "Sottovoce":
        return builtin()
    if choice["program"]:
        return _chosen()
    return who_answers() or builtin()


def _post(url: str, body: dict, timeout: float):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def who_answers() -> dict | None:
    """The first local server that is on, or None.

    Probed every time instead of remembered: a person switches it on and off,
    and a one-minute-old answer would make the page show a button that does
    not work.
    """
    for port, name in PORTS:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/v1/models",
                    timeout=PROBE_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
            continue
        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        # Embedding models answer on the same endpoint but cannot write.
        writers = [m for m in models if "embed" not in m.lower()]
        if writers:
            return {"port": port, "program": name, "model": writers[0],
                    "models": writers}
    return None


def ask(instructions: str, request: str, model: str | None = None) -> dict:
    """One answer from the local LLM, or an explained error.

    Never raises towards the web server: a summary or an email that does not
    come is an inconvenience, not a failure. The transcript, which is the
    real work, is already on disk.
    """
    if choice["program"] in ("LM Studio", "Ollama"):
        try:
            port = start(choice["program"])
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            return {"error": str(e)}
        server = {"port": port, "program": choice["program"], "model": choice["model"]}
    else:
        server = None if choice["program"] == "Sottovoce" else who_answers()
    if server is None:
        if builtin():
            try:
                return _builtin_ask(instructions, request)
            except Exception as e:            # a download cut short, the GPU out of memory
                return {"error": f"the built-in model failed: {type(e).__name__}: {e}"}
        return {"error": "no LLM server is running on this machine, and the built-in "
                         "model needs an NVIDIA GPU"}

    body = {"model": model or server["model"],
            "messages": [{"role": "system", "content": instructions},
                         {"role": "user", "content": request}],
            "temperature": 0.3, "max_tokens": MAX_TOKENS, "stream": False}
    if server["program"] == "LM Studio":
        body["ttl"] = IDLE          # a model it loads for this leaves after ten minutes unused
        if lms() and body["model"] and body["model"] not in _lmstudio_loaded():
            _lmstudio["models"].add(body["model"])      # loaded by this request: unloaded at quit
    url = f"http://127.0.0.1:{server['port']}/v1/chat/completions"
    try:
        try:
            reply = _post(url, body, JOB_TIMEOUT)
        except urllib.error.HTTPError:
            # Just-in-time loading turned off in LM Studio: the model is
            # loaded by hand, once, and asked again.
            if server["program"] != "LM Studio" or not lms() or not body["model"]:
                raise
            _cli([lms(), "load", body["model"], "--yes", "--ttl", str(IDLE)], JOB_TIMEOUT)
            reply = _post(url, body, JOB_TIMEOUT)
    except urllib.error.HTTPError as e:
        said = e.read().decode("utf-8", "replace")[:300]
        return {"error": f"{server['program']} refused: {e.code} {said}"}
    except (urllib.error.URLError, OSError, TimeoutError, subprocess.SubprocessError) as e:
        return {"error": f"{server['program']} did not answer: {e}"}

    first = (reply.get("choices") or [{}])[0]
    out = (first.get("message", {}).get("content") or "").strip()

    # Reasoning models put their thinking in a separate field and the answer
    # in `content`. If they run out of tokens while thinking, `content` comes
    # back EMPTY: without this check the page would show a blank box and not
    # say why.
    if not out:
        if first.get("finish_reason") == "length":
            return {"error": "the model ran out of tokens while reasoning, "
                             "before writing the answer: try a model that does "
                             "not reason, or raise MAX_TOKENS"}
        return {"error": "the model answered with nothing"}

    usage = reply.get("usage") or {}
    return {"text": out,
            "model": reply.get("model") or server["model"],
            "program": server["program"],
            "tokens_read": usage.get("prompt_tokens"),
            "tokens_written": usage.get("completion_tokens")}


def summarize(text: str, model: str | None = None) -> dict:
    """The summary: a few lines, then Decided, To do, Open."""
    return ask(INSTRUCTIONS, REQUEST.format(text=text), model)


def followup(text: str, me: str | None = None, others: list[str] | None = None,
             known: bool = False, model: str | None = None) -> dict:
    """The follow-up email, from whoever recorded the call to the others.

    `known` says whether the lines carry who said them. Without it the model
    is told that it is not marked, rather than left to guess who promised
    what.
    """
    if known:
        who = (f"Lines starting with '{me}:' are the person who recorded the call, "
               "who sends the email; the others are the other side.") if me else (
               "Each line starts with who said it.")
    else:
        who = "It is not marked who said each line."
    sender = me or "the person who recorded the call"
    recipient = ", ".join(others) if others else "the other people on the call"
    signature = (f"with the name {me}" if me else
                 "with a placeholder for the sender's name in square brackets, written in "
                 "the language of the transcript (for example [il tuo nome] in Italian)")
    return ask(FOLLOWUP_INSTRUCTIONS,
               FOLLOWUP_REQUEST.format(who=who, sender=sender, recipient=recipient,
                                       signature=signature, text=text), model)


if __name__ == "__main__":
    import pathlib
    import sys
    import time

    if len(sys.argv) < 2:
        s = who_answers()
        print(f"  {s['program']} on port {s['port']}: {s['model']}" if s
              else "  no LLM server is running")
        print("\n  usage: python summary.py <file.md|file.txt>")
        raise SystemExit

    t0 = time.time()
    r = summarize(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    if "error" in r:
        print(f"  {r['error']}")
        raise SystemExit(1)
    print(r["text"])
    print(f"\n  {r['model']} via {r['program']}, "
          f"{r['tokens_read']} tokens read, {round(time.time() - t0, 1)} s")
