"""Compares the transcripts produced by benchmark.py, without a reference.

The problem: measuring the word error rate needs a transcript typed by hand,
and that costs hours. This uses two stand-ins that need no reference.

1. NON-EXISTENT WORDS. A hallucinating model does not produce noise: it
   produces plausible words that do not exist ("we export it in btf" for
   "we export it as PDF"). `wordfreq` gives how common a word is in a
   language: zero means the word is not used. More zeros, more invention.

   It is not the WER: a real but wrong word is not counted. But it is the
   worst kind of mistake for a reader, because an invented word stops the
   reading, while a real wrong word can often be guessed from context.

2. DISAGREEMENT. Where two models say the same thing, both are almost always
   right. Where they diverge is the real difficulty, and those spots are put
   one under the other: ten lines read by someone who was on the call are worth
   more than any automatic metric.

    python research/compare.py --language it                 every transcript
    python research/compare.py a.txt b.txt --language it     and where they disagree

Needs `pip install wordfreq` (only for this script).
"""
import argparse
import difflib
import pathlib
import re

from wordfreq import zipf_frequency

FOLDER = pathlib.Path(__file__).resolve().parent / "transcripts"

# At or below this, the word is not used in the language. Zero = never seen.
THRESHOLD = 0.0
# Words a generic meter would mark as non-existent but that belong in a
# business call: acronyms, product names, technical terms. Add yours.
ALLOWED = {"crm", "erp", "api", "pdf", "xml", "excel", "ok", "app", "email",
           "shopify", "wordpress", "whatsapp", "google", "meet", "drive",
           "tab", "link", "file", "backup", "login", "mail", "pc", "vat"}


def words(text):
    return re.findall(r"[^\W\d_][^\W\d_']+", text.lower())


def text_of(p):
    lines = p.read_text(encoding="utf-8").splitlines()
    return " ".join(re.sub(r"^\[\d+:\d+\]\s*", "", r) for r in lines)


def non_existent(text, language):
    ws = words(text)
    bad = [w for w in ws if w not in ALLOWED and zipf_frequency(w, language) <= THRESHOLD]
    return ws, bad


def overview(language):
    files = sorted(FOLDER.glob("*.txt"))
    if not files:
        raise SystemExit(f"Nothing in {FOLDER}/ yet: run benchmark.py first")
    print(f"\n{'transcript':<44}{'words':>8}{'non-existent':>14}{'rate':>8}")
    print("-" * 74)
    rows = []
    for p in files:
        ws, bad = non_existent(text_of(p), language)
        rate = len(bad) / max(1, len(ws))
        rows.append((p, bad))
        print(f"{p.stem[:42]:<44}{len(ws):>8}{len(bad):>14}{rate:>7.1%}")
    print()
    for p, bad in rows:
        if bad:
            unique = list(dict.fromkeys(bad))
            print(f"  {p.stem[:40]:<42} {', '.join(unique[:12])}")


def disagreement(a, b, how_many=12):
    """Where the two transcripts diverge, one under the other."""
    wa, wb = words(text_of(a)), words(text_of(b))
    m = difflib.SequenceMatcher(None, wa, wb, autojunk=False)
    same = sum(block.size for block in m.get_matching_blocks())
    print(f"\n  agreement: {2 * same / (len(wa) + len(wb)):.1%} of the words\n")
    print(f"  A = {a.stem}")
    print(f"  B = {b.stem}\n")
    shown = 0
    for tag, i1, i2, j1, j2 in m.get_opcodes():
        if tag == "equal" or shown >= how_many:
            continue
        ctx = " ".join(wa[max(0, i1 - 6):i1])      # a little context on the left
        da, db = " ".join(wa[i1:i2]), " ".join(wb[j1:j2])
        if len(da) + len(db) < 8:
            continue                                 # one-word differences: noise
        print(f"  …{ctx}")
        print(f"     A: {da[:90]}")
        print(f"     B: {db[:90]}\n")
        shown += 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="two transcripts to put side by side")
    ap.add_argument("--language", default="en", help='wordfreq code, e.g. "it" (default: en)')
    args = ap.parse_args()
    if len(args.files) == 2:
        disagreement(pathlib.Path(args.files[0]), pathlib.Path(args.files[1]))
    else:
        overview(args.language)
