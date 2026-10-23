"""Transcription without an NVIDIA card: how long it takes, how many errors.

    python research/cpu.py                    the first 10 FLEURS Italian clips (2.5 min)
    python research/cpu.py --limit 30         more clips
    python research/cpu.py --configs shipped,fw-int8

The NVIDIA card is hidden (CUDA_VISIBLE_DEVICES), so this is what a computer
without one gets. Every config transcribes the same clips; the model is
loaded before the clock starts.

    plain       Whisper large-v3 alone, float32, no preparation of the audio:
                the fair comparison for research/intel.py
    shipped     the engine as installed today without NVIDIA: transcribe.run,
                Whisper large-v3 loaded in float16 on the processor
    fp32        the same engine, the model in float32
    turbo       the same engine with large-v3-turbo, float32
    fw-int8     faster-whisper (CTranslate2, MIT), large-v3 in int8, the
                engine's decoding settings
    fw-turbo    faster-whisper, large-v3-turbo in int8

Scored like research/wer.py: WER after Whisper's own normalizer.
Needs: pip install jiwer faster-whisper
"""
import argparse
import json
import os
import pathlib
import sys
import time

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"              # before torch: no NVIDIA card here ("" is not enough on Windows)

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import soundfile as sf                                    # noqa: E402

import transcribe as T                                    # noqa: E402
import wer as W                                           # noqa: E402

T.GLOSSARY = HERE / "no-glossary.txt"


def engine(model, dtype):
    """The engine's pipeline, built here with the model and the precision asked."""
    import torch
    from transformers import pipeline
    T.release()
    T._engine = T._Torch.__new__(T._Torch)
    T._engine.p = pipeline("automatic-speech-recognition", model=model, dtype=getattr(torch, dtype), device="cpu")


def ours(wav):
    r = T.run(wav, "it")
    return " ".join(w[2] for s in r["segments"] for w in (s.get("words") or []))


_fw = {}


def faster(name, wav):
    from faster_whisper import WhisperModel
    if name not in _fw:
        _fw.clear()
        _fw[name] = WhisperModel(name, device="cpu", compute_type="int8")
    d = T.DECODE
    audio, _ = sf.read(str(wav), dtype="float32")         # its own decoder trips on this PyAV
    segments, _ = _fw[name].transcribe(
        audio, language="it", beam_size=1, condition_on_previous_text=d["condition_on_prev_tokens"],
        temperature=list(d["temperature"]), compression_ratio_threshold=d["compression_ratio_threshold"],
        log_prob_threshold=d["logprob_threshold"], no_speech_threshold=d["no_speech_threshold"])
    return " ".join(s.text.strip() for s in segments)


def plain(wav):
    """Whisper alone, as OpenVINO is measured: no loudness, no map of speech."""
    audio, _ = sf.read(str(wav), dtype="float32")
    r = T._engine.p(audio, return_timestamps=True, generate_kwargs={"language": "it", "task": "transcribe"})
    return r["text"]


CONFIGS = {
    "plain": (lambda: engine(T.MODEL, "float32"), plain),
    "shipped": (lambda: T.release(), ours),
    "fp32": (lambda: engine(T.MODEL, "float32"), ours),
    "turbo": (lambda: engine("openai/whisper-large-v3-turbo", "float32"), ours),
    "fw-int8": (lambda: None, lambda wav: faster("large-v3", wav)),
    "fw-turbo": (lambda: None, lambda wav: faster("large-v3-turbo", wav)),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--configs", default=",".join(CONFIGS))
    args = ap.parse_args()
    import platform
    import torch
    if torch.cuda.is_available():
        raise SystemExit("the NVIDIA card is still visible: these numbers would be the GPU's")
    print(f"\n  {platform.processor() or 'CPU'}, {os.cpu_count()} threads, torch {torch.__version__}, no CUDA")
    items = W.fleurs(args.limit)
    audio = sum(sf.info(str(f)).duration for f, _ in items)
    norm = W.normalizer("it")
    print(f"  FLEURS it_it test, first {len(items)} clips: {audio:.0f} s of audio\n")
    print("  config      WER     seconds   x real time")
    results = {}
    for c in [c.strip() for c in args.configs.split(",") if c.strip()]:
        prepare, run = CONFIGS[c]
        prepare()
        run(items[0][0])                                  # loads the model, off the clock
        t0 = time.time()
        hyps = [run(f) for f, _ in items]
        secs = time.time() - t0
        s = W.score([r for _, r in items], hyps, norm)
        results[c] = {**s, "seconds": round(secs, 1), "audio_seconds": round(audio, 1)}
        print(f"  {c:10}  {s['wer']:6.1%}  {secs:8.0f}   {audio / secs:10.2f}", flush=True)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "cpu.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
