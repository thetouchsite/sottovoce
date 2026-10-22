"""How well voices are told apart, measured on public meetings with every speaker annotated.

    python research/voices_ami.py              the table in the README
    python research/voices_ami.py --sweep      every threshold, on the tuning meeting

Two AMI meetings (CC BY 4.0), downloaded once into research/ami/:

    ES2004a   used to choose the threshold
    IS1009a   used to grade it, and never looked at while choosing

Each meeting has four people. To also test three and two, the quietest
people are muted where they speak alone: the call then really has three or
two voices, with the same room, microphones and crosstalk.

DER = (missed speech + false alarm + wrong person) / reference speech, in
10 ms frames, with the usual 0.25 s tolerance around every reference turn,
overlapping speech included. People are matched to the reference with the
best one-to-one assignment. Lower is better; published systems on AMI sit
between about 15% and 25% with pyannote 3, depending on the setup.

Needs: pip install sherpa-onnx onnxruntime scipy soundfile
"""
import argparse
import pathlib
import sys
import time
import urllib.request

import numpy as np
import soundfile as sf
from scipy.optimize import linear_sum_assignment

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import voices as V                                      # noqa: E402

DATA = HERE / "ami"
AUDIO = "https://groups.inf.ed.ac.uk/ami/AMICorpusMirror/amicorpus/{m}/audio/{m}.Mix-Headset.wav"
TURNS = "https://raw.githubusercontent.com/pyannote/AMI-diarization-setup/main/only_words/rttms/{split}/{m}.rttm"
MEETINGS = {"ES2004a": "train", "IS1009a": "test"}
STEP = 0.01


def fetch(m):
    DATA.mkdir(exist_ok=True)
    for url, dest in ((AUDIO.format(m=m), DATA / f"{m}.wav"),
                      (TURNS.format(m=m, split=MEETINGS[m]), DATA / f"{m}.rttm")):
        if not dest.exists():
            print(f"  downloading {dest.name}", flush=True)
            urllib.request.urlretrieve(url, dest)


def reference(m):
    rows = []
    for line in (DATA / f"{m}.rttm").read_text().splitlines():
        p = line.split()
        if p and p[0] == "SPEAKER":
            rows.append((float(p[3]), float(p[3]) + float(p[4]), p[7]))
    return rows


def meeting(m, keep):
    """The meeting with only its `keep` most talkative people."""
    audio, rate = sf.read(str(DATA / f"{m}.wav"), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    assert rate == V.RATE
    ref = reference(m)
    talk = {}
    for a, b, s in ref:
        talk[s] = talk.get(s, 0) + b - a
    kept = sorted(talk, key=lambda s: -talk[s])[:keep]
    frames = int(len(audio) / rate / STEP) + 1
    on = {s: np.zeros(frames, bool) for s in talk}
    for a, b, s in ref:
        on[s][int(a / STEP):int(b / STEP)] = True
    kept_on = np.any([on[s] for s in kept], axis=0)
    others = [on[s] for s in talk if s not in kept]
    mute = (np.any(others, axis=0) if others else np.zeros(frames, bool)) & ~kept_on
    gain = np.repeat(~mute, int(rate * STEP))
    gain = np.pad(gain, (0, max(0, len(audio) - len(gain))), constant_values=True)[:len(audio)]
    return audio * gain, [r for r in ref if r[2] in kept]


def der(ref, hyp, total, collar=0.25):
    frames = int(total / STEP) + 1
    rs = sorted({s for _, _, s in ref})
    hs = sorted({s for _, _, s in hyp}) or ["none"]
    R = np.zeros((len(rs), frames), bool)
    H = np.zeros((len(hs), frames), bool)
    for a, b, s in ref:
        R[rs.index(s), int(a / STEP):int(b / STEP)] = True
    for a, b, s in hyp:
        H[hs.index(s), int(a / STEP):int(b / STEP)] = True
    keep = np.ones(frames, bool)
    c = int(collar / STEP)
    for a, b, _ in ref:
        for t in (int(a / STEP), int(b / STEP)):
            keep[max(0, t - c):t + c] = False
    R, H = R[:, keep], H[:, keep]
    overlap = R.astype(int) @ H.T.astype(int)
    ri, hi = linear_sum_assignment(-overlap)
    nref, nhyp = R.sum(0), H.sum(0)
    speech = nref.sum()
    miss = np.maximum(nref - nhyp, 0).sum()
    fa = np.maximum(nhyp - nref, 0).sum()
    conf = np.minimum(nref, nhyp).sum() - overlap[ri, hi].sum()
    return {"der": (miss + fa + conf) / speech, "miss": miss / speech, "fa": fa / speech,
            "conf": conf / speech, "found": len({s for _, _, s in hyp}), "true": len(rs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="every threshold, on the tuning meeting")
    args = ap.parse_args()
    m = "ES2004a" if args.sweep else "IS1009a"
    thresholds = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9] if args.sweep else [V.THRESHOLD]
    fetch(m)
    seg = V._fetch(V.SEGMENTATION)
    fp = V._fetch(V.FINGERPRINTS)
    print(f"\n  {m}, {'tuning' if args.sweep else 'held out'}\n")
    print("  people  threshold    DER    missed  false alarm  wrong person  counted   seconds")
    for keep in (4, 3, 2):
        audio, ref = meeting(m, keep)
        t0 = time.time()
        starts, acts = V._segment(audio, seg)
        vecs, meta, seconds, bins = V._fingerprints(audio, starts, acts, fp)
        secs = time.time() - t0
        for th in thresholds:
            who, n = V.group(vecs, seconds, bins, threshold=th)
            r = der(ref, V.turns(starts, acts, meta, who, n), len(audio) / V.RATE)
            print(f"  {keep:>6}  {th:>9.2f}  {r['der']:6.1%}  {r['miss']:7.1%}  {r['fa']:11.1%}"
                  f"  {r['conf']:12.1%}  {r['found']:>4} of {r['true']}  {secs:6.0f}", flush=True)
    print()


if __name__ == "__main__":
    main()
