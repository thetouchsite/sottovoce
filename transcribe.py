"""The engine: from a recording to text. Used by the server and from the command line.

    python transcribe.py "C:\\path\\Client call.mp4" [--language it] [--formats txt,md,srt]

Takes anything ffmpeg can read (mp4, m4a, mp3, wav, opus, 3gp, webm) and writes
next to the original a .txt with timestamps, a .md in paragraphs, and on
request .srt, .vtt and .json.

The choices inside are not taste. They were measured on 22 October 2026 on a
real 27-minute business call recorded with a phone. If you change this file,
know what you would break.

MODEL: whisper-large-v3.
    Compared with whisper-large-v3-turbo and parakeet-tdt-0.6b-v3 on the same
    call. Non-existent words produced, out of 2,500: large-v3 1.2%, turbo 2.2%,
    parakeet 2.8%. The gap shows on proper nouns: one company name came out of
    parakeet spelled eight different ways, out of large-v3 almost always the
    same. In a business call the names are the content that matters.
    Turbo is three times faster but makes twice the mistakes: on 27 minutes it
    saves two minutes. Not worth it. The full comparison is in research/.

LOUDNESS NORMALIZATION before transcribing.
    Phone audio has one voice close to the microphone and the others coming
    out of the speaker: mean -29.8 dB with peaks at -0.9. Bringing it to a
    uniform level does not change the text, but Whisper gets 35% faster,
    because on a weak signal it discards and retries the uncertain windows.

LONG-FORM with Whisper's own mechanism, not in chunks.
    With `chunk_length_s` the pipeline cuts 30-second slices and stitches them
    back together: on this call it produced timestamps going backwards and a
    loop of the same three words forty times in a row. Do not add it to go
    faster.

TWO PROGRAMS, ONE MODEL. The same Whisper large-v3 runs through PyTorch on
an NVIDIA card and through OpenVINO on an Intel GPU or on the processor,
whichever is fastest on this computer. See "where Whisper runs" below.

WORD TIMESTAMPS, two ways. By default each line's time is shared among its
words: as fast as before. On request (--precise) from Whisper's own
alignment, no second model: same quality, twice the time. See listen().

HALLUCINATIONS ON SILENCE: Whisper learned from YouTube subtitles and, on
silent stretches, writes "Thanks for watching", "Subtitles by...". They are
dropped only when two things are both true: the text is one of those phrases,
and the audio at that point is far below the level of speech. See
drop_phantoms().

TWO TRACKS. A call recorded from the page has your microphone on the left
channel and the call's audio on the right. Who speaks is then a measurement,
not a guess: see label_speakers().

VOICES. On request (--voices), the people on the call are told apart by the
sound of their voice, for any recording: see voices.py for the models and the
measurements. On two tracks only the call's side is split, since "Me" is
already known.
"""
from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import tempfile
import threading
import time

MODEL = "openai/whisper-large-v3"

# Phrases Whisper learned from YouTube subtitles and produces on silence. In a
# call they mean nothing. They are flagged when found and dropped only where
# the audio is silent (drop_phantoms): the last one of a call can be real.
#
# Only phrases that belong to subtitles, not to conversation: a plain
# "thank you" would flag every polite line of every call.
SUBTITLE_PHRASES = (
    # Italian
    "grazie a tutti", "sottotitoli", "buona visione", "grazie per aver guardato",
    "iscriviti al canale", "sottotitoli e revisione", "alla prossima",
    # English
    "thanks for watching", "thank you for watching", "subtitles by",
    "captions by", "please subscribe", "transcribed by",
    # Spanish, French, German, Portuguese
    "subtítulos realizados por", "gracias por ver", "suscríbete",
    "sous-titres réalisés", "merci d'avoir regardé", "sous-titrage",
    "untertitel im auftrag", "untertitelung", "danke fürs zuschauen",
    "legendas pela comunidade", "obrigado por assistir",
    # The community that made most of them
    "amara.org",
)

# The two voices of a call recorded from the page: you on the microphone, the
# others on the call's audio. With voices told apart, the others become
# "Voice 1", "Voice 2"... Only these are read back as speaker tags, so a line
# that really starts with "[Music]" stays text.
SPEAKERS = ("Me", "Them")
TAG = "|".join(SPEAKERS) + r"|Voice \d{1,2}"

ROOT = pathlib.Path(__file__).resolve().parent

def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# --- where Whisper runs -------------------------------------------------------------
#
# The same model, Whisper large-v3, through two programs:
#
#     cuda        PyTorch on an NVIDIA card, float16
#     intel-gpu   OpenVINO on an Intel GPU, Arc or built into the processor, int8
#     cpu         OpenVINO on the processor, Intel or AMD, int8
#
# OpenVINO's large-v3 is the OpenVINO organisation's int8 conversion on
# Hugging Face. On a processor it is about five times faster than PyTorch
# (research/intel.py and research/cpu.py, the first ten FLEURS clips). Whole,
# end to end, research/wer.py with the sottovoce@<path> configs: the same error
# rate within a few tenths on every path, on FLEURS, AMI and the long pauses.
#
# Not used: OpenVINO on an NVIDIA card, through OpenCL (2.0x real time on
# those ten clips, research/intel.py --configs nvidia, far below PyTorch on the
# same card), and the NPU of the Core Ultra tried (95% of words wrong,
# --configs npu-turbo). A GPU that is neither NVIDIA nor Intel, AMD's for one,
# runs on the processor for now.

PATHS = {"cuda": "NVIDIA GPU", "intel-gpu": "Intel GPU", "cpu": "processor"}

# (program, turbo) -> the model. Turbo is the user's choice on a slow computer:
# about twice as fast through OpenVINO (SPEEDS), with more mistakes, above all
# on names (see MODEL above).
REPOS = {
    ("torch", False): "openai/whisper-large-v3",
    ("torch", True): "openai/whisper-large-v3-turbo",
    ("openvino", False): "OpenVINO/whisper-large-v3-int8-ov",
    ("openvino", True): "OpenVINO/whisper-large-v3-turbo-int8-ov",
}
# Measured on disk, for the page to say what the first transcription downloads.
SIZE_GB = {"openai/whisper-large-v3": 2.9, "openai/whisper-large-v3-turbo": 1.6,
           "OpenVINO/whisper-large-v3-int8-ov": 1.5, "OpenVINO/whisper-large-v3-turbo-int8-ov": 0.8}

# How much faster than real time, from the start of transcribing to the end:
# the page's estimate of how long is left. By (path, turbo), then (segments,
# precise word timings); None where not measured, and the page shows a moving
# bar. These are the defaults; once a call of a minute or more has been
# transcribed here, the speed this computer really had is used instead
# (`measured`, kept by the server).
#
# cuda: 200 s for the 27-minute call, 395 s with precise word timings, on an
# RTX 5090 Laptop. The others: the four whole AMI test meetings, 92 minutes,
# on a Core Ultra 9 285H with its Arc 140T (research/wer.py ami, configs
# sottovoce@intel-gpu, sottovoce@cpu and the same +turbo). A smaller computer
# is slower: its first call corrects the estimate.
SPEEDS = {
    ("cuda", False): (7.0, 3.8),
    ("intel-gpu", False): (10.8, None),
    ("intel-gpu", True): (28.5, None),
    ("cpu", False): (5.2, None),
    ("cpu", True): (9.2, None),
}
measured: dict[str, float] = {}

# What the user chose. path None: the first found. SOTTOVOCE_ENGINE, if set,
# wins over both: a way to try OpenVINO on a computer with an NVIDIA card.
chosen = {"path": None, "turbo": False}

_found: list[str] | None = None
_found_lock = threading.Lock()
_intel: str | None = None
_engine = None
_lock = threading.Lock()


def _intel_gpu() -> str | None:
    """OpenVINO's name for the first Intel GPU, "GPU.0", or None.

    OpenVINO lists an NVIDIA card as a GPU too, through OpenCL: only Intel's
    are kept."""
    try:
        import openvino as ov
        core = ov.Core()
        for d in core.available_devices:
            if d.startswith("GPU") and "intel" in str(core.get_property(d, "FULL_DEVICE_NAME")).lower():
                return d
    except Exception:
        pass
    return None


def openvino() -> bool:
    return importlib.util.find_spec("openvino_genai") is not None


def found() -> list[str]:
    """The paths this computer has, the likely fastest first. Looked up once:
    the hardware does not change while the program runs."""
    global _found
    with _found_lock:
        if _found is None:
            _found = _look()
    return _found


def looked() -> bool:
    """Whether found() has already looked: the first time imports PyTorch
    and asks OpenVINO for its devices, seconds the page should not wait."""
    return _found is not None


def _look() -> list[str]:
    global _intel
    out = []
    try:
        import torch
        if torch.cuda.is_available():
            out.append("cuda")
    except ImportError:
        pass
    if openvino():
        _intel = _intel_gpu()
        if _intel:
            out.append("intel-gpu")
    return out + ["cpu"]


def path() -> str:
    """Where Whisper runs: forced, else chosen, else the first found."""
    want = os.environ.get("SOTTOVOCE_ENGINE") or chosen["path"]
    return want if want in found() else found()[0]


def program(p=None) -> str:
    """ "torch" or "openvino". The processor falls back to PyTorch where
    OpenVINO is not installed."""
    p = p or path()
    return "torch" if p == "cuda" or not openvino() else "openvino"


def model(p=None, turbo=None) -> str:
    """The model that runs on path p, by default the one in use."""
    return REPOS[(program(p), chosen["turbo"] if turbo is None else turbo)]


def choose(p=None, turbo=None):
    """Sets where Whisper runs and which model. Lets the loaded one go if
    that changes them: the next transcription loads the new one."""
    before = (path(), model())
    if p is not None:
        chosen["path"] = p or None             # "" back to automatic
    if turbo is not None:
        chosen["turbo"] = bool(turbo)
    if (path(), model()) != before:
        release()


def key(precise=False, p=None, turbo=None) -> str:
    """What a measured speed is about: path, model, kind of word timings."""
    return f"{p or path()}|{model(p, turbo)}|{'precise' if precise else 'segments'}"


def speed(precise=False, p=None, turbo=None) -> float | None:
    """Times faster than real time here, measured or by default: None when
    neither is known, and the page shows a moving bar instead of a countdown."""
    k = key(precise, p, turbo)
    if k in measured:
        return measured[k]
    s = SPEEDS.get((p or path(), chosen["turbo"] if turbo is None else turbo))
    return (s[1] if precise else s[0]) if s else None


# Seconds without a transcription before the server lets Whisper go: the
# same as the built-in summary model (summary.IDLE).
IDLE = 600


def loaded() -> bool:
    return _engine is not None


def downloaded(repo=None) -> bool:
    """Whether the model is already on disk: if not, the first load downloads it (SIZE_GB)."""
    try:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(repo or model(), "config.json"), str)
    except Exception:
        return False


def release():
    """Frees Whisper's memory (3.4 GB of the GPU measured with PyTorch). The
    next call to engine() loads it again, in about ten seconds."""
    global _engine
    with _lock:
        if _engine is None:
            return
        _engine = None
    import gc
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass


def engine():
    """Whisper, loaded on first use and kept until released.

    Loading it takes about ten seconds. The server loads it for the first
    transcription and lets it go IDLE seconds after the last one, so a
    Sottovoce left open all day holds the GPU only while it works. From the
    command line it is paid for every file.
    """
    global _engine
    with _lock:
        if _engine is None:
            p = path()
            if program(p) == "openvino":
                found()
                _engine = _OpenVINO(model(p), _intel if p == "intel-gpu" else "CPU")
            else:
                _engine = _Torch(model(p), "cuda" if p == "cuda" else "cpu")
        return _engine


class _Torch:
    """Whisper through the transformers pipeline."""

    def __init__(self, repo, device):
        import torch
        from transformers import pipeline
        self.p = pipeline(
            "automatic-speech-recognition", model=repo,
            dtype=torch.float16 if device == "cuda" else torch.float32,
            device=device, model_kwargs={"attn_implementation": "sdpa"})

    def segments(self, wav, language, speech=None):
        r = self.p(str(wav), return_timestamps=True, generate_kwargs=_decode(language))
        return r.get("chunks", [])

    def words(self, wav, language):
        r = self.p(str(wav), return_timestamps="word", generate_kwargs=_decode(language))
        out = []
        for c in r.get("chunks", []):
            token = c["text"].strip()
            a, b = c["timestamp"]
            if token and a is not None:
                out.append([a, b if b is not None else a, token])
        return out

    def language(self, audio):
        r = self.p({"raw": audio, "sampling_rate": 16000}, return_language=True,
                   return_timestamps=True, generate_kwargs={"task": "transcribe"})
        return next((c.get("language") for c in r.get("chunks", []) if c.get("language")), None)


# Whisper's own limit: text that compresses more than this has looped
# ("un'esplosione di un'esplosione di..."). The PyTorch engine redoes such a
# window by itself (DECODE); OpenVINO has no such setting, so _OpenVINO does it.
LOOPED = 2.4


def looped(text) -> bool:
    import zlib
    b = text.encode("utf-8")
    return len(b) > 40 and len(b) / len(zlib.compress(b)) > LOOPED


def unloop(text):
    """One copy of a phrase of up to eight words said three times or more in a row."""
    words, out, i = text.split(), [], 0
    while i < len(words):
        for n in range(1, 9):
            unit, times = words[i:i + n], 1
            while len(unit) == n and words[i + times * n:i + (times + 1) * n] == unit:
                times += 1
            if times >= 3:
                out += unit
                i += times * n
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


class _OpenVINO:
    """Whisper through OpenVINO GenAI, on an Intel GPU or the processor.

    Its decoding is greedy, without the settings of DECODE: no retry of a
    window that came out badly, no skipping a window of silence. On the
    long-pauses test that let one window loop a phrase a hundred times, so a
    looped window is done again here (_again), the way the PyTorch engine
    would. What it costs and saves is measured, not assumed: research/wer.py
    with the sottovoce@intel-gpu and sottovoce@cpu configs.
    """

    def __init__(self, repo, device):
        self.repo, self.device = repo, device
        self.p, self.with_words = self._pipeline(False), False

    def _pipeline(self, words):
        import openvino_genai as og
        from huggingface_hub import snapshot_download
        folder = pathlib.Path(snapshot_download(self.repo))
        # Compiled for this device the first time and kept beside the model,
        # so it goes with it: loading again takes seconds instead of a minute.
        props = {"CACHE_DIR": str(folder.parent.parent / "openvino-cache")}
        if words:
            props["word_timestamps"] = True
        return og.WhisperPipeline(str(folder), self.device, **props)

    def _generate(self, audio, language, words=False, temperature=0.0):
        if words and not self.with_words:
            # Word timings need a pipeline built for them: built when first
            # asked, and kept.
            self.p, self.with_words = self._pipeline(True), True
        c = self.p.get_generation_config()
        c.task = "transcribe"
        c.return_timestamps = True
        if language:
            c.language = f"<|{language}|>"
        if words:
            c.word_timestamps = True
        if temperature:
            c.do_sample, c.temperature, c.rng_seed = True, temperature, 0
        return self.p.generate(audio, c)

    @staticmethod
    def _audio(wav):
        import soundfile as sf
        audio, rate = sf.read(str(wav), dtype="float32")
        assert rate == 16000, rate
        return audio

    def segments(self, wav, language, speech=None):
        audio = self._audio(wav)
        out = []
        for c in self._generate(audio, language).chunks or []:
            a, b = c.start_ts, c.end_ts
            if not looped(c.text):
                out.append({"text": c.text, "timestamp": (a, b)})
                continue
            # No ending time: the loop ran to the end of its 30-second window.
            b = b if b > a else min(a + 30, len(audio) / 16000)
            out += self._again(audio, a, b, language, speech)
        return out

    def _again(self, audio, a, b, language, speech):
        """A looped stretch, done again as the PyTorch engine would: skipped
        if nobody speaks in it (by the map of speech), else only its spoken
        part, greedy and then a little warmer each time; if every try loops,
        one copy of what it repeats."""
        if speech is not None:
            spoken = [x for x, y in speech if x < b and a < y]
            if not spoken:
                return []
            a = max(a, spoken[0] - 0.3)
        clip = audio[int(a * 16000):int(b * 16000)]
        chunks = []
        for t in DECODE["temperature"]:
            chunks = self._generate(clip, language, temperature=t).chunks or []
            if not any(looped(x.text) for x in chunks):
                break
        fix = unloop if any(looped(x.text) for x in chunks) else str
        return [{"text": fix(x.text), "timestamp": (a + x.start_ts, a + x.end_ts if x.end_ts > x.start_ts else b)}
                for x in chunks]

    def words(self, wav, language):
        r = self._generate(self._audio(wav), language, words=True)
        return join_pieces([(w.start_ts, w.end_ts, w.word) for w in r.words or []])

    def language(self, audio):
        return self._generate(audio, None).language or None


def join_pieces(pieces):
    """Words from OpenVINO's word timings, which come in pieces: a piece that
    does not start with a space belongs to the word before ("L" + "'incidente")."""
    out = []
    for a, b, text in pieces:
        if out and text and not text[0].isspace():
            out[-1][1], out[-1][2] = b, out[-1][2] + text
        elif text.strip():
            out.append([a, b, text.strip()])
    return out


LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def prepare(source, dest, two_tracks=False) -> float:
    """16 kHz mono at a uniform loudness: what the model expects.

    Two tracks (you, the call) are mixed half and half before normalizing.
    Normalizing each track first would be fairer to a quiet microphone, and
    dangerous to a muted one: loudnorm would lift its hiss to speech level.
    """
    mix = f"pan=mono|c0=0.5*c0+0.5*c1,{LOUDNORM}" if two_tracks else LOUDNORM
    subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", mix, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
        check=True)
    import soundfile as sf
    info = sf.info(str(dest))
    return info.frames / info.samplerate


def level_copy(source, dest, two_tracks=False):
    """The same audio with one gain for the whole file: for measuring levels.

    What Whisper hears, from prepare(), cannot be used to tell silence from
    speech. In one pass loudnorm adjusts its gain as it goes and lifts long
    quiet stretches: on a test file the faint hiss of a line, at -50 dB
    between sentences, came out at -19 dB, as loud as the speech. The map of
    speech then saw speech in 468 seconds out of 471, and no invented phrase
    was ever dropped. One gain keeps the distance between speech and silence;
    bringing the whole file to the same loudness keeps the -35 dB threshold of
    speech_regions meaning the same on a quiet recording and on a loud one.
    """
    mix = "pan=mono|c0=0.5*c0+0.5*c1," if two_tracks else ""
    r = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(source),
         "-af", f"{mix}{LOUDNORM}:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    try:
        measured = float(json.loads(r.stderr[r.stderr.rindex("{"):])["input_i"])
    except (ValueError, KeyError):
        measured = float("-inf")
    # A file of digital silence has no loudness: it stays as it is.
    gain = -16.0 - measured if measured > -70 else 0.0
    subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", f"{mix}volume={gain:.2f}dB", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_f32le", str(dest)],
        check=True)


# --- where people speak -------------------------------------------------------
#
# The map of speech is used to clean up AFTER transcribing, never to cut the
# audio before. See run() for the measurement that decided it.

SILENCE_THRESHOLD = "-35dB"   # below this level it is silence
MIN_PAUSE = 1.0               # seconds; shorter gaps are breathing, not silence
MARGIN = 0.40                 # seconds kept around speech, not to clip attacks


def speech_regions(wav, duration):
    """The intervals where someone is speaking, with a safety margin."""
    r = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(wav),
         "-af", f"silencedetect=n={SILENCE_THRESHOLD}:d={MIN_PAUSE}", "-f", "null", "-"],
        capture_output=True, text=True)
    silences = []
    start = None
    for line in r.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.split("silence_start:")[1].split()[0])
        elif "silence_end:" in line and start is not None:
            silences.append((start, float(line.split("silence_end:")[1].split()[0])))
            start = None
    if start is not None:
        silences.append((start, duration))

    # Speech is what is left between one silence and the next.
    speech, t = [], 0.0
    for a, b in silences:
        if a - t > 0.1:
            speech.append((max(0.0, t - MARGIN), min(duration, a + MARGIN)))
        t = b
    if duration - t > 0.1:
        speech.append((max(0.0, t - MARGIN), duration))

    # The margin may have made two neighbours touch: merge them.
    merged = []
    for a, b in speech:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


# --- the glossary ---------------------------------------------------------------

# Where the glossary lives. server.py moves it with --glossary.
GLOSSARY = ROOT / "glossary.txt"


def glossary_file() -> pathlib.Path:
    return GLOSSARY


def glossary():
    """Names the model cannot know, as a correction table.

    The first attempt passed them to Whisper as an initial prompt
    (`prompt_ids`), which is the "official" way. Measured on the test call, it
    does two kinds of damage:

        without glossary   552 segments, 44 non-existent words (1.7%)
        with glossary      166 segments, 67 non-existent words (2.6%)

    The prompt destabilizes the model instead of guiding it: it sends it into
    long runs (segments collapse from 552 to 166) and makes it look for those
    names everywhere.

    So the correction happens AFTER, with a deterministic substitution that
    cannot touch the model. Format of `glossary.txt`:

        Right <- wrong, another wrong

    Matching ignores case and respects word boundaries: a name does not fire
    inside another word.
    """
    f = glossary_file()
    if not f.exists():
        return []
    rules = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if "<-" not in line:
            continue
        right, variants = line.split("<-", 1)
        for v in variants.split(","):
            v = v.strip()
            if v:
                rules.append((re.compile(rf"\b{re.escape(v)}\b", re.IGNORECASE),
                              right.strip()))
    return rules


def apply_glossary(segments, rules):
    """Applies the table, and says how many times it corrected what.

    A line whose text changes keeps its word timings: see realign().
    """
    done = {}
    for s in segments:
        before = s["text"]
        for rx, right in rules:
            new, n = rx.subn(right, s["text"])
            if n:
                s["text"] = new
                done[right] = done.get(right, 0) + n
        if s["text"] != before and s.get("words"):
            s["words"] = realign(s["words"], s["text"])
    return done


def realign(words, text):
    """Word timings for a line whose text was changed (glossary, or by hand).

    Words that stayed the same keep their times. A run of words replaced by
    another ("North pine" -> "Northpine") shares the time span of what it
    replaced; a word inserted where nothing was gets the instant between its
    neighbours. So a corrected line can still be clicked word by word, instead
    of losing every timing because one word changed.

    Invariant: the tokens returned, joined by spaces, are the new text.
    """
    new = text.split()
    if not words:
        return []
    old = [w[2] for w in words]
    m = difflib.SequenceMatcher(None, [w.lower() for w in old], [w.lower() for w in new],
                                autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                s, e, _ = words[i1 + k]
                out.append([s, e, new[j1 + k]])
        elif tag in ("replace", "insert") and j2 > j1:
            if tag == "replace":
                a, b = words[i1][0], words[i2 - 1][1]
            else:
                a = words[i1 - 1][1] if i1 > 0 else words[0][0]
                b = words[i1][0] if i1 < len(words) else a
            step = (b - a) / (j2 - j1)
            for k in range(j2 - j1):
                out.append([round(a + k * step, 2), round(a + (k + 1) * step, 2), new[j1 + k]])
    return out


# --- listening ------------------------------------------------------------------

DECODE = {
    "task": "transcribe",
    # Stops a repetition from dragging into the next window.
    "condition_on_prev_tokens": False,
    # If a window comes out badly, redo it "warmer" instead of keeping it.
    "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    # Too repetitive, or the model too unsure: discard and retry.
    "compression_ratio_threshold": 1.35,
    "logprob_threshold": -1.0,
    # Above this the window is silence: do not invent.
    "no_speech_threshold": 0.6,
}


def _code(language):
    """Detection reports a name ("italian"), a forced language is a code
    ("it"), OpenVINO a token ("<|it|>"): only codes are stored, so the page
    has one thing to show."""
    language = language.strip("<|>") if language else language
    if language and len(language) > 3:
        from transformers.models.whisper.tokenization_whisper import TO_LANGUAGE_CODE
        return TO_LANGUAGE_CODE.get(language.lower(), language)
    return language


def _decode(language):
    kwargs = dict(DECODE)
    if language:
        kwargs["language"] = language
    return kwargs


def listen(wav, language=None, speech_start=0.0, precise=False, speech=None):
    """The transcription, word by word. `language` is a Whisper code or None.

    Returns (words, language, breaks): words as [start, end, token]; breaks is
    the set of word positions where one of Whisper's own segments begins, or
    None when the lines are to be rebuilt from the words.

    Two ways, measured on the real 27-minute call:

                        time    non-existent words   word timings
        segments        200 s   29 of 2,504 (1.2%)   estimated inside each line
        precise words   395 s   29 of 2,500 (1.2%)   from Whisper's alignment

    Same quality, twice the time: precise timings need the attention weights,
    and that turns off the fast attention kernel. So the default keeps the
    speed and spreads each line's time over its words by their length, which
    lands a click near the word; `precise` is the choice when it has to land
    on it.

    With no language given, it is found first, from where people start
    speaking (a call often opens with silence), and the whole call is
    transcribed in it. `speech`, the map of where people speak, lets the
    OpenVINO engine skip a looped window of silence.
    """
    e = engine()
    if not language:
        language = detect_language(wav, speech_start)
    words, breaks = [], None
    if precise:
        try:
            words = e.words(wav, language)
        except Exception as x:                              # pragma: no cover
            print(f"  word timestamps failed ({type(x).__name__}): using segments")
            precise = False
    if not precise:
        words, breaks = spread(e.segments(wav, language, speech))
    return tidy(words), _code(language), breaks


def spread(chunks):
    """Words with estimated times, from Whisper's segments.

    Each segment's time is shared among its words by their length in
    characters: a long word takes longer to say than "a". Returns the words and
    the positions where a segment starts, so the lines stay Whisper's own.
    """
    words, breaks = [], set()
    for c in chunks:
        toks = c["text"].split()
        a, b = c["timestamp"]
        if not toks or a is None:
            continue
        b = b if b is not None and b > a else a + 0.4 * len(toks)
        total = sum(len(t) + 1 for t in toks)
        breaks.add(len(words))
        t = a
        for tok in toks:
            d = (b - a) * (len(tok) + 1) / total
            words.append([t, t + d, tok])
            t += d
    return words, breaks


def tidy(words):
    """Times that only go forward, and no word shorter than 50 ms.

    Whisper's alignment occasionally gives a word that starts before the
    previous one, or that lasts nothing: on the 27-minute call, 1 and 18 of
    2,753. A click must never jump backwards, nor land on an empty word.
    """
    out, last = [], 0.0
    for a, b, w in words:
        a = max(a, last)
        b = max(b, a + 0.05)
        out.append([round(a, 2), round(b, 2), w])
        last = a
    return out


def detect_language(wav, start=0.0):
    """The language Whisper hears in 30 seconds of audio, as a code, or None.

    Only one window: it is what Whisper itself uses to decide, and decoding the
    whole call again just to name its language would cost minutes.
    """
    try:
        import soundfile as sf
        audio, _ = sf.read(str(wav), dtype="float32",
                           start=int(start * 16000), frames=30 * 16000)
        return _code(engine().language(audio))
    except Exception:
        return None


ENDS_SENTENCE = re.compile(r"[.!?…]['\")\]]*$")


def lines_from_words(words, speakers=None, breaks=None, pause=1.0, longest=220):
    """The lines, from the words.

    With `breaks` (Whisper's segments), a line is one of Whisper's segments,
    split only where the speaker changes inside it.

    Without (precise word timings), the lines are rebuilt: a line ends at the
    end of a sentence, at a pause of a second or more, when the speaker
    changes, or when it grows past `longest` characters (at a comma if there
    is one in the last stretch). These are the places Whisper's own segments
    broke on the test call, so a transcript reads the same either way.
    """
    lines, cur, idx = [], [], []

    def flush():
        if cur:
            line = {"start": cur[0][0], "end": cur[-1][1],
                    "text": " ".join(w[2] for w in cur), "words": [list(w) for w in cur]}
            if speakers:
                line["speaker"] = speakers[idx[0]]
            lines.append(line)
            cur.clear()
            idx.clear()

    for i, w in enumerate(words):
        turn = bool(cur) and speakers is not None and speakers[i] != speakers[idx[0]]
        if breaks is not None:
            if cur and (i in breaks or turn):
                flush()
            cur.append(w)
            idx.append(i)
            continue
        if cur and (w[0] - cur[-1][1] >= pause or turn):
            flush()
        cur.append(w)
        idx.append(i)
        size = sum(len(x[2]) + 1 for x in cur)
        if (ENDS_SENTENCE.search(w[2]) and len(cur) >= 3) or size > longest * 1.4 \
                or (size > longest and w[2].endswith(",")):
            flush()
    flush()
    return lines


# --- two tracks: who speaks -------------------------------------------------------

def label_speakers(words, left, right, rate, window=0.08, breaks=None):
    """Me or Them for every word, from the energy of the two tracks.

    `left` is your microphone, `right` the call's audio, both mono arrays at
    `rate`. The call's track never contains your voice (the meeting app does
    not send it back to you), while your microphone may pick the others up
    faintly from the speakers. So each track is compared with its own typical
    loudness, and the word goes to the track that is more above its usual
    level.

    A single word that disagrees with both neighbours is smoothed over: one
    "yes" in the middle of someone else's sentence is more often bleed than a
    real interruption.

    With estimated word timings (`breaks`, Whisper's lines), a word's own
    time is a guess, and the guess is worst exactly where it matters: a line
    of Whisper that holds the end of one turn and the start of the next
    shares its time evenly, pause included, and the words at the change land
    on the wrong side. In a test call in Meet: "Parla | un po'", "Ciao, |
    come va?". So then each line's words are laid out, in order and by
    length, over the moments in that line when someone is actually speaking,
    and each takes the track that carries its moment. Measured on a public
    AMI meeting put on two tracks, words on the right side: 98.6% -> 99.0%,
    and with the others bleeding into the microphone at -25 dB, 98.1% ->
    98.9%. Keeping a lone word at the edge of a line with its line, as for
    voices, cost 0.4 points here: on two tracks a one-word reply is real.

    Tried and dropped: transcribing each track on its own. Every word is
    then on the right side by construction, but Whisper's times on a track
    that is silent half the time drift: on the call's side, the median word
    was 2.3 s away from where it was said, and lines came out of order.
    """
    import numpy as np
    if breaks:
        return _by_turns(words, breaks, left, right, rate)

    def energy(x, a, b):
        i, j = int(max(0, a - window) * rate), int((b + window) * rate)
        seg = x[i:max(j, i + 1)]
        return float(np.sqrt(np.mean(seg.astype(np.float64) ** 2))) if seg.size else 0.0

    me = [energy(left, w[0], w[1]) for w in words]
    them = [energy(right, w[0], w[1]) for w in words]
    ref_me = float(np.percentile(me, 90)) if me else 0.0
    ref_them = float(np.percentile(them, 90)) if them else 0.0
    if ref_me < 1e-4 and ref_them < 1e-4:
        return ["Them"] * len(words)
    if ref_me < 1e-4:
        return ["Them"] * len(words)       # a muted microphone
    if ref_them < 1e-4:
        return ["Me"] * len(words)         # nobody else spoke
    labels = ["Me" if m / ref_me > t / ref_them else "Them" for m, t in zip(me, them)]
    for i in range(1, len(labels) - 1):
        if labels[i - 1] == labels[i + 1] != labels[i]:
            labels[i] = labels[i - 1]
    return labels


def tell_voices(words, audio, speakers=None, progress=None, breaks=None):
    """Voice 1, Voice 2... for every word, and how many voices were found.

    `audio` is mono 16 kHz: the whole call, or only the call's side of a
    two-track recording, whose "Me" words are then left as they are. With a
    single voice nothing changes: one label on every line says nothing.
    """
    import numpy as np
    import voices
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    turns = voices.diarize(audio / peak * 0.9 if peak > 0 else audio, progress)
    found = len({t[2] for t in turns})
    if found < 2 or not words:
        return speakers, found
    keep = [s if s == "Me" else None for s in speakers] if speakers else None
    return voices.assign(words, turns, keep, breaks), found


# A track carries a voice where it is this far above its own background: 4x,
# 12 dB. Comparing each track with its usual level alone failed when you
# only listen: the microphone's usual level is then the room's hiss, so the
# hiss looked like speech next to the others' voice. A recording made from
# the computer with you silent went to "You" word for word, 31 of 31.
ABOVE_BACKGROUND = 4.0


def background(frames):
    """A track's background level: the quietest tenth of its moments."""
    import numpy as np
    return max(float(np.percentile(frames, 10)), 1e-5) if len(frames) else 1e-5


def _by_turns(words, breaks, left, right, rate, hop=0.02, floor=0.08):
    """label_speakers() with estimated word timings: see there."""
    import numpy as np
    n = max(1, int(rate * hop))

    def frames(x):
        m = len(x) // n
        return np.sqrt((x[:m * n].astype(np.float64).reshape(m, n) ** 2).mean(1))

    L, R = frames(left), frames(right)
    m = min(len(L), len(R))
    L, R = L[:m], R[:m]
    ref_me, ref_them = float(np.percentile(L, 90)) if m else 0.0, float(np.percentile(R, 90)) if m else 0.0
    if ref_me < 1e-4:
        return ["Them"] * len(words)       # a muted microphone
    if ref_them < 1e-4:
        return ["Me"] * len(words)         # nobody else spoke
    l, r = L / ref_me, R / ref_them
    heard_me = L > ABOVE_BACKGROUND * background(L)
    heard_them = R > ABOVE_BACKGROUND * background(R)
    # each moment: nobody (-1), you (0), the call (1). A track only wins a
    # moment it is heard in; heard in both, the one more above its usual level.
    me_wins = heard_me & (~heard_them | (l > r))
    them_wins = heard_them & ~me_wins
    side = np.where(np.maximum(l, r) < floor, -1, np.where(me_wins, 0, np.where(them_wins, 1, -1)))
    starts = sorted(set(breaks) | {len(words)})
    out = []
    for a, b in zip(starts, starts[1:]):
        ws = words[a:b]
        if not ws:
            continue
        f0 = int(ws[0][0] / hop)
        f1 = max(int(ws[-1][1] / hop), f0 + 1)
        voiced = side[f0:f1]
        voiced = voiced[voiced >= 0]
        if not len(voiced):
            out += ["Me" if l[f0:f1].sum() > r[f0:f1].sum() else "Them"] * len(ws)
            continue
        chars = np.array([len(w[2]) + 1 for w in ws], float)
        centre = (np.cumsum(chars) - chars / 2) / chars.sum()
        out += ["Me" if voiced[min(len(voiced) - 1, int(c * len(voiced)))] == 0 else "Them"
                for c in centre]
    for i in range(1, len(out) - 1):
        if out[i - 1] == out[i + 1] != out[i]:
            out[i] = out[i - 1]
    return out


def read_two_tracks(source, rate=16000):
    """The two tracks of a recording as two arrays: (microphone, call, rate)."""
    import soundfile as sf
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "stereo.wav"
        subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                        "-ac", "2", "-ar", str(rate), "-c:a", "pcm_s16le", str(wav)], check=True)
        data, sr = sf.read(str(wav), dtype="float32")
    return data[:, 0], data[:, 1], sr


# --- reading ----------------------------------------------------------------------

def mmss(s) -> str:
    s = int(s or 0)
    return f"{s//60:02d}:{s%60:02d}"


def paragraphs(segments, pause=2.0, longest=700):
    """Joins lines into paragraphs: a break on a pause, a change of speaker, or
    when it gets long.

    Whisper cuts wherever suits it, often mid-sentence. Reading needs the
    opposite: blocks that end where a thought ends.
    """
    out, buf, words, start, last, who = [], [], [], None, None, None

    def flush():
        if buf:
            p = {"start": start, "text": " ".join(buf)}
            if who:
                p["speaker"] = who
            # Words travel with the paragraph only if every line has them:
            # a half-timed paragraph would make some words clickable and
            # others not, for no reason the reader can see.
            if words and all(w is not None for w in words):
                p["words"] = [x for w in words for x in w]
            out.append(p)

    for s in segments:
        if start is None:
            start = s["start"]
        gap = last is not None and s["start"] is not None and (s["start"] - last) >= pause
        turn = s.get("speaker") != who and bool(buf)
        if buf and (gap or turn or sum(len(x) for x in buf) > longest):
            flush()
            buf, words, start = [], [], s["start"]
        buf.append(s["text"])
        words.append(s.get("words"))
        who = s.get("speaker")
        last = s["end"] if s.get("end") is not None else last
    flush()
    return out


def mean_volume(wav, start, duration=3.0):
    """The mean level of a short piece of audio, in dB."""
    r = subprocess.run(
        [ffmpeg(), "-hide_banner", "-ss", f"{max(0.0, start):.2f}",
         "-t", f"{duration:.2f}", "-i", str(wav),
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0])
            except ValueError:
                break
    return 0.0


# How far below the speech level a stretch must be to count as silent. On the
# test call the three places where Whisper invented were at -43.9, -64.5 and
# -41.3 dB against speech at -24.3: between 17 and 40 dB below. The threshold
# is 12 and not 15 because at 15 the third one passed by 1.3 dB, too thin a
# margin: moving the measuring window by half a second changed the outcome.
BELOW_SPEECH = 12.0


def speech_level(wav, speech):
    """How loud the audio is WHERE SOMEONE IS SPEAKING.

    The mean of the whole file is the wrong reference: it includes all the
    silence and is pulled down, so the threshold becomes lenient and a phantom
    at -41 dB gets through. Measuring only where there is speech, the
    comparison becomes "this piece is much quieter than when people talk",
    which is the real question.
    """
    if not speech:
        return mean_volume(wav, 0, 10_000)
    sel = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in speech[:400])
    r = subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(wav),
         "-af", f"aselect='{sel}',volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].split("dB")[0])
            except ValueError:
                break
    return mean_volume(wav, 0, 10_000)


def drop_phantoms(segments, wav, level, volume=None):
    """Drops the subtitle phrases spoken where there was no sound.

    Two conditions together, and both are needed:

      the text is one of the phrases Whisper learned from YouTube subtitles
      ("Thanks for watching", "Subtitles by...")

      and at that point the audio is much quieter than the rest of the call

    The second makes the first safe: a "thank you all" really said falls where
    someone is speaking, at normal volume, and stays. Deleting on the text
    alone would mean removing real words.

    The volume is measured instead of asking `silencedetect`, because that one
    reasons in silent stretches of a minimum length, and a crackle in the
    middle breaks its count: on the test call it reported "100% speech" at a
    point measuring -43.9 dB. The level is a fact; the length of a silence is
    an inference.

    Modifies `segments` in place and returns the dropped ones: the reader has
    to know. A silent deletion is worse than a visible mistake.
    """
    volume = volume or mean_volume
    dropped, kept = [], []
    for s in segments:
        if (any(p in s["text"].lower() for p in SUBTITLE_PHRASES)
                and s["start"] is not None
                and volume(wav, s["start"]) < level - BELOW_SPEECH):
            dropped.append(s)
        else:
            kept.append(s)
    segments[:] = kept
    return dropped


def suspicious(segments):
    """Subtitle phrases that survived: worth a look, not worth trusting."""
    return [s for s in segments
            if any(p in s["text"].lower() for p in SUBTITLE_PHRASES)]


# --- the .txt format, and the others ----------------------------------------------
#
#   [mm:ss] text                    a line
#   [mm:ss] [Me] text               a line of a call recorded on two tracks
#   [mm:ss] [Voice 2] text          a line, with the voices told apart
#
# Names given to the voices are kept in info.json, never in the .txt: renaming
# "Voice 2" must not mean rewriting every line, and a name can be changed back.
#
# The .txt is the source everything else is rebuilt from, and stays readable in
# any editor. Word timings live next to it, in words.json.

LINE = re.compile(r"^\[(\d+):(\d+)\]\s*(?:\[(" + TAG + r")\]\s*)?(.*)$")
PREFIX = re.compile(r"^(\[\d+:\d+\]\s*(?:\[(?:" + TAG + r")\]\s*)?)(.*)$")


def parse_line(line):
    """(seconds, speaker or None, text) for a .txt line, or None."""
    m = LINE.match(line)
    if not m or not m[4].strip():
        return None
    return int(m[1]) * 60 + int(m[2]), m[3], m[4].strip()


def who(s, names=None):
    """The speaker of a line as a reader should see it: the name, if given."""
    sp = s.get("speaker")
    return (names or {}).get(sp) or sp


def as_txt(segments, names=None) -> str:
    return "".join(f"[{mmss(s['start'])}] " + (f"[{who(s, names)}] " if s.get("speaker") else "")
                   + f"{s['text']}\n" for s in segments)


def as_md(segments, title, seconds, names=None) -> str:
    words = sum(len(s["text"].split()) for s in segments)
    lines = [f"# {title}\n",
             f"*{seconds/60:.0f} min · {words} words · "
             f"transcribed locally with {MODEL}*\n"]
    for p in paragraphs(segments):
        by = f" · {who(p, names)}" if p.get("speaker") else ""
        lines.append(f"**{mmss(p['start'])}{by}** — {p['text']}\n")
    return "\n".join(lines)


def ends(segments, duration):
    """An end for every line, for subtitles.

    From the word timings when there are any. Otherwise estimated: a line lasts
    about as long as it takes to say (0.4 s a word, plus half a second), but
    never past the start of the next line. Using the next start alone would
    keep a subtitle on screen through every silence.
    """
    out = []
    for i, s in enumerate(segments):
        if s.get("words"):
            e = s["words"][-1][1]
        else:
            nxt = segments[i + 1]["start"] if i + 1 < len(segments) else duration
            e = min(nxt, s["start"] + 0.5 + 0.4 * len(s["text"].split()))
        out.append(max(e, s["start"] + 0.3))
    return out


def _stamp(t, sep):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def as_srt(segments, duration, names=None) -> str:
    out = []
    for i, (s, e) in enumerate(zip(segments, ends(segments, duration)), 1):
        by = f"{who(s, names)}: " if s.get("speaker") else ""
        out.append(f"{i}\n{_stamp(s['start'], ',')} --> {_stamp(e, ',')}\n{by}{s['text']}\n")
    return "\n".join(out)


def as_vtt(segments, duration, names=None) -> str:
    out = ["WEBVTT\n"]
    for s, e in zip(segments, ends(segments, duration)):
        by = f"<v {who(s, names)}>" if s.get("speaker") else ""
        out.append(f"{_stamp(s['start'], '.')} --> {_stamp(e, '.')}\n{by}{s['text']}\n")
    return "\n".join(out)


def as_json(segments, duration, names=None, **meta) -> str:
    lines = []
    for s, e in zip(segments, ends(segments, duration)):
        item = {"start": s["start"], "end": round(e, 2), "text": s["text"]}
        if s.get("speaker"):
            item["speaker"] = who(s, names)
        if s.get("words"):
            item["words"] = [{"start": a, "end": b, "word": w} for a, b, w in s["words"]]
        lines.append(item)
    return json.dumps({**meta, "duration": duration, "lines": lines}, ensure_ascii=False, indent=1)


FORMATS = {"txt", "md", "srt", "vtt", "json"}


def render(fmt, segments, title, duration, names=None, **meta) -> str:
    """A transcript in one of FORMATS. `names` maps a speaker tag to a name."""
    if fmt == "txt":
        return as_txt(segments, names)
    if fmt == "md":
        return as_md(segments, title, duration, names)
    if fmt == "srt":
        return as_srt(segments, duration, names)
    if fmt == "vtt":
        return as_vtt(segments, duration, names)
    if fmt == "json":
        return as_json(segments, duration, names, title=title, **meta)
    raise ValueError(f"unknown format {fmt!r}: choose from {', '.join(sorted(FORMATS))}")


# --- the whole job ------------------------------------------------------------------

def run(source, language=None, progress=None, two_tracks=False, precise=False, voices=False):
    """From a file to lines. `progress(stage, seconds_to_transcribe)` for the page.

    Returns a dict: segments (lines with words, and speaker for two tracks or
    voices), seconds, speech_seconds, corrected (name -> count), phantoms,
    speech (the map), language, word_times, and speakers_found when the voices
    were told apart.
    """
    source = pathlib.Path(source)
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "audio.wav"
        if progress:
            progress("preparing the audio", 0)
        seconds = prepare(source, wav, two_tracks)

        # The map of silence is for cleaning up AFTER, not for cutting before.
        #
        # Cutting the silence and giving Whisper the compacted audio does
        # remove the hallucinations, but makes the words worse. Measured on
        # the test call: from 31 non-existent words to 42 removing all the
        # silence, and to 47 removing only pauses over 3 seconds. It is not the
        # number of joins that does the damage, it is the cut itself: silence
        # tells Whisper where words end.
        #
        # So: the whole audio goes to the model, and afterwards the subtitle
        # phrases are dropped ONLY where nobody was speaking. Zero
        # hallucinations, at no cost in words.
        meter = pathlib.Path(tmp) / "levels.wav"
        level_copy(source, meter, two_tracks)
        speech = speech_regions(meter, seconds)
        speech_s = sum(b - a for a, b in speech) if speech else seconds
        level = speech_level(meter, speech)

        if not loaded():
            # Ten seconds or so, minutes the very first time: said, so the
            # page doesn't look stuck.
            if progress:
                progress("loading the model" if downloaded() else "downloading the model", seconds)
            engine()
        if progress:
            progress("transcribing", seconds)
        # Timed for the page's next estimate (speed()): what the user waits
        # for once the model is loaded, without telling voices apart.
        t0 = time.time()
        words, used, breaks = listen(wav, language, speech[0][0] if speech else 0.0, precise, speech)

        speakers = None
        if two_tracks and words:
            if progress:
                progress("telling the two voices apart", seconds)
            left, right, rate = read_two_tracks(source)
            speakers = label_speakers(words, left, right, rate, breaks=breaks)

        found = None
        if voices and words:
            if two_tracks:
                audio = right
            else:
                import soundfile as sf
                audio, _ = sf.read(str(wav), dtype="float32")
            t1 = time.time()
            speakers, found = tell_voices(words, audio, speakers, progress, breaks)
            t0 += time.time() - t1

        segments = lines_from_words(words, speakers, breaks)
        phantoms = drop_phantoms(segments, meter, level)
        busy = time.time() - t0

    # Proper nouns are fixed here, on the output: see glossary().
    corrected = apply_glossary(segments, glossary())
    out = {"segments": segments, "seconds": seconds, "speech_seconds": speech_s,
           "corrected": corrected, "phantoms": phantoms, "speech": speech,
           "language": used, "word_times": "precise" if breaks is None else "estimated",
           "transcribing_seconds": round(busy, 1), "engine": key(precise)}
    if found is not None:
        out["speakers_found"] = found
    return out


def speech_map(source):
    """Where people speak, measured on the audio.

    It cannot be derived from the text: the .txt only stores where each line
    starts, so for transcripts made before word timings were kept, lines touch
    by construction and every call would look spoken from the first second to
    the last. Silence lives in the audio, and is measured there.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "levels.wav"
        level_copy(source, wav)
        import soundfile as sf
        info = sf.info(str(wav))
        return speech_regions(wav, info.frames / info.samplerate)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe a recording locally with Whisper large-v3.")
    ap.add_argument("file", nargs="?", help="audio or video file")
    ap.add_argument("--where", action="store_true",
                    help="say where Whisper runs on this computer, and stop")
    ap.add_argument("--language", default=None,
                    help='Whisper language code, e.g. "it" or "en" (default: detect)')
    ap.add_argument("--formats", default="txt,md",
                    help="comma separated, from: txt, md, srt, vtt, json (default: txt,md)")
    ap.add_argument("--precise", action="store_true",
                    help="precise word timings: twice as slow (default: estimated)")
    ap.add_argument("--two-tracks", action="store_true",
                    help="stereo recording: your microphone left, the call right")
    ap.add_argument("--voices", action="store_true",
                    help="tell the voices apart: Voice 1, Voice 2... (about 2 s a minute, on the CPU)")
    args = ap.parse_args()
    if args.where:
        names = [f"{PATHS[p]} ({'OpenVINO' if program(p) == 'openvino' else 'PyTorch'})" for p in found()]
        print(f"  Whisper large-v3 runs on: {names[0]}" + (f"; also possible: {', '.join(names[1:])}" if names[1:] else ""))
        return
    if not args.file:
        ap.error("the file to transcribe is missing")

    source = pathlib.Path(args.file).expanduser()
    if not source.exists():
        raise SystemExit(f"File not found: {source}")
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    unknown = set(formats) - FORMATS
    if unknown:
        raise SystemExit(f"Unknown format: {', '.join(sorted(unknown))}")

    print(f"\n  {source.name}")
    t0 = time.time()
    r = run(source, args.language, lambda stage, s: print(f"  {stage}...", flush=True),
            two_tracks=args.two_tracks, precise=args.precise, voices=args.voices)
    dt = time.time() - t0
    segments = r["segments"]

    for fmt in formats:
        source.with_suffix(f".{fmt}").write_text(
            render(fmt, segments, source.stem, r["seconds"], language=r["language"]),
            encoding="utf-8")

    words = sum(len(s["text"].split()) for s in segments)
    print(f"\n  done in {dt:.0f} s   ({r['seconds']/dt:.0f}x real time)   "
          f"language: {r['language'] or '?'}")
    if r["phantoms"]:
        print(f"  dropped {len(r['phantoms'])} subtitle phrases that fell on silence:")
        for s in r["phantoms"]:
            print(f"     [{mmss(s['start'])}] {s['text']}")
    if r["corrected"]:
        print("  names corrected: " +
              ", ".join(f"{k} ({v}x)" for k, v in r["corrected"].items()))
    if "speakers_found" in r:
        print(f"  voices: {r['speakers_found']}")
    print(f"  {words} words\n")
    for fmt in formats:
        print(f"  {source.with_suffix('.' + fmt).name}")

    left = suspicious(segments)
    if left:
        print("\n  Worth a look: phrases Whisper tends to invent on silence")
        for s in left:
            print(f"     [{mmss(s['start'])}] {s['text']}")
    print()


if __name__ == "__main__":
    main()
