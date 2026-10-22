"""The summary of a call, and the follow-up email, written by an LLM running on this machine.

NOTHING NEW TO DOWNLOAD. We do not load a second model ourselves: we speak the
OpenAI protocol to a local server that is already there (LM Studio, Ollama,
`llama-server`). If you run one, you get summaries; if you do not, you get
everything else and never notice, because the button does not appear.

The reason is VRAM. Whisper fits in 3 GB, a useful LLM wants another 5 to 16:
keeping both loaded all the time, for something asked for once at the end of a
call, is paying rent on a room you open once a day. A separate server is
switched on when needed.

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
    server = who_answers()
    if server is None:
        return {"error": "no LLM server is running on this machine"}

    try:
        reply = _post(
            f"http://127.0.0.1:{server['port']}/v1/chat/completions",
            {"model": model or server["model"],
             "messages": [{"role": "system", "content": instructions},
                          {"role": "user", "content": request}],
             "temperature": 0.3, "max_tokens": MAX_TOKENS, "stream": False},
            JOB_TIMEOUT)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"error": f"{server['program']} did not answer: {e}"}

    choice = (reply.get("choices") or [{}])[0]
    out = (choice.get("message", {}).get("content") or "").strip()

    # Reasoning models put their thinking in a separate field and the answer
    # in `content`. If they run out of tokens while thinking, `content` comes
    # back EMPTY: without this check the page would show a blank box and not
    # say why.
    if not out:
        if choice.get("finish_reason") == "length":
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
