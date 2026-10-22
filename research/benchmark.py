"""Runs several transcription models on the SAME file, measured the same way.

Numbers can only be compared when taken with the same instrument. Public
leaderboards measure speech read aloud in a studio; a business call recorded
with a phone on a desk is a different job, and this is how the model in
transcribe.py was chosen.

Besides speed, it looks for Whisper's known defect: phrases invented on
pauses. The test call was silent for 23% of its length, 78 pauses over 1.5 s:
seventy-eight chances to hallucinate.

    python research/benchmark.py whisper-large-v3 call.wav --language it
    python research/benchmark.py parakeet         call.wav

Each run writes research/transcripts/<model>__<file>.txt, which compare.py
reads. Those files are your calls: they are git-ignored.
"""
import argparse
import collections
import pathlib
import re
import time

MODELS = {
    "whisper-large-v3": ("whisper", "openai/whisper-large-v3"),
    "whisper-turbo":    ("whisper", "openai/whisper-large-v3-turbo"),
    "parakeet":         ("parakeet", "nvidia/parakeet-tdt-0.6b-v3"),
    "canary":           ("parakeet", "nvidia/canary-1b-v2"),
}

OUT = pathlib.Path(__file__).resolve().parent / "transcripts"

# Phrases Whisper produces on noise: they come from the YouTube subtitles it
# was trained on, and cannot be in a call.
SUSPICIOUS = ("sottotitoli", "amara.org", "grazie per aver guardato",
              "thanks for watching", "subtitles by", "please subscribe",
              "buona visione", "www.", "http")


def audio_seconds(path):
    import soundfile as sf
    info = sf.info(path)
    return info.frames / info.samplerate


def with_whisper(hf_name, path, language):
    """Long-form with Whisper's own mechanism, not in chunks.

    With `chunk_length_s` the pipeline cuts 30-second slices and stitches
    them: on this audio it produced timestamps going backwards and a loop of
    the same words forty times in a row. The transformers warning says it
    plainly: long-form needs the model's mechanism, which carries context from
    one window to the next.

    The thresholds are OpenAI's own against hallucinations:
      temperature   if a window comes out badly, retry it "warmer"
      compression   text too repetitive -> discarded and redone
      logprob       model too unsure -> discarded and redone
      no_speech     above this the window is silence: do not invent
      condition_on_prev_tokens=False  stops a repetition from feeding itself
                    into the next window
    """
    import torch
    from transformers import pipeline
    p = pipeline("automatic-speech-recognition", model=hf_name,
                 dtype=torch.float16, device="cuda",
                 model_kwargs={"attn_implementation": "sdpa"})
    kwargs = {"task": "transcribe", "condition_on_prev_tokens": False,
              "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
              "compression_ratio_threshold": 1.35, "logprob_threshold": -1.0,
              "no_speech_threshold": 0.6}
    if language:
        kwargs["language"] = language
    r = p(path, return_timestamps=True, generate_kwargs=kwargs)
    return r["text"], [(c["timestamp"], c["text"]) for c in r.get("chunks", [])]


def with_parakeet(hf_name, path, language):
    """NeMo if installed, otherwise transformers. Parakeet detects the language itself."""
    try:
        import nemo.collections.asr as nemo_asr
        m = nemo_asr.models.ASRModel.from_pretrained(model_name=hf_name)
        out = m.transcribe([path], timestamps=True)[0]
        segments = [((s["start"], s["end"]), s["segment"])
                    for s in getattr(out, "timestamp", {}).get("segment", [])]
        return out.text, segments
    except ImportError:
        import torch
        from transformers import pipeline
        p = pipeline("automatic-speech-recognition", model=hf_name,
                     dtype=torch.float16, device="cuda")
        # Timestamps go through a tokenizer path this model does not support:
        # ask for them, and if it breaks take the text alone. Real timestamps
        # need NeMo, which exposes them properly.
        try:
            r = p(path, return_timestamps=True)
            segments = [(c["timestamp"], c["text"]) for c in r.get("chunks", [])]
        except (TypeError, KeyError):
            r = p(path)
            segments = [((None, None), r["text"])]
        return r["text"], segments


def repetitions(segments, at_least=3):
    """Identical segments repeated: the typical signature of a hallucination."""
    count = collections.Counter(t.strip().lower() for _, t in segments if t.strip())
    return [(t, n) for t, n in count.most_common() if n >= at_least]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("model", choices=list(MODELS))
    ap.add_argument("file")
    ap.add_argument("--language", default=None, help='Whisper language code, e.g. "it"')
    args = ap.parse_args()
    kind, hf_name = MODELS[args.model]

    seconds = audio_seconds(args.file)
    print(f"\n{'=' * 64}")
    print(f"  {args.model}   on   {args.file}   ({seconds/60:.1f} minutes)")
    print(f"{'=' * 64}\n")

    t0 = time.time()
    text, segments = (with_whisper if kind == "whisper" else with_parakeet)(
        hf_name, args.file, args.language)
    dt = time.time() - t0

    words = len(text.split())
    print(f"  time         {dt:.0f} s   ({seconds/dt:.0f}x real time)")
    print(f"  words        {words}   ({words/(seconds/60):.0f} per minute)")
    print(f"  segments     {len(segments)}")

    rep = repetitions(segments)
    if rep:
        print("\n  SUSPICIOUS REPETITIONS:")
        for t, n in rep[:5]:
            print(f"     {n}x  \"{t[:60]}\"")
    else:
        print("  repetitions  none")

    sus = [t for _, t in segments if any(s in t.lower() for s in SUSPICIOUS)]
    if sus:
        print(f"\n  SUBTITLE PHRASES ({len(sus)}): {sus[:3]}")
    else:
        print("  spurious     none")

    name = re.sub(r"[^a-z0-9-]", "-", args.model.lower())
    base = re.sub(r"[^a-z0-9-]", "-", pathlib.Path(args.file).stem.lower())
    OUT.mkdir(exist_ok=True)
    dest = OUT / f"{name}__{base}.txt"
    with open(dest, "w", encoding="utf-8") as f:
        for (a, _), t in segments:
            a = a if a is not None else 0
            f.write(f"[{int(a)//60:02d}:{int(a)%60:02d}] {t.strip()}\n")
    print(f"\n  written      {dest}\n")


if __name__ == "__main__":
    main()
