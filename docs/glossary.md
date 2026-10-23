# The name glossary

Whisper can't know your clients' names, your products or your colleagues. It writes them as it hears them, often several different ways in the same call, and then search misses them and the summary garbles them.

The glossary is a correction table, applied after transcription:

```text
# glossary.txt
Northpine <- North pine, Nord pine
Trailhead <- Trail head
```

The right name on the left; on the right, the ways it comes out wrong, separated by commas. Matching ignores case and respects word boundaries: a name never fires inside another word.

## Using it

- **From the page:** the book icon opens the glossary view. It shows every name, how it gets written wrong, and how many times it appears across your calls. New lines are added without touching your comments.
- **By hand:** `glossary.txt` is a plain text file next to the program. `#` starts a comment.
- **On older calls:** after adding a name, open a call and press **Apply the glossary again**. Every change goes into `corrections.jsonl` with its before and after, so it can be undone, and the word timings follow the corrected text.

`glossary.txt` is git-ignored, because it holds your clients' names. The repo ships `glossary.example.txt`.

## Why after, not before

Whisper accepts an initial prompt to tell it which names to expect, and that is the documented way. Tried on a real call, the prompt made the text worse: it pushed the model into long runs and made it look for those names everywhere. A deterministic table applied to the output can't make the transcription worse. The measurement is in [Benchmarks](benchmarks.md#names-correct-after-dont-prompt-before).
