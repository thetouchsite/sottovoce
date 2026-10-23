# Benchmarks

Every number in these docs comes from a script in [`research/`](https://github.com/thetouchsite/sottovoce/tree/main/research), with the command to run it next to it. The first four sections use public or bundled data: anyone can check them. The last one records measurements made during development on a private call: they explain why the defaults are what they are.

**Machine:** NVIDIA GeForce RTX 5090 Laptop GPU (24 GB), Windows 11, Python 3.14, PyTorch 2.14.1 + CUDA 13.0, transformers 5.20.

## Transcription accuracy

Word error rate (WER): words substituted, dropped and added, over the words of a hand-made transcript. Lower is better. Reference and transcript go through Whisper's own text normalizer first, so case, punctuation and filler words don't count.

Three ways to transcribe the same audio:

- **large-v3** and **turbo**: Whisper large-v3 and large-v3-turbo alone, through the Hugging Face pipeline with its defaults: what you get by running the model as it comes.
- **Sottovoce**: the whole engine, `transcribe.run()`. Same model as large-v3, plus loudness normalization, the anti-hallucination settings and the removal of subtitle phrases on silence. The name glossary is off.

```sh
pip install jiwer
python research/wer.py fleurs     # Italian, read speech
python research/wer.py ami        # English meetings, whole
python research/wer.py silence    # Italian, with long pauses
```

The data is downloaded on the first run, with no account: [FLEURS](https://huggingface.co/datasets/google/fleurs) and [AMI](https://groups.inf.ed.ac.uk/ami/corpus/), both CC BY 4.0.

### Italian, read speech

FLEURS `it_it`, the whole test split: 865 recordings, 211 minutes, 20,787 words. Short clean sentences read aloud.

| | WER | Substituted | Dropped | Added | Speed |
| --- | --- | --- | --- | --- | --- |
| large-v3 | 4.3% | 1.7% | 0.2% | 2.4% | 7.1× real time |
| turbo | 4.8% | 2.0% | 0.3% | 2.5% | 27.1× |
| **Sottovoce** | **4.3%** | 1.7% | 0.2% | 2.4% | 5.9× |

On clean speech the engine changes nothing in the text: the same model gives the same words. It is slower here because every clip is measured and normalized before transcribing, which on clips of a few seconds weighs more than on a call. Turbo is four times faster and makes about a tenth more errors.

### English meetings, whole

Four AMI test meetings, one from each series (`ES2004a`, `IS1009a`, `TS3003a`, `EN2002a`): 92 minutes, 14,993 words, the room's mixed headsets, each meeting transcribed in one go as a recording would be.

| | WER | Substituted | Dropped | Added | Speed |
| --- | --- | --- | --- | --- | --- |
| large-v3 | 30.3% | 4.3% | 23.7% | 2.3% | 10.7× real time |
| turbo | 28.4% | 4.2% | 23.2% | 0.9% | 35.4× |
| **Sottovoce** | **25.4%** | 4.0% | 20.5% | 0.9% | 7.7× |

Most errors are dropped words: in AMI four people talk over each other, and the reference has every word of every one of them, short *yeah*s included. Whisper writes one voice at a time. These figures are not comparable with leaderboards that cut AMI into single utterances first: here nobody has cut the meeting.

### Long pauses

Whisper invents on silence, and more on the faint hiss of a real line than on digital silence. Five files of 10 FLEURS sentences each, separated by 15 to 45 seconds of noise at -50 dB: 40 minutes, 28 of them noise, 1,175 words. Built the same way on every run (fixed seed).

| | WER | Words added | Subtitle phrases | Words dropped |
| --- | --- | --- | --- | --- |
| large-v3 | 30.0% | 318 | 15 | 5 |
| turbo | 41.2% | 444 | 16 | 8 |
| **Sottovoce** | **10.0%** | **47** | **1** | 34 |

*Words added* are words in the transcript and not in the reference. *Subtitle phrases* counts *"Grazie a tutti"*, *"Sottotitoli e revisione a cura di QTSS"* and the rest of the known list. The one left in Sottovoce's text follows a real sentence in the same line, so it isn't removed: it is flagged *to check*.

Two things this test found:

- **A bug, now fixed.** Silence used to be measured on the audio Whisper hears, after loudness normalization. In one pass the normalizer lifts long quiet stretches: the hiss at -50 dB came out at -19 dB, as loud as speech, and no phrase was ever dropped. Before the fix Sottovoce scored 14.5%, with 101 words added and 18 subtitle phrases.
- **A limit, still open.** After a long pause Whisper's long-form mode sometimes writes a subtitle phrase over a window that ends in real speech, and the first sentence after the pause is never written. The phrase is removed; the sentence is still missing. That is most of the 34 words dropped. It's on the [roadmap](https://github.com/thetouchsite/sottovoce/blob/main/ROADMAP.md).

## Telling voices apart

Two public [AMI](https://groups.inf.ed.ac.uk/ami/corpus/) meetings (CC BY 4.0), every speaker annotated. The threshold was chosen on `ES2004a` and graded on `IS1009a`, never looked at while choosing. Each meeting has four people; for three and two, the others are muted where they speak alone, so the room and the microphones stay the same.

```sh
python research/voices_ami.py            # the held-out meeting
python research/voices_ami.py --sweep    # every threshold, on the tuning meeting
```

| People on the call | DER | Missed | False alarm | Wrong person | People counted |
| --- | --- | --- | --- | --- | --- |
| 4 | 12.6% | 6.2% | 2.6% | 3.8% | 4 of 4 |
| 3 | 11.8% | 4.1% | 4.4% | 3.3% | 3 of 3 |
| 2 | 11.9% | 3.8% | 6.9% | 1.3% | 2 of 2 |

DER (diarization error rate) adds up missed speech, false alarms and speech given to the wrong person, over all the speech, with the usual 0.25 s tolerance where turns change. Lower is better.

Other fingerprint models were tried in the same way during development: WeSpeaker ResNet34 and ResNet293, 3D-Speaker CAM++ and NVIDIA TitaNet-large. ERes2Net was kept as the best on these meetings and on a real call; the other models are not in the script today.

## Two-track calls

Who said each word on a call recorded on two tracks, your microphone and the call. Built from AMI meetings where every person wore a headset microphone: one person's headset on one track, the others on the other, so every microphone also hears the room, as in real life. Two setups: *headset*, as recorded, and *speakers*, where the call also leaks into the microphone at -25 dB, as without headphones.

```sh
python research/two_tracks.py                        # the current method
python research/two_tracks.py --method per_track     # each track transcribed on its own
```

Held-out meeting `IS1009a`. *Right side* is the share of words given to the right person (you or the others), over the words said where only one person spoke. *Invented* counts words that fall where nobody spoke, half a second either way.

| People | Setup | Current: right side | Current: words / invented | Per track: right side | Per track: words / invented |
| --- | --- | --- | --- | --- | --- |
| 2 | headset | **89.8%** | 1,606 / 77 | 62.1% | 2,421 / 102 |
| 3 | headset | **91.8%** | 1,602 / 89 | 61.8% | 2,525 / 110 |
| 4 | headset | **90.7%** | 1,641 / 66 | 63.2% | 2,552 / 121 |
| 2 | speakers | **90.8%** | 1,624 / 115 | 62.1% | 2,421 / 98 |
| 3 | speakers | **91.8%** | 1,647 / 81 | 61.8% | 2,523 / 110 |
| 4 | speakers | **89.2%** | 1,631 / 68 | 63.3% | 2,543 / 121 |

The current method transcribes the two tracks mixed and lays each line's words over the moments someone speaks in it. Transcribing each track on its own puts every word on its side by construction, but in an AMI room every headset hears the others clearly, so Whisper transcribes them twice. A real Meet call is kinder to it (the call's track never carries your voice), so it stays on the roadmap, to be measured on real calls.

## The built-in summary model

Qwen3 4B Instruct, through the same endpoints the page uses, on the fictional calls in `examples/`.

```sh
python research/llm.py
```

| Task | Run | Seconds | Tokens read | Tokens written |
| --- | --- | --- | --- | --- |
| Follow-up email, 1-minute Italian call | loading the model included | 55.8 | 495 | 184 |
| Summary, 11-minute English call | model loaded | 10.9 | 1,484 | 269 |
| Follow-up email | model loaded | 7.2 | 495 | 184 |
| Summary | model loaded | 10.3 | 1,484 | 269 |

GPU memory held by the model: 7.8 GB. The first run also downloads it (8 GB).

## On a private call

These measurements were made on **one real 27-minute business call in Italian**, recorded with a phone on a desk. The recording is a client's and is not published, so they can't be checked from outside; not every variant below can be re-run with today's scripts. They are kept as the record of why the defaults are what they are.

There was no hand-typed reference, so the metric is the **share of words that don't exist in the language**, checked with [wordfreq](https://github.com/rspeer/wordfreq): a hallucinating model produces plausible words that aren't real. To measure your own recordings the same way:

```sh
python research/benchmark.py whisper-large-v3 call.wav --language it
python research/benchmark.py whisper-turbo    call.wav --language it
python research/compare.py --language it
```

### Which model

| | Non-existent words | Time on 27 min | Invented phrases |
| --- | --- | --- | --- |
| **whisper-large-v3** | **1.2%** | 168 s | 3 |
| whisper-large-v3-turbo | 2.2% | 50 s | 4 |
| parakeet-tdt-0.6b-v3 | 2.8% | 355 s | 0 |

The gap showed on proper nouns: one company name came out of Parakeet spelled eight different ways, and out of large-v3 almost always the same. On the first 5 minutes alone the three models looked even (1.6%, 2.2%, 2.1%): the difference only appeared over 2,500 words.

### Removing invented phrases

| Approach | Non-existent words | Invented phrases |
| --- | --- | --- |
| Nothing | 31 (1.2%) | 3 |
| Cut all silence before transcribing | 42 (1.7%) | 0 |
| Cut only pauses over 3 s | 47 (1.8%) | 0 |
| Transcribe speech regions separately | 30 (1.2%) | 2 |
| **Remove subtitle phrases only where the audio is 12 dB below speech** | **30 (1.2%)** | **0** |

Cutting silence removes the hallucinations but makes the words worse: silence is how Whisper knows where words end. So the whole audio goes to the model, and only the known subtitle phrases are removed, only where the audio is far below the level of speech.

### Names: correct after, don't prompt before

| | Segments | Non-existent words |
| --- | --- | --- |
| No prompt | 552 | 44 (1.7%) |
| Glossary given to Whisper as a prompt | 166 | 67 (2.6%) |

The prompt pushed the model into long runs and made it look for those names everywhere. The glossary is applied after transcription instead; on that call it fixed 27 occurrences of five names.

### Word timings

| | Time | Non-existent words |
| --- | --- | --- |
| Default (each line's time shared among its words) | 200 s | 29 of 2,504 (1.2%) |
| Precise word timings (Whisper's own alignment) | 395 s | 29 of 2,500 (1.2%) |

Same quality, twice the time: precise timings need the attention weights, which switches off the fast attention kernel.

### Other settings

- **Loudness normalization** made Whisper 35% faster on that call, with the same text: on a weak signal it discards and retries uncertain windows.
- **Whisper's own long-form mode** instead of 30-second chunks: chunking produced timestamps that went backwards and the same three words forty times in a row.
- **One transcription at a time:** two in parallel took 233 s instead of 190.
