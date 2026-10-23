"""How long the built-in LLM takes to write, on the example calls in the repo.

    python research/llm.py

Runs the model built into summary.py (no LM Studio or Ollama, even if one is
running) through the same endpoints the page uses, on a copy of the fictional
calls in examples/:

    follow-up   the email after "Kickoff Halden Studio" (Italian, 1 minute)
    summary     the summary of "Northpine launch sync" (English, 11 minutes)

Each is asked twice: the first time includes loading the model on the GPU,
the second does not. It prints the time of each, the tokens read and written,
and the GPU memory the model held. The examples are in the repo, so the
numbers can be checked by anyone with an NVIDIA GPU; the first run also
downloads the model (8 GB).
"""
import pathlib
import shutil
import sys
import tempfile
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def main():
    import torch
    import server
    import summary
    from fastapi.testclient import TestClient

    if not torch.cuda.is_available():
        raise SystemExit("the built-in model needs an NVIDIA GPU")
    summary.who_answers = lambda: None            # the built-in model, whatever else runs
    print(f"\n  {torch.cuda.get_device_name(0)}, torch {torch.__version__}, model {summary.BUILTIN}\n")
    with tempfile.TemporaryDirectory() as tmp:
        data = pathlib.Path(tmp) / "examples"
        shutil.copytree(ROOT / "examples", data)
        server.start(data / "transcripts", data / "glossary.txt", model=False)
        client = TestClient(server.app)
        jobs = [("follow-up", "/api/followup/2026-10-17_Kickoff Halden Studio?redo=true"),
                ("summary", "/api/summary/2026-10-21_Northpine launch sync?redo=true")]
        print("  task        run          seconds   tokens read   tokens written")
        for run in ("with loading", "loaded"):
            if run == "with loading":
                summary._builtin.update(model=None, tok=None)
                torch.cuda.empty_cache()
            for name, url in jobs:
                t0 = time.time()
                r = client.post(url).json()
                if "error" in r:
                    raise SystemExit(f"  {name}: {r['error']}")
                print(f"  {name:10}  {run:12}  {time.time() - t0:7.1f}   {r.get('tokens_read'):>11}   "
                      f"{r.get('tokens_written'):>14}", flush=True)
                run = "loaded" if run == "with loading" else run
        print(f"\n  GPU memory held by the model: {torch.cuda.max_memory_allocated() / 2 ** 30:.1f} GB\n")


if __name__ == "__main__":
    main()
