"""The engine: from a recording to text. Used by the server and from the command line.

    python transcribe.py "C:\\path\\Client call.mp4" [--language it]

Takes anything ffmpeg can read (mp4, m4a, mp3, wav, opus, 3gp) and writes a
.txt with timestamps and a .md in paragraphs next to the original.

The three choices inside are not taste. They were measured on 22 October 2026
on a real 27-minute business call recorded with a phone. If you change this
file, know what you would break.

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

HALLUCINATIONS ON SILENCE: Whisper learned from YouTube subtitles and, on
silent stretches, writes "Thanks for watching", "Subtitles by...". They are
dropped only when two things are both true: the text is one of those phrases,
and the audio at that point is far below the level of speech. See
drop_phantoms().
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import tempfile
import threading
import time

MODEL = "openai/whisper-large-v3"

# How much faster than real time. Used to tell the page how long is left.
#
# 7 and not 10: transcription alone runs at 10x (27 minutes in 168 seconds),
# but the user also waits for the upload and the audio conversion. End to end,
# measured on the same call: 27 minutes in 233 seconds. The estimate must say
# how long the person waits, not how long the GPU works.
SPEED = 7.0

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

ROOT = pathlib.Path(__file__).resolve().parent

_engine = None
_lock = threading.Lock()


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def engine():
    """The pipeline, loaded once and kept in VRAM.

    Loading it takes about twenty seconds: inside the server that is paid once
    at startup and never again. From the command line it is paid for every
    file, which is why the server is worth it for more than one.
    """
    global _engine
    with _lock:
        if _engine is None:
            import torch
            from transformers import pipeline
            _engine = pipeline(
                "automatic-speech-recognition", model=MODEL,
                dtype=torch.float16,
                device="cuda" if torch.cuda.is_available() else "cpu",
                model_kwargs={"attn_implementation": "sdpa"})
        return _engine


def prepare(source, dest) -> float:
    """16 kHz mono at a uniform loudness: what the model expects."""
    subprocess.run(
        [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
        check=True)
    import soundfile as sf
    info = sf.info(str(dest))
    return info.frames / info.samplerate


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
    """Applies the table, and says how many times it corrected what."""
    done = {}
    for s in segments:
        for rx, right in rules:
            new, n = rx.subn(right, s["text"])
            if n:
                s["text"] = new
                done[right] = done.get(right, 0) + n
    return done


def listen(wav, language=None):
    """The transcription. `language` is a Whisper code ("it", "en") or None to detect it.

    Returns the segments and the language actually used.
    """
    p = engine()
    kwargs = {
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
    if language:
        kwargs["language"] = language
    r = p(str(wav), return_timestamps=True, return_language=True,
          generate_kwargs=kwargs)
    chunks = r.get("chunks", [])
    used = language or next((c.get("language") for c in chunks if c.get("language")), None)
    # Detection reports a name ("italian"), a forced language is a code ("it"):
    # store codes only, so the page has one thing to show.
    if used and len(used) > 3:
        from transformers.models.whisper.tokenization_whisper import TO_LANGUAGE_CODE
        used = TO_LANGUAGE_CODE.get(used.lower(), used)
    return ([{"start": c["timestamp"][0], "end": c["timestamp"][1],
              "text": c["text"].strip()}
             for c in chunks if c["text"].strip()],
            used)


def mmss(s) -> str:
    s = int(s or 0)
    return f"{s//60:02d}:{s%60:02d}"


def paragraphs(segments, pause=2.0, longest=700):
    """Joins segments into paragraphs: a break on a pause, or when it gets long.

    Whisper cuts wherever suits it, often mid-sentence. Reading needs the
    opposite: blocks that end where a thought ends.
    """
    out, buf, start, last = [], [], None, None
    for s in segments:
        if start is None:
            start = s["start"]
        gap = last is not None and s["start"] is not None and (s["start"] - last) >= pause
        if buf and (gap or sum(len(x) for x in buf) > longest):
            out.append({"start": start, "text": " ".join(buf)})
            buf, start = [], s["start"]
        buf.append(s["text"])
        last = s["end"] if s["end"] is not None else last
    if buf:
        out.append({"start": start, "text": " ".join(buf)})
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


def drop_phantoms(segments, wav, level):
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
    dropped, kept = [], []
    for s in segments:
        if (any(p in s["text"].lower() for p in SUBTITLE_PHRASES)
                and s["start"] is not None
                and mean_volume(wav, s["start"]) < level - BELOW_SPEECH):
            dropped.append(s)
        else:
            kept.append(s)
    segments[:] = kept
    return dropped


def suspicious(segments):
    """Subtitle phrases that survived: worth a look, not worth trusting."""
    return [s for s in segments
            if any(p in s["text"].lower() for p in SUBTITLE_PHRASES)]


def as_txt(segments) -> str:
    return "".join(f"[{mmss(s['start'])}] {s['text']}\n" for s in segments)


def as_md(segments, title, seconds) -> str:
    words = sum(len(s["text"].split()) for s in segments)
    lines = [f"# {title}\n",
             f"*{seconds/60:.0f} min · {words} words · "
             f"transcribed locally with {MODEL}*\n"]
    for p in paragraphs(segments):
        lines.append(f"**{mmss(p['start'])}** — {p['text']}\n")
    return "\n".join(lines)


def run(source, language=None, progress=None):
    """From a file to segments. `progress(stage, seconds_to_transcribe)` for the page.

    Returns (segments, seconds, speech_seconds, names_corrected, phantoms,
    speech, language).
    """
    source = pathlib.Path(source)
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "audio.wav"
        if progress:
            progress("preparing the audio", 0)
        seconds = prepare(source, wav)

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
        speech = speech_regions(wav, seconds)
        speech_s = sum(b - a for a, b in speech) if speech else seconds
        level = speech_level(wav, speech)

        if progress:
            progress("transcribing", seconds)
        segments, used = listen(wav, language)
        phantoms = drop_phantoms(segments, wav, level)

    # Proper nouns are fixed here, on the output: see glossary().
    corrected = apply_glossary(segments, glossary())
    return segments, seconds, speech_s, corrected, phantoms, speech, used


def speech_map(source):
    """Where people speak, measured on the audio.

    It cannot be derived from the text: the .txt only stores where each line
    starts, the end is taken from the start of the next one, so lines touch by
    construction and every call would look spoken from the first second to the
    last. Silence lives in the audio, and is measured there.
    """
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "audio.wav"
        seconds = prepare(source, wav)
        return speech_regions(wav, seconds)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe a recording locally with Whisper large-v3.")
    ap.add_argument("file", help="audio or video file")
    ap.add_argument("--language", default=None,
                    help='Whisper language code, e.g. "it" or "en" (default: detect)')
    args = ap.parse_args()

    source = pathlib.Path(args.file).expanduser()
    if not source.exists():
        raise SystemExit(f"File not found: {source}")

    print(f"\n  {source.name}")
    t0 = time.time()
    segments, seconds, _, corrected, phantoms, _, used = run(
        source, args.language, lambda stage, s: print(f"  {stage}...", flush=True))
    dt = time.time() - t0

    source.with_suffix(".txt").write_text(as_txt(segments), encoding="utf-8")
    source.with_suffix(".md").write_text(
        as_md(segments, source.stem, seconds), encoding="utf-8")

    words = sum(len(s["text"].split()) for s in segments)
    print(f"\n  done in {dt:.0f} s   ({seconds/dt:.0f}x real time)   language: {used or '?'}")
    if phantoms:
        print(f"  dropped {len(phantoms)} subtitle phrases that fell on silence:")
        for s in phantoms:
            print(f"     [{mmss(s['start'])}] {s['text']}")
    if corrected:
        print("  names corrected: " +
              ", ".join(f"{k} ({v}x)" for k, v in corrected.items()))
    print(f"  {words} words\n")
    print(f"  {source.with_suffix('.txt').name}   with timestamps")
    print(f"  {source.with_suffix('.md').name}    to read")

    left = suspicious(segments)
    if left:
        print("\n  Worth a look: phrases Whisper tends to invent on silence")
        for s in left:
            print(f"     [{mmss(s['start'])}] {s['text']}")
    print()


if __name__ == "__main__":
    main()
