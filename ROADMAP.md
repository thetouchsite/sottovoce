# Roadmap

What's missing, in order. Each item says **why** and **how we'll know it's done**. A plan without a finish line is just a wish list.

The ideas come from projects that do this job well: [whisper.cpp](https://github.com/ggerganov/whisper.cpp), [WhisperX](https://github.com/m-bain/whisperX), [Buzz](https://github.com/chidiwilliams/buzz) and [Vibe](https://github.com/thewh1teagle/vibe). All are permissively licensed, so their ideas can be read, borrowed and credited. Where the idea is enough, we don't copy code.

---

## 1. Word-level timestamps

**Why.** A timestamp currently belongs to a segment, so clicking a line jumps to where the segment starts, not to the word. In a 30-minute call, landing within 10 seconds of a word and landing on the word is the difference between searching and finding.

**How.** The WhisperX idea: after Whisper, run forced alignment with a small phonetic model over the text that's already there. It moves the timings and leaves the words alone.

**Done when** clicking a word on the page plays from that word, less than half a second off.

## 2. Record straight from the PC

**Why.** It fixes the problem at the root instead of fixing what it causes. Today the call is recorded with a phone on the desk: one voice near the mic, the others from the speaker, mean -29.8 dB with peaks at -0.9. **Everything** we compensate for comes from that: loudness normalization, garbled names, phrases invented on silence. Recording the PC's audio output gets clean audio, and most of that work stops being needed.

**How.** The Vibe idea: capture system audio (WASAPI loopback on Windows) and the microphone as two separate tracks. Which also gives **speaker separation for free**: whoever comes out of the speaker isn't you.

**Done when** a "record" button on the page produces a transcript with fewer non-existent words than the same call recorded with a phone.

## 3. Fine-tune on your own corrections

**Why.** Every line corrected by hand is a pair: what the model heard, and what was right. It's the one thing here that can't be bought or downloaded. It's your language, your names, your calls, recorded badly.

**Not yet.** It needs around a hundred calls. But **the dataset is collected from day one**, which is why `corrections.jsonl` keeps the before and the after: it can't be rebuilt later.

**Two things to do now, because they can't be done later.** Set aside a group of calls as a test set and **never look at them**. And write down the success criterion **before** training. Without both, the improvement gets measured on what the model has already seen, and it will always look like it worked.

And a rule learned the hard way, on another project: **never decide on a single training run.** The variance between two identical runs changes the result more than almost any real improvement. Use three seeds, and report the mean and the spread.

## 4. Speaker labels, optionally

**Why.** On calls with several people, "who said it" sometimes matters. Item 2 solves it for two-sided calls without any model.

**How.** `pyannote` on top of the transcript, as an opt-in. It needs a Hugging Face token and accepting a licence, so it stays off by default.

**Done when** it can be switched on from the page, and switching it off leaves no trace in the install.

## 5. Linux and macOS launchers

**Why.** The Python code is cross-platform, but only Windows is tested and has double-click launchers.

**Done when** `install.sh` and `start.sh` work on a clean Ubuntu machine with an NVIDIA GPU, checked by someone who isn't the author.
