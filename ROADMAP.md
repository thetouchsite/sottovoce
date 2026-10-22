# Roadmap

What's missing, in order. Each item says **why** and **how we'll know it's done**. A plan without a finish line is just a wish list.

The ideas come from projects that do this job well: [whisper.cpp](https://github.com/ggerganov/whisper.cpp), [WhisperX](https://github.com/m-bain/whisperX), [Buzz](https://github.com/chidiwilliams/buzz) and [Vibe](https://github.com/thewh1teagle/vibe). All are permissively licensed, so their ideas can be read, borrowed and credited. Where the idea is enough, we don't copy code.

---

## Done in 1.2

**Telling voices apart, for any recording.** The item that was number 4 here said "`pyannote` as an opt-in, with a Hugging Face token". It turned out the token wasn't needed: pyannote's segmentation model is MIT and redistributed without a gate by sherpa-onnx, and the voice fingerprints come from 3D-Speaker (Apache-2.0). So it's one tick on the page, nothing to sign up for. On a public meeting never seen while tuning: 12.6%, 11.8% and 11.9% error with four, three and two people, all counted right; 96% of words get the right voice end to end. Switching it off leaves 32 MB in `models/`, which can be deleted.

## Done in 1.1

**Recording a call from the page.** The Vibe idea, done in the browser instead of natively: the call's tab and the microphone on two tracks, sent to the server every five seconds so an interrupted recording is offered again instead of lost. Checked on a synthetic two-track recording made from a real call: the two voices labelled correctly, with the other side bleeding into the microphone at -25 dB.

**Who spoke, for calls recorded here.** It falls out of the two tracks, with no speaker-recognition model: each word goes to the track that is louder than usual at that moment, and lines split where the speaker changes.

**Word timings.** By default each line's time is shared among its words, at no cost. Precise timings come from Whisper's own alignment, with no second model, at twice the transcription time (395 s instead of 200 on the 27-minute call, same quality). Not yet checked against a hand-timed reference: the "less than half a second off" criterion is still open.

**Exports** (`.srt`, `.vtt`, `.json`), **several files at once**, **tests and CI** (engine, API and page, on every push, Ubuntu and Windows, Python 3.10 and 3.14).

## 1. Two tracks: transcribe each track on its own

**Why.** On a call recorded here, who speaks when is known exactly: it's in the two tracks. But Whisper hears them mixed, and gives times per line, not per word. When one line holds the end of one person's turn and the start of the other's, which *word* falls at the change is a guess. On a fast test call in Meet (two people, short overlapping turns) about 19 words of 136 still go to the wrong person, against 1% on a meeting with long turns.

**Tried.** Each track transcribed alone, only in the stretches where its person speaks, each stretch at its own time. On that call every line went to the right person, and the text came out better punctuated. Two problems before it can be the default:

- Whisper invents *"Grazie."* on short noises from the microphone (a breath, a click): a dozen on that call.
- Without headphones the microphone hears the others faintly, and that echo is transcribed a second time under your name: on an AMI meeting with the others at -25 dB in the microphone, words on the right side fell to 75%.

Both look fixable: a stretch belongs to your track only where your track is the louder of the two (as the current labelling already decides), and stretches too short or too quiet are not sent to Whisper.

**Measured.** `research/two_tracks.py` builds real two-track calls from AMI meetings, where every person wore a headset microphone: one person's headset on one side, the others on the other, with the room heard faintly in every microphone as in real life. On the held-out meeting the current way puts about **90%** of words on the right side (2 people 89.8%, 3 people 91.8%, 4 people 90.7%; with the call leaking from loudspeakers at -25 dB, 90.7%, 91.8%, 89.2%). Earlier figures of 99% came from tracks cut apart artificially, with no crosstalk: too kind.

**Each track alone, on the same test** (`--method per_track`, with pieces taken only where a track is the louder of the two, and pieces under 0.4 s skipped): about **62%** of words on the right side, and half as many words again as there were, because every headset in an AMI room also hears the others clearly and Whisper transcribes them twice. It loses here. But a real Meet call is kinder to it than this test: the call's track never carries your voice, and with headphones your microphone doesn't carry theirs. So it is parked, not dropped, until it can be measured on real calls recorded here.

**Done when** it beats those numbers in `research/two_tracks.py` and on several real calls recorded here (with and without headphones, two and three people), counted word by word, and never puts lines out of order. Transcribing each whole track without cutting was tried too: Whisper's times drift on a track that is silent half the time (median 2.3 s off).

## 2. Record calls from desktop apps

**Why.** Recording from the page covers calls in a browser tab. Teams, Zoom and Webex desktop apps, and phone calls through the PC, don't have a tab to share.

**How.** System-wide loopback capture (WASAPI on Windows), plus the microphone, on the same two tracks. Probably a small native helper, since a web page can't capture the whole system's sound on its own.

**Done when** a call in the Teams desktop app is recorded and transcribed with *You* and *Them*, without a browser tab.

## 3. Check precise word timings against a reference

**Why.** Precise mode promises a click lands on the word. Nobody has measured how close it lands.

**How.** Time by hand the words of two minutes of a real call, and compare.

**Done when** the median offset is under half a second, or the README says what it really is.

## 4. Fine-tune on your own corrections

**Why.** Every line corrected by hand is a pair: what the model heard, and what was right. It's the one thing here that can't be bought or downloaded. It's your language, your names, your calls, recorded badly.

**Not yet.** It needs around a hundred calls. But **the dataset is collected from day one**, which is why `corrections.jsonl` keeps the before and the after: it can't be rebuilt later.

**Two things to do now, because they can't be done later.** Set aside a group of calls as a test set and **never look at them**. And write down the success criterion **before** training. Without both, the improvement gets measured on what the model has already seen, and it will always look like it worked.

And a rule learned the hard way, on another project: **never decide on a single training run.** The variance between two identical runs changes the result more than almost any real improvement. Use three seeds, and report the mean and the spread.

## 5. Say how many people were on the call

**Why.** The count is right on every meeting measured, but a call where two voices sound alike can still come out as one person. If you know there were three, you should be able to say so.

**Tried, not good enough.** Over-splitting and then merging the closest groups down to the given number scored 27-34% error on AMI, against 12% for counting on its own. So it isn't offered. pyannote's way is to constrain the grouping itself, not to merge after it.

**Done when** giving the right number never scores worse than counting, on both AMI meetings, and the page offers it next to **Separate voices**.

## 6. Recognise the same person across calls

**Why.** *Voice 2* in Monday's call and *Voice 1* in Thursday's may be the same client. Naming them every time is the chore this would remove.

**How.** Keep each named voice's fingerprint, locally, next to the glossary; on a new call, suggest the name when a voice is close enough. Never automatic without a threshold measured on calls where the answer is known: a wrong name is worse than no name.

**Done when** a name suggested is right at least 95% of the time on a held-out set, and the fingerprints can be listed and deleted from the page.

## 7. Linux and macOS launchers

**Why.** The Python code is cross-platform and the tests run on Ubuntu, but only Windows had launchers.

**Done so far.** `install.sh` and `start.sh` do what `Install.bat` and `Start.bat` do. PyTorch goes in first: from the CUDA index on Linux when `nvidia-smi` is there, the plain build otherwise and on macOS, which has no CUDA. Then the rest, and whether the GPU is seen. `./start.sh` passes its arguments to the server. On every push, CI checks both with `bash -n` and `shellcheck`.

**Still open.** Nobody has run them end to end. CI can't: the install downloads gigabytes and needs a GPU. And the author's machine runs Windows.

**Done when** `install.sh` and `start.sh` work on a clean Ubuntu machine with an NVIDIA GPU, checked by someone who isn't the author.
