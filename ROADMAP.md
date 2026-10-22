# Roadmap

What's missing, in order. Each item says **why** and **how we'll know it's done**. A plan without a finish line is just a wish list.

The ideas come from projects that do this job well: [whisper.cpp](https://github.com/ggerganov/whisper.cpp), [WhisperX](https://github.com/m-bain/whisperX), [Buzz](https://github.com/chidiwilliams/buzz) and [Vibe](https://github.com/thewh1teagle/vibe). All are permissively licensed, so their ideas can be read, borrowed and credited. Where the idea is enough, we don't copy code.

---

## Done in 1.1

**Recording a call from the page.** The Vibe idea, done in the browser instead of natively: the call's tab and the microphone on two tracks, sent to the server every five seconds so an interrupted recording is offered again instead of lost. Checked on a synthetic two-track recording made from a real call: the two voices labelled correctly, with the other side bleeding into the microphone at -25 dB.

**Who spoke, for calls recorded here.** It falls out of the two tracks, with no speaker-recognition model: each word goes to the track that is louder than usual at that moment, and lines split where the speaker changes.

**Word timings.** By default each line's time is shared among its words, at no cost. Precise timings come from Whisper's own alignment, with no second model, at twice the transcription time (395 s instead of 200 on the 27-minute call, same quality). Not yet checked against a hand-timed reference: the "less than half a second off" criterion is still open.

**Exports** (`.srt`, `.vtt`, `.json`), **several files at once**, **tests and CI** (engine, API and page, on every push, Ubuntu and Windows, Python 3.10 and 3.14).

## 1. Record calls from desktop apps

**Why.** Recording from the page covers calls in a browser tab. Teams, Zoom and Webex desktop apps, and phone calls through the PC, don't have a tab to share.

**How.** System-wide loopback capture (WASAPI on Windows), plus the microphone, on the same two tracks. Probably a small native helper, since a web page can't capture the whole system's sound on its own.

**Done when** a call in the Teams desktop app is recorded and transcribed with *You* and *Them*, without a browser tab.

## 2. Check precise word timings against a reference

**Why.** Precise mode promises a click lands on the word. Nobody has measured how close it lands.

**How.** Time by hand the words of two minutes of a real call, and compare.

**Done when** the median offset is under half a second, or the README says what it really is.

## 3. Fine-tune on your own corrections

**Why.** Every line corrected by hand is a pair: what the model heard, and what was right. It's the one thing here that can't be bought or downloaded. It's your language, your names, your calls, recorded badly.

**Not yet.** It needs around a hundred calls. But **the dataset is collected from day one**, which is why `corrections.jsonl` keeps the before and the after: it can't be rebuilt later.

**Two things to do now, because they can't be done later.** Set aside a group of calls as a test set and **never look at them**. And write down the success criterion **before** training. Without both, the improvement gets measured on what the model has already seen, and it will always look like it worked.

And a rule learned the hard way, on another project: **never decide on a single training run.** The variance between two identical runs changes the result more than almost any real improvement. Use three seeds, and report the mean and the spread.

## 4. Speaker labels for calls recorded elsewhere

**Why.** A phone recording has one track, so who spoke can't be measured. On calls with several people it sometimes matters.

**How.** `pyannote` on top of the transcript, as an opt-in. It needs a Hugging Face token and accepting a licence, so it stays off by default.

**Done when** it can be switched on from the page, and switching it off leaves no trace in the install.

## 5. Linux and macOS launchers

**Why.** The Python code is cross-platform and the tests run on Ubuntu, but only Windows has double-click launchers.

**Done when** `install.sh` and `start.sh` work on a clean Ubuntu machine with an NVIDIA GPU, checked by someone who isn't the author.
