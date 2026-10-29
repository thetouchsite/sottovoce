"""Word error rate on public recordings with hand-made transcripts.

    python research/wer.py fleurs     Italian, read speech: FLEURS it_it, test (865 recordings)
    python research/wer.py ami        English meetings, whole: four AMI test meetings
    python research/wer.py silence    Italian with long, slightly noisy silences: invented words

    --configs large-v3,turbo,sottovoce    which ones (default: all three)
    --limit N                             only the first N recordings or meetings

Three ways to transcribe, on the same audio:

    large-v3    Whisper large-v3 alone, through the transformers pipeline with
                its defaults: what you get by running the model as it comes
    turbo       Whisper large-v3-turbo alone, the same way
    sottovoce   the whole engine: transcribe.run(), with loudness
                normalization, the anti-hallucination settings and the removal
                of subtitle phrases on silence

The engine can be measured on each of the paths it can take (transcribe.PATHS),
and with turbo:

    sottovoce@cuda  sottovoce@intel-gpu  sottovoce@cpu  sottovoce@cpu+turbo

"sottovoce" alone is the path this computer would take by itself.

WER = (substituted + deleted + inserted words) / words in the reference, over
the whole set. Reference and transcript go through the same normalizer,
Whisper's own (EnglishTextNormalizer for English, BasicTextNormalizer for
Italian): case, punctuation and filler words don't count.

The data (CC BY 4.0) is downloaded once into research/fleurs/ and
research/ami/, both git-ignored: FLEURS from Hugging Face (no account), AMI
from the University of Edinburgh's mirror.

Needs: pip install jiwer (only for this script), and the engine's own
requirements with a GPU.
"""
import argparse
import csv
import json
import pathlib
import random
import sys
import tarfile
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import soundfile as sf

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import transcribe as T                                      # noqa: E402

# Never your own glossary: it holds your clients' names and would bend the score.
T.GLOSSARY = HERE / "no-glossary.txt"

FLEURS = HERE / "fleurs"
AMI = HERE / "ami"
AMI_MEETINGS = ["ES2004a", "IS1009a", "TS3003a", "EN2002a"]     # one per series of the test set
AMI_AUDIO = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/{m}/audio/{m}.Mix-Headset.wav"
AMI_WORDS = "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip"
MODELS = {"large-v3": "openai/whisper-large-v3", "turbo": "openai/whisper-large-v3-turbo"}
RATE = 16000


# --- data ---------------------------------------------------------------------------

def fleurs(limit=None):
    """[(wav path, reference)] for FLEURS Italian, test split."""
    from huggingface_hub import hf_hub_download
    tsv = pathlib.Path(hf_hub_download("google/fleurs", "data/it_it/test.tsv",
                                       repo_type="dataset", local_dir=FLEURS))
    audio = FLEURS / "test"
    if not audio.exists():
        tar = hf_hub_download("google/fleurs", "data/it_it/audio/test.tar.gz",
                              repo_type="dataset", local_dir=FLEURS)
        with tarfile.open(tar) as t:
            t.extractall(FLEURS, filter="data")
    rows = []
    for r in csv.reader(tsv.open(encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE):
        f = audio / r[1]
        if f.exists():
            rows.append((f, r[2]))
    return rows[:limit] if limit else rows


def ami(limit=None):
    """[(wav path, reference)] for whole AMI meetings: every word, in time order."""
    from two_tracks import download
    AMI.mkdir(exist_ok=True)
    words_zip = AMI / "ami_public_manual_1.6.2.zip"
    if not words_zip.exists():
        download(AMI_WORDS, words_zip)
    out = []
    with zipfile.ZipFile(words_zip) as z:
        for m in AMI_MEETINGS[:limit] if limit else AMI_MEETINGS:
            wav = AMI / f"{m}.wav"
            if not wav.exists():
                download(AMI_AUDIO.format(m=m), wav)
            words = []
            for name in z.namelist():
                if name.startswith(f"words/{m}.") and name.endswith(".words.xml"):
                    for w in ET.fromstring(z.read(name)).iter():
                        if w.tag == "w" and w.get("punc") != "true" and w.text and w.get("starttime"):
                            words.append((float(w.get("starttime")), w.text))
            out.append((wav, " ".join(t for _, t in sorted(words))))
    return out


def silence_set(n_files=5, per_file=10, seed=0):
    """Files of FLEURS sentences separated by 15 to 45 s of faint noise.

    Silence that is truly digital rarely makes Whisper invent; the faint hiss
    of a real line does. Returns [(wav path, reference, [(start, end) of
    speech])].
    """
    rows = fleurs()
    rng = random.Random(seed)
    picks = rng.sample(rows, n_files * per_file)
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="sottovoce-silence-"))
    noise = np.random.default_rng(seed)
    files = []
    for i in range(n_files):
        parts, ref, speech, t = [], [], [], 0.0
        for f, text in picks[i * per_file:(i + 1) * per_file]:
            gap = rng.uniform(15, 45)
            parts.append(noise.normal(0, 10 ** (-50 / 20), int(gap * RATE)).astype(np.float32))
            t += gap
            x, rate = sf.read(str(f), dtype="float32")
            assert rate == RATE
            parts.append(x)
            speech.append((t, t + len(x) / RATE))
            t += len(x) / RATE
            ref.append(text)
        parts.append(noise.normal(0, 10 ** (-50 / 20), int(20 * RATE)).astype(np.float32))
        wav = out_dir / f"silence-{i}.wav"
        sf.write(str(wav), np.concatenate(parts), RATE)
        files.append((wav, " ".join(ref), speech))
    return files


# --- transcribing ---------------------------------------------------------------------

_plain = {}


def plain(model_id, wav, language):
    """Whisper as it comes: the transformers pipeline, its defaults, timestamps on."""
    import torch
    from transformers import pipeline
    if model_id not in _plain:
        _plain.clear()
        torch.cuda.empty_cache()
        _plain[model_id] = pipeline("automatic-speech-recognition", model=model_id,
                                    dtype=torch.float16, device="cuda")
    r = _plain[model_id](str(wav), return_timestamps=True,
                         generate_kwargs={"language": language, "task": "transcribe"})
    words, _ = T.spread(r.get("chunks", []))
    return words


# What follows the path, in any order: +turbo (the turbo model), +precise
# (precise word timings), +whole (the call given to Whisper whole, not in
# pieces of transcribe.PIECE seconds).
OPTIONS = ("+turbo", "+precise", "+whole")
how = {"precise": False}


def engine_config(config):
    """ "sottovoce@intel-gpu+turbo" -> ("intel-gpu", True); None if not the engine."""
    if not config.startswith("sottovoce"):
        return None
    rest = config[len("sottovoce"):]
    turbo = "+turbo" in rest
    p = rest
    for o in OPTIONS:
        p = p.replace(o, "")
    p = p.removeprefix("@")
    if p and p not in T.PATHS:
        raise SystemExit(f"unknown path {p!r}: {', '.join(T.PATHS)}")
    return p, turbo


def ours(wav, language):
    r = T.run(wav, language, precise=how["precise"])
    return [w for s in r["segments"] for w in (s.get("words") or [])]


def load(config):
    """The model on the GPU before the clock starts: loading is not transcribing."""
    import torch
    from transformers import pipeline
    if engine_config(config):
        _plain.clear()
        torch.cuda.empty_cache()
        p, turbo = engine_config(config)
        if p and p not in T.found():
            raise SystemExit(f"{p} is not on this computer: {', '.join(T.found())}")
        T.choose(p, turbo)
        how["precise"] = "+precise" in config
        T.PIECES = "+whole" not in config
        T.engine()
    elif MODELS[config] not in _plain:
        _plain.clear()
        torch.cuda.empty_cache()
        _plain[MODELS[config]] = pipeline("automatic-speech-recognition", model=MODELS[config],
                                          dtype=torch.float16, device="cuda")


def transcribe(config, wav, language):
    return ours(wav, language) if engine_config(config) else plain(MODELS[config], wav, language)


# --- scoring --------------------------------------------------------------------------

def normalizer(language):
    from transformers import WhisperTokenizer
    tok = WhisperTokenizer.from_pretrained(MODELS["large-v3"])
    if language == "en":
        return tok.normalize
    return lambda s: tok.basic_normalize(s, remove_diacritics=False)


def score(refs, hyps, norm):
    import jiwer
    pairs = [(norm(r), norm(h)) for r, h in zip(refs, hyps)]
    pairs = [(r, h) for r, h in pairs if r.strip()]
    o = jiwer.process_words([r for r, _ in pairs], [h for _, h in pairs])
    n = o.hits + o.substitutions + o.deletions
    return {"wer": o.wer, "sub": o.substitutions / n, "del": o.deletions / n,
            "ins": o.insertions / n, "ref_words": n}


# --- the runs ------------------------------------------------------------------------

def run_set(name, items, language, configs):
    norm = normalizer(language)
    audio_s = sum(sf.info(str(i[0])).duration for i in items)
    print(f"\n  {name}: {len(items)} recordings, {audio_s / 60:.0f} min of audio\n")
    print("  config       WER     sub     del     ins     seconds   x real time")
    results = {}
    for c in configs:
        load(c)
        t0 = time.time()
        hyps = [" ".join(w[2] for w in transcribe(c, i[0], language)) for i in items]
        secs = time.time() - t0
        s = score([i[1] for i in items], hyps, norm)
        results[c] = {**s, "seconds": round(secs), "audio_seconds": round(audio_s)}
        if engine_config(c):
            results[c]["engine"] = T.key(how["precise"])
            # The most RAM this process has held so far: run one config per
            # process to read it for that config alone.
            try:
                import psutil
                results[c]["peak_ram_gb"] = round(psutil.Process().memory_info().peak_wset / 2 ** 30, 1)
            except (ImportError, AttributeError):
                pass
        print(f"  {c:10}  {s['wer']:6.1%}  {s['sub']:6.1%}  {s['del']:6.1%}  {s['ins']:6.1%}  "
              f"{secs:9.0f}   {audio_s / secs:10.1f}"
              + (f"   peak RAM {results[c]['peak_ram_gb']} GB" if "peak_ram_gb" in results[c] else ""), flush=True)
    return results


def subtitle_phrases(text):
    """How many of Whisper's subtitle phrases a text holds, each counted once:
    "sottotitoli e revisione" is one phrase, not two."""
    import re
    known = sorted(T.SUBTITLE_PHRASES, key=len, reverse=True)
    return len(re.findall("|".join(map(re.escape, known)), text.lower()))


def run_silence(configs, limit=None):
    """Invented words are counted as the words the transcript has and the
    reference doesn't (insertions). Not by where they fall: word times are
    estimated across each line, and a line that starts in a pause would put
    real words in the silence."""
    files = silence_set()[:limit] if limit else silence_set()
    norm = normalizer("it")
    total = sum(sf.info(str(f[0])).duration for f in files)
    quiet = total - sum(b - a for f in files for a, b in f[2])
    print(f"\n  silence: {len(files)} files, {total / 60:.0f} min, {quiet / 60:.0f} min of it faint noise\n")
    print("  config       WER     words added   subtitle phrases")
    results = {}
    for c in configs:
        load(c)
        hyps = [" ".join(w[2] for w in transcribe(c, f[0], "it")) for f in files]
        s = score([f[1] for f in files], hyps, norm)
        added = round(s["ins"] * s["ref_words"])
        phrases = sum(subtitle_phrases(h) for h in hyps)
        results[c] = {**s, "words_added": added, "subtitle_phrases": phrases, "transcripts": hyps}
        print(f"  {c:10}  {s['wer']:6.1%}   {added:>11}   {phrases:>16}", flush=True)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=["fleurs", "ami", "silence"])
    ap.add_argument("--configs", default="large-v3,turbo,sottovoce")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    import torch
    import platform
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no NVIDIA GPU"
    print(f"\n  {gpu}, {platform.processor() or 'CPU'}, torch {torch.__version__}, "
          f"paths here: {', '.join(T.found())}")
    if args.set == "fleurs":
        r = run_set("FLEURS it_it test", fleurs(args.limit), "it", configs)
    elif args.set == "ami":
        r = run_set("AMI test meetings, Mix-Headset, whole", ami(args.limit), "en", configs)
    else:
        r = run_silence(configs, args.limit)
    out = HERE / "results" / f"wer_{args.set}.json"
    out.parent.mkdir(exist_ok=True)
    # Running one config again keeps the others' results.
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    out.write_text(json.dumps({**old, **r}, indent=1), encoding="utf-8")
    print()


if __name__ == "__main__":
    main()
