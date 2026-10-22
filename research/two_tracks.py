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

Methods: "current" is the engine as it is; "per_track" transcribes each
track alone, in the pieces where its person speaks (see the roadmap).

The score is the share of words on the right side (yours or the others'),
over the words said where only one person was speaking, by the annotated
turns. Lines are counted too: a method that splits every line in two would
score well and read badly. And words that fall where nobody was speaking
(half a second either way) are counted as invented.

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


def pieces(mine, other, rate, hop=0.02, floor=0.08, gap=0.8, pad=0.3, shortest=0.4, longest=28.0):
    """Where a track's own person speaks: loud for that track, and louder
    than the other track, relative to each track's own loud parts. The
    second condition is what keeps the others' voices, heard faintly in
    your microphone, out of your pieces."""
    n = int(rate * hop)
    def frames(x):
        m = len(x) // n
        return np.sqrt((x[:m * n].astype(np.float64).reshape(m, n) ** 2).mean(1))
    a, b = frames(mine), frames(other)
    k = min(len(a), len(b))
    a, b = a[:k] / (np.percentile(a[:k], 90) or 1e-9), b[:k] / (np.percentile(b[:k], 90) or 1e-9)
    on = (a > floor) & (a > b)
    out, start, last = [], None, None
    for i in np.nonzero(on)[0]:
        t = i * hop
        if start is None:
            start = last = t
        elif t - last > gap:
            out.append((start, last + hop)); start = t
        last = t
    if start is not None:
        out.append((start, last + hop))
    res = []
    for s, e in out:
        voiced = on[int(s / hop):int(e / hop)].sum() * hop
        if voiced < shortest:          # a breath, a click: Whisper invents on those
            continue
        s, e = max(0.0, s - pad), min(len(mine) / rate, e + pad)
        while e - s > longest:
            res.append((s, s + longest)); s += longest
        res.append((s, e))
    return res


def per_track(stereo, language):
    """Each track transcribed alone, only in the pieces where its person
    speaks, each piece at its own time: every word on its side by
    construction."""
    left, right, rate = T.read_two_tracks(stereo)
    p = T.engine()
    kw = dict(T.DECODE)
    kw["language"] = language
    lines = []
    for who, mine, other in (("Me", left, right), ("Them", right, left)):
        cuts = pieces(mine, other, rate)
        clips = []
        for s, e in cuts:
            c = mine[int(s * rate):int(e * rate)].astype(np.float32)
            clips.append({"raw": c / (np.abs(c).max() or 1) * 0.9, "sampling_rate": rate})
        results = p(clips, batch_size=8, return_timestamps=True, generate_kwargs=kw) if clips else []
        for (s, e), r in zip(cuts, results):
            chunks = [{"text": c["text"], "timestamp": (s + (c["timestamp"][0] or 0.0),
                       s + (c["timestamp"][1] if c["timestamp"][1] is not None else e - s))}
                      for c in r.get("chunks", [])]
            words, breaks = T.spread(chunks)
            part = T.lines_from_words(T.tidy(words), [who] * len(words), breaks)
            lines += [l for l in part if not T.suspicious([l])]
    lines.sort(key=lambda l: l["start"])
    return lines


METHODS = {"current": current, "per_track": per_track}


def grade(segments, ref, you, people):
    def side(t):
        who = {s for a, b, s in ref if a <= t < b and s in people}
        others = {s for a, b, s in ref if a <= t < b and s not in people}
        if len(who) != 1 or others:
            return None
        return "Me" if you in who else "Them"
    pairs = [(side((w[0] + w[1]) / 2), s.get("speaker")) for s in segments for w in s.get("words") or []]
    known = [(a, b) for a, b in pairs if a]
    # Words where nobody was speaking, give or take half a second: invented.
    def anyone(t):
        return any(a - 0.5 <= t <= b + 0.5 for a, b, _ in ref)
    invented = sum(1 for s in segments for w in s.get("words") or [] if not anyone((w[0] + w[1]) / 2))
    return (sum(a == b for a, b in known) / max(1, len(known)), len(known), len(pairs), len(segments),
            invented)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true", help="the meeting to tune on, not the held-out one")
    ap.add_argument("--method", default="current", choices=sorted(METHODS))
    args = ap.parse_args()
    m = "ES2004a" if args.tune else "IS1009a"
    by_person, ref = headsets(m)
    print(f"\n  {m}, {'tuning' if args.tune else 'held out'}, method: {args.method}\n")
    print("  people  setup      right side   words graded   words   invented   lines   seconds")
    for setup in ("headset", "speakers"):
        for n in (2, 3, 4):
            left, right, you, people = call(by_person, ref, n, setup)
            with tempfile.TemporaryDirectory() as tmp:
                stereo = pathlib.Path(tmp) / "call.wav"
                sf.write(str(stereo), np.stack([left, right], 1), RATE)
                t0 = time.time()
                segments = METHODS[args.method](stereo, "en")
                secs = time.time() - t0
            acc, graded, words, lines, invented = grade(segments, ref, you, people)
            print(f"  {n:>6}  {setup:9}  {acc:10.1%}   {graded:>12}   {words:>5}   {invented:>8}   "
                  f"{lines:>5}   {secs:7.0f}", flush=True)
    print()


if __name__ == "__main__":
    main()
