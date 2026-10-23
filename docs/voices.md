# Telling voices apart

On a call with several people, tick **Separate voices** before transcribing, or open a call already transcribed and press **Separate voices** at the top of its right column: there is no need to transcribe again. Every line gets *Voice 1*, *Voice 2*…, numbered in the order they first speak.

Name them in the **Voices** panel next to the transcript. The names appear in the reading views, in what you copy, in every download, in the summary and in the follow-up email. The `.txt` keeps the labels and `info.json` keeps the names, so a wrong name is undone by changing one field.

## No account, no token

The usual choice, [pyannote](https://github.com/pyannote/pyannote-audio), asks for a Hugging Face account and for accepting its terms before it downloads anything. Sottovoce uses:

- **pyannote segmentation-3.0** (MIT), as redistributed by [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), to find who speaks when in each 10-second window;
- **3D-Speaker ERes2Net** (Apache-2.0) from [3D-Speaker](https://github.com/modelscope/3D-Speaker), for a fingerprint of each voice.

Both are downloaded from GitHub on first use, 32 MB in all, and checked against a fixed SHA-256 before they are used. They run on the CPU, so the GPU stays with Whisper. You don't say how many people were on the call: they are counted.

## How the voices are grouped

The pipeline is pyannote 3's, rebuilt on those two models. The segmentation model slides a 10-second window over the call; every voice in every window gets a fingerprint; fingerprints are grouped into people by their distance to the group's centre.

Two details decide the quality:

- **Only clean fingerprints are grouped.** Fingerprints from at least a second of speech are grouped first; short ones join the nearest person afterwards. Grouping everything at once merged three people into one, because short noisy bursts formed groups of their own.
- **A person needs 15 seconds of distinct speech.** Every moment is seen by four windows, so one burst of noise gives four near-identical fingerprints. Counting seconds of speech instead of fingerprints keeps those from becoming extra people.

## How well it works

Measured on public [AMI](https://groups.inf.ed.ac.uk/ami/corpus/) meetings where every speaker is annotated: the settings were chosen on one meeting and graded on another, never seen while choosing. See [Benchmarks](benchmarks.md#telling-voices-apart).

| People on the call | 4 | 3 | 2 |
| --- | --- | --- | --- |
| Error (DER) | 12.6% | 11.8% | 11.9% |
| People counted | 4 of 4 | 3 of 3 | 2 of 2 |

```sh
python research/voices_ami.py
```

## Where it goes wrong

- Two similar voices on the same phone can merge into one.
- A short "yes" or "okay" can go to the wrong person.
- Someone who talks for less than about 15 seconds in all joins the nearest voice: on short calls where one person does most of the talking, expect fewer voices than people.
- When two people talk at once, the overlapping words go to one of them.
- The number of people can't be set by hand yet.
