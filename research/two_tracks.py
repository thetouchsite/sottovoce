"""Who said each word on a call recorded on two tracks, measured where the answer is known.

    python research/two_tracks.py              the held-out meeting
    python research/two_tracks.py --tune       the meeting to tune on

A call recorded from the page has your microphone on one track and the
call's audio on the other. AMI meetings (CC BY 4.0) were recorded with a
headset microphone on every person, so they make real two-track calls: one
person's headset on the left, the other people's headsets on the right. The
left track then carries what a real microphone carries, the others heard
faintly across the room. Two setups:

    headset     as recorded
    speakers    the right track also leaks into the left at -25 dB, as when
                the call plays from loudspeakers instead of headphones

and calls of 2, 3 and 4 people (the most talkative ones; "you" is the
person who talks most).

The score is the share of words on the right side (yours or the others'),
over the words said where only one person was speaking, by the annotated
turns. Lines are counted too: a method that splits every line in two would
score well and read badly.

The meetings are downloaded once into research/ami/ (about 130 MB each).
Whisper runs on the GPU: a meeting takes a few minutes per setup.

Needs: pip install -r requirements.txt (the engine), scipy
"""
import argparse
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.request

import numpy as np
import soundfile as sf

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import transcribe as T                                  # noqa: E402
from voices_ami import DATA, MEETINGS, fetch, reference  # noqa: E402

HEADSET = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/{m}/audio/{m}.Headset-{i}.wav"
RATE = 16000


def download(url, dest, tries=6):
    """The mirror refuses (403) downloads that come too close together: wait and retry."""
    for k in range(tries):
        try:
            print(f"  downloading {dest.name}", flush=True)
            part = dest.with_suffix(".part")
            urllib.request.urlretrieve(url, part)
            part.rename(dest)
            time.sleep(5)
            return
        except urllib.error.HTTPError as e:
            if e.code != 403 or k == tries - 1:
                raise
            wait = 30 * 2 ** k
            print(f"  the mirror says 403, waiting {wait} s", flush=True)
            time.sleep(wait)


def headsets(m):
    """The four headset tracks of a meeting, each matched to its person."""
    fetch(m)
    tracks = []
    for i in range(4):
        f = DATA / f"{m}.Headset-{i}.wav"
        if not f.exists():
            download(HEADSET.format(m=m, i=i), f)
        x, rate = sf.read(str(f), dtype="float32")
        assert rate == RATE
        tracks.append(x if x.ndim == 1 else x.mean(axis=1))
    n = min(len(x) for x in tracks)
    tracks = [x[:n] for x in tracks]
    ref = reference(m)
    people = sorted({s for _, _, s in ref})
    # Which headset is whose: the one loudest while that person speaks alone.
    hop = RATE // 50
    energy = [np.sqrt((x[:n // hop * hop].reshape(-1, hop).astype(np.float64) ** 2).mean(1))
              for x in tracks]
    score = np.zeros((len(people), 4))
    for a, b, s in ref:
        alone = not any(o != s and oa < b and ob > a for oa, ob, o in ref)
        if alone:
            i, j = int(a * 50), int(b * 50)
            score[people.index(s)] += [e[i:j].sum() for e in energy]
    from scipy.optimize import linear_sum_assignment
    rows, cols = linear_sum_assignment(-score)
    return {people[r]: tracks[c] for r, c in zip(rows, cols)}, ref


def call(by_person, ref, n, setup):
    """A two-track call of the n most talkative people: (left, right, you, people)."""
    talk = {}
    for a, b, s in ref:
        talk[s] = talk.get(s, 0) + b - a
    people = sorted(talk, key=lambda s: -talk[s])[:n]
    you = people[0]
    left = by_person[you].copy()
    right = np.sum([by_person[p] for p in people[1:]], axis=0)
    if setup == "speakers":
        left = left + right * 10 ** (-25 / 20)
    peak = max(np.abs(left).max(), np.abs(right).max()) or 1
    return left / peak * 0.9, right / peak * 0.9, you, people


def current(stereo, language):
    """The engine as it is: the tracks mixed, each word to the track speaking then."""
    r = T.run(stereo, language, two_tracks=True)
    return r["segments"]


METHODS = {"current": current}


def grade(segments, ref, you, people):
    def side(t):
        who = {s for a, b, s in ref if a <= t < b and s in people}
        others = {s for a, b, s in ref if a <= t < b and s not in people}
        if len(who) != 1 or others:
            return None
        return "Me" if you in who else "Them"
    pairs = [(side((w[0] + w[1]) / 2), s.get("speaker")) for s in segments for w in s.get("words") or []]
    known = [(a, b) for a, b in pairs if a]
    return sum(a == b for a, b in known) / max(1, len(known)), len(known), len(pairs), len(segments)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true", help="the meeting to tune on, not the held-out one")
    ap.add_argument("--method", default="current", choices=sorted(METHODS))
    args = ap.parse_args()
    m = "ES2004a" if args.tune else "IS1009a"
    by_person, ref = headsets(m)
    print(f"\n  {m}, {'tuning' if args.tune else 'held out'}, method: {args.method}\n")
    print("  people  setup      right side   words graded   words   lines   seconds")
    for setup in ("headset", "speakers"):
        for n in (2, 3, 4):
            left, right, you, people = call(by_person, ref, n, setup)
            with tempfile.TemporaryDirectory() as tmp:
                stereo = pathlib.Path(tmp) / "call.wav"
                sf.write(str(stereo), np.stack([left, right], 1), RATE)
                t0 = time.time()
                segments = METHODS[args.method](stereo, "en")
                secs = time.time() - t0
            acc, graded, words, lines = grade(segments, ref, you, people)
            print(f"  {n:>6}  {setup:9}  {acc:10.1%}   {graded:>12}   {words:>5}   {lines:>5}   {secs:7.0f}",
                  flush=True)
    print()


if __name__ == "__main__":
    main()
