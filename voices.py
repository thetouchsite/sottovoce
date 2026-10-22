"""Telling voices apart: who is speaking, from the sound alone.

No account, no gated download, no GPU. Two small models, fetched once from
sherpa-onnx's GitHub releases into models/ and checked against a fixed
SHA-256 before use:

    segmentation   pyannote segmentation-3.0, MIT          6 MB
    fingerprints   3D-Speaker ERes2Net (VoxCeleb), Apache-2.0   26 MB

The pipeline is pyannote 3's, rebuilt on those two:

  1. the segmentation model slides a 10-second window over the call and says,
     frame by frame, which of up to three local voices are speaking;
  2. every local voice in every window gets a fingerprint (an embedding);
  3. the reliable fingerprints (at least a second of clean speech) are
     grouped by distance to the group's centre; every fingerprint then joins
     the nearest real group, and each frame takes, among the people present,
     as many as the windows say are speaking.

MEASURED on two AMI meetings with every speaker annotated (research/voices_ami.py):
the threshold was tuned on one meeting and graded on the other, never seen:

    people on the call     4        3        2
    error (DER)          12.6%    11.8%    11.9%
    people counted         4        3        2      (by itself, all right)

DER here is missed speech + false alarm + wrong person, over the speech, with
the usual 0.25 s tolerance at turn boundaries. 17 minutes take about 25
seconds on the CPU. Four other fingerprint models were tried the same way
(WeSpeaker ResNet34 and ResNet293, 3D-Speaker CAM++, NVIDIA TitaNet-large):
TitaNet scored the same on AMI but gave the questions of a real call to the
wrong person; the others were clearly worse.

Grouping matters more than it looks: grouping every fingerprint by average
distance, the first version merged three people into one, because a few
noisy fingerprints from short bursts form groups of their own. Only clean
fingerprints are grouped now, and the noisy ones are assigned afterwards.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
MODELS = ROOT / "models"
RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

SEGMENTATION = {
    "file": "pyannote-segmentation-3.0.onnx",
    "url": f"{RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    "archive_sha256": "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
    "member": "sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
    "sha256": "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079",
}
FINGERPRINTS = {
    "file": "3dspeaker-eres2net-voxceleb.onnx",
    "url": f"{RELEASES}/speaker-recongition-models/3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx",
    "sha256": "c59158379255ad66e161679cca6af8d52d51e389e3224ab7d7a7baae295c2db5",
}

RATE = 16000
WINDOW = 10 * RATE            # the segmentation model sees 10 s at a time
STEP = 2.5                    # seconds between windows: each frame is seen 4 times
FRAMES = 589                  # frames per window
SHIFT = 270 / RATE            # seconds per frame
THRESHOLD = 0.6               # tuned on one AMI meeting, graded on another
CLEAN = 1.0                   # seconds of speech for a fingerprint to be trusted
TALK = 15.0                   # seconds of distinct speech for a group to be a person: see group()

# The segmentation model answers in "powerset" classes: nobody, a, b, c,
# a+b, a+c, b+c. This turns them into three on/off tracks.
_POWERSET = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1]]


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(spec: dict, progress=None) -> pathlib.Path:
    """The model on disk, downloaded and checked the first time.

    A file that does not match its SHA-256 is never used: a broken download
    or a changed file upstream would otherwise give wrong voices silently.
    """
    dest = MODELS / spec["file"]
    if dest.exists() and _sha256(dest) == spec["sha256"]:
        return dest
    MODELS.mkdir(exist_ok=True)
    if progress:
        progress("downloading the voice models (30 MB, once)", 0)
    with tempfile.TemporaryDirectory() as tmp:
        got = pathlib.Path(tmp) / "download"
        with urllib.request.urlopen(spec["url"], timeout=120) as r, got.open("wb") as out:
            shutil.copyfileobj(r, out)
        if "archive_sha256" in spec:
            if _sha256(got) != spec["archive_sha256"]:
                raise RuntimeError(f"{spec['url']} did not match its checksum")
            with tarfile.open(got, "r:bz2") as t:
                member = t.getmember(spec["member"])
                with t.extractfile(member) as src, (pathlib.Path(tmp) / "model").open("wb") as out:
                    shutil.copyfileobj(src, out)
            got = pathlib.Path(tmp) / "model"
        if _sha256(got) != spec["sha256"]:
            raise RuntimeError(f"{spec['file']} did not match its checksum")
        shutil.move(str(got), dest)
    return dest


def ready() -> bool:
    """Whether the models are already on disk (no download needed)."""
    return all((MODELS / s["file"]).exists() for s in (SEGMENTATION, FINGERPRINTS))


def _segment(audio, model):
    import numpy as np
    import onnxruntime as ort
    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    powerset = np.array(_POWERSET)
    starts = list(range(0, max(1, len(audio) - WINDOW) + 1, int(STEP * RATE)))
    if starts[-1] + WINDOW < len(audio):
        starts.append(len(audio) - WINDOW)
    acts = []
    for i in range(0, len(starts), 32):
        batch = np.stack([np.pad(audio[s:s + WINDOW], (0, max(0, WINDOW - len(audio[s:s + WINDOW]))))
                          for s in starts[i:i + 32]])[:, None, :].astype(np.float32)
        acts.append(powerset[sess.run(None, {"x": batch})[0].argmax(-1)])
    return np.array(starts), np.concatenate(acts)


def _fingerprints(audio, starts, acts, model):
    import numpy as np
    import sherpa_onnx
    ex = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model), num_threads=4))
    vecs, meta, seconds, bins = [], [], [], []
    for w, s in enumerate(starts):
        for k in range(3):
            on = acts[w, :, k].astype(bool)
            if on.sum() * SHIFT < 0.3:
                continue
            # Frames where this voice speaks alone, when there are enough of
            # them: an overlapped frame carries two voices in one fingerprint.
            alone = on & (acts[w].sum(1) == 1)
            use = alone if alone.sum() * SHIFT >= 0.5 else on
            idx = np.nonzero(use)[0]
            samples = np.concatenate([audio[s + int(f * SHIFT * RATE): s + int((f + 1) * SHIFT * RATE)]
                                      for f in idx])
            st = ex.create_stream()
            st.accept_waveform(RATE, samples)
            st.input_finished()
            v = np.array(ex.compute(st))
            vecs.append(v / (np.linalg.norm(v) + 1e-9))
            meta.append((w, k))
            seconds.append(on.sum() * SHIFT)
            # Where in the call this voice speaks, in half seconds: four
            # windows see the same moment, and must count it once.
            bins.append({int((s / RATE + f * SHIFT) * 2) for f in np.nonzero(on)[0]})
    return np.array(vecs), meta, np.array(seconds), bins


def group(vecs, seconds, bins, threshold=THRESHOLD, clean=CLEAN, talk=TALK):
    """Fingerprints into people: an index per fingerprint, and how many people.

    Only fingerprints from at least `clean` seconds of speech are grouped, by
    distance to the group's centre; groups too small to be a person (a cough,
    a laugh) are not people; then every fingerprint joins the nearest person.

    Too small is measured in seconds of distinct speech, not in fingerprints.
    Every moment is seen by four windows, so one burst of noise gives four
    near-identical fingerprints: a group of four. The first version required
    2% of the fingerprints, which is eight on a long meeting and three on
    sparse audio, and on the call's side of a two-track recording (silent
    wherever you speak) it found 16 people instead of 2. With 15 seconds:
    2 of 2 there, the full AMI meetings unchanged. 15 is the smallest value
    clean on the tuning meeting (10 still left 4-8 extra people); 20 was the
    same there, but on 3-minute pieces of the other meeting it found 1 person
    of 3, against 2 with 15. Short calls where the others say little remain
    the weak spot: someone who talks for less than 15 seconds joins the
    nearest voice.
    """
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage
    if len(vecs) == 0:
        return np.array([], int), 0
    trusted = np.nonzero(seconds >= clean)[0]
    if len(trusted) < 2:
        trusted = np.arange(len(vecs))
    if len(trusted) < 2:
        return np.zeros(len(vecs), int), 1
    X = vecs[trusted]
    lab = fcluster(linkage(X, method="centroid", metric="euclidean"), t=threshold, criterion="distance")
    groups = {c: np.nonzero(lab == c)[0] for c in set(lab)}
    people = [m for m in groups.values()
              if len(set().union(*(bins[trusted[i]] for i in m))) / 2 >= talk]
    people = people or [max(groups.values(), key=len)]
    centres = np.array([X[m].mean(0) / np.linalg.norm(X[m].mean(0)) for m in people])
    return (vecs @ centres.T).argmax(1), len(people)


def diarize(audio, progress=None):
    """Who speaks when, in mono 16 kHz audio: [(start, end, "Voice N")], N from 1.

    Voices are numbered in the order they first speak, so "Voice 1" is
    whoever opens the call, in every call.
    """
    import numpy as np
    seg_model = _fetch(SEGMENTATION, progress)
    fp_model = _fetch(FINGERPRINTS, progress)
    if progress:
        progress("telling the voices apart", 0)
    starts, acts = _segment(audio, seg_model)
    vecs, meta, seconds, bins = _fingerprints(audio, starts, acts, fp_model)
    if len(vecs) == 0:
        return []
    who, n = group(vecs, seconds, bins)
    return turns(starts, acts, meta, who, n)


def turns(starts, acts, meta, who, n):
    """From people per fingerprint back to time: who speaks when.

    Every frame is seen by four windows. Each person scores where their
    fingerprints' local voice was active; a frame then goes to as many of the
    best-scoring people as the windows, on average, heard speaking at once.
    """
    import numpy as np
    total = int((starts[-1] / RATE + 10) / SHIFT) + 2
    score = np.zeros((n, total))
    count = np.zeros(total)
    cover = np.zeros(total)
    for w, s in enumerate(starts):
        f0 = int(s / RATE / SHIFT)
        cover[f0:f0 + FRAMES] += 1
        count[f0:f0 + FRAMES] += acts[w].sum(1)
    for (w, k), c in zip(meta, who):
        f0 = int(starts[w] / RATE / SHIFT)
        score[c, f0:f0 + FRAMES] += acts[w, :, k]
    cover[cover == 0] = 1
    speaking = np.round(count / cover).astype(int)
    order = np.argsort(-score, axis=0)
    on = np.zeros_like(score, dtype=bool)
    for f in range(total):
        for j in order[:speaking[f], f]:
            if score[j, f] > 0:
                on[j, f] = True

    out = []
    for j in range(n):
        edges = np.diff(np.concatenate([[0], on[j].astype(int), [0]]))
        for a, b in zip(np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]):
            out.append((a * SHIFT, b * SHIFT, j))
    first = {}
    for a, _, j in sorted(out):
        first.setdefault(j, len(first) + 1)
    return sorted((round(a, 2), round(b, 2), f"Voice {first[j]}") for a, b, j in out)


def assign(words, turns, keep=None, lines=None):
    """A voice for every word: the voice that overlaps it most.

    A word that falls in no turn takes the nearest one. A single word that
    disagrees with both neighbours is smoothed over, as for two tracks: one
    "ok" inside someone else's sentence is more often a mistake than a real
    interruption. `keep` (optional) gives labels that are not to be touched,
    such as "Me" on a call recorded on two tracks.

    `lines` (optional) is where each of Whisper's lines starts. With estimated
    word timings a line's last word often runs into the next person's turn:
    on an AMI meeting, 27 of 193 lines came out as one word ("right.", "is.")
    split off from their sentence. So a single word at the edge of a line
    takes the voice of the word next to it in the same line: 13 one-word
    lines of 180 are left, most of them real ("Right?"), for words with the
    right voice going from 96.5% to 96.0%. Sentences read whole are worth it.
    """
    out = []
    for i, (a, b, _) in enumerate(words):
        if keep and keep[i]:
            out.append(keep[i])
            continue
        best, label = 0.0, None
        for s, e, v in turns:
            o = min(b, e) - max(a, s)
            if o > best:
                best, label = o, v
        if label is None and turns:
            label = min(turns, key=lambda t: min(abs(t[0] - b), abs(t[1] - a)))[2]
        out.append(label)
    for i in range(1, len(out) - 1):
        if keep and keep[i]:
            continue
        if out[i - 1] == out[i + 1] != out[i] and not (keep and keep[i - 1]):
            out[i] = out[i - 1]
    if lines:
        starts = sorted(set(lines) | {len(out)})
        for a, b in zip(starts, starts[1:]):
            if b - a < 3:
                continue
            for edge, inner in ((a, a + 1), (b - 1, b - 2)):
                if out[edge] != out[inner] and not (keep and (keep[edge] or keep[inner])):
                    out[edge] = out[inner]
    return out
