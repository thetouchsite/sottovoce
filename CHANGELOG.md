# Changelog

What changed in each release, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **Invented phrases on long pauses are dropped again.** Silence was measured on the audio Whisper hears, after loudness normalization, and in one pass the normalizer lifts long quiet stretches: the faint hiss of a line, at -50 dB, came out at -19 dB, as loud as speech. The map of speech then saw speech nearly everywhere and no *"Grazie a tutti"* was ever dropped there. Levels are now measured on a copy with one gain for the whole file. On the long-pauses test, subtitle phrases left fell from 18 to 1, and words added from 101 to 47. The call strip draws silence where there is silence.

### Added

- **Word error rate on public data**, with `research/wer.py`: FLEURS Italian, four whole AMI meetings and a set with long pauses, each for Whisper large-v3 alone, large-v3-turbo alone and the whole engine. Results in [Benchmarks](docs/benchmarks.md#transcription-accuracy).

## [1.4.0] - 2026-10-23

Safer on the network, notes and follow-up emails for every call, a summary model built in, and a documentation site.

### Security

- **Cross-site requests and DNS rebinding are refused.** Any page open in the browser could send requests to `127.0.0.1:8200`: a form posted to `/api/shutdown` stopped the server, and with DNS rebinding a page could have read `/api/history`. Now requests that change state are refused when the browser says they come from another site (`Origin`, `Sec-Fetch-Site`), and only the names the server is reached by are accepted in `Host` (`127.0.0.1`, `localhost`, `[::1]` on its port; with `--lan`, also this computer's addresses and name).
- **`info.json` is never read half written.** A transcription rewrites it from its own thread while the page reads the list; a read landing mid-write found an empty file (95 of 300 reads in a stress test, and one failed CI run). It is now written next to it and swapped in one step, and reads wait out the instant of the swap on Windows.
- `SECURITY.md`: what is protected and how, the limits of `--lan` (a PIN over plain http), and how to report a problem privately.

### Added

- **Documentation site** at [thetouchsite.github.io/sottovoce](https://thetouchsite.github.io/sottovoce/), built from `docs/` with MkDocs Material: getting started, how it works, recording, voices, summaries, the glossary, the phone, benchmarks, limitations and troubleshooting. Built on every pull request, published from `main`.
- **A shorter README**, with a comparison against Meetily, Vibe, noScribe, Buzz and WhisperX taken from their READMEs, an FAQ, and a section for companies. The Italian README follows the same structure.
- `research/llm.py`: the built-in summary model's time and memory on the example calls, so those figures can be checked by anyone.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), and `CONTRIBUTING.md` rewritten: setup, tests, measurements, docs, commit style.
- **Notes**, first in the Download menu: one Markdown file for the client's folder, with date, length and who took part, the summary, and the whole transcript with names and minutes, its headings in the language of the call.
- **A small LLM built in.** With no LM Studio or Ollama running, summaries and follow-up emails are written by Qwen3 4B Instruct (Apache-2.0), downloaded the first time (8 GB), loaded on the GPU when asked and unloaded after ten minutes unused. Nothing to install for whoever clones the repo. A running LLM server is still used first. `--no-llm` turns it off.
- **The follow-up email.** Under the transcript, **Write the follow-up** asks the local LLM for the email to send after the call, from you to the others by name, in the call's language and tone: what was decided, next steps and who takes them, what is open, with `[placeholders]` instead of invented details. Edit it in place (saved), copy it, share it from a phone, or write it again. Kept as `followup.md`, and dropped when the lines change, like the summary.

## [1.3.0] - 2026-10-23

Use it from your phone, in Italian, and decide when a recording is transcribed.

### Added

- **The page in Italian.** An **IT / EN** switch in the side bar, English by default and remembered. Only the interface changes: transcripts, summaries and the names of calls and people are marked as data and never translated.
- **Add first, transcribe when you choose.** A file dropped on the page, or onto the list of calls, is added and waits there tagged *Not transcribed*: open it to listen to it, rename it, pick the language and the options, and press **Transcribe**, with an estimate of how long it takes. The home lists what is waiting, with **Transcribe all**. The state lives on disk, so the list stays true after a reload, and a transcription cut short by a restart goes back to waiting. A failed one keeps its recording and can be tried again (before, the upload was deleted).
- **Rename and delete** from a call's **⋯** menu, transcribed or not. Renaming moves the folder and its files; deleting moves the folder to `transcripts/_deleted/`, never erases it.
- `/api/uploads`, `/api/transcribe/{name}`, `/api/history/{name}/rename` and `DELETE /api/history/{name}`. `/api/transcribe` still adds and transcribes in one call, for scripts.
- `--lan` opens the page to other devices on your network, to read, correct and send recordings from a phone. Off by default. Other devices give a **PIN** once and are remembered for a year (a signed cookie); the computer itself is never asked. The PIN is made up the first time and kept in `.lan-pin` (git-ignored), or chosen with `--pin`; five wrong tries lock a device out for 15 minutes. `Start.bat` now passes its arguments on, like `start.sh`.

### Changed

- **Two tracks: the end of a turn stays with whoever said it.** Each Whisper line's words are now laid over the moments someone actually speaks in it, instead of being spread evenly, pause included. On a fast test call in Meet, words given to the wrong person went from 34 of 136 to 19. Still not good enough: on real two-track calls built from AMI headset microphones (`research/two_tracks.py`) about 10% of words go to the wrong person, and fast, overlapping exchanges are the worst. See the roadmap.
- **The page on a phone**, redone for a thumb instead of squeezed from the desktop. The home starts with **Send a recording**; the choices fold into one line that says what is set; the latest calls are a list. On a call, shortcuts to Transcript, Voices, To check and Glossary sit under the title, the figures take two short rows, the tabs and the player stay at the top while the text scrolls, and time and speaker sit above each line so the text has the whole width. Fields are 16 px (iOS no longer zooms in), buttons are thumb-sized, the list drawer closes when you tap beside it, and the stop button is hidden: a server stopped from a phone can't be started from there. Tapping the call strip now scrolls the text to that moment on a phone too.
- **Correcting a line without a mouse.** A **Correct** button next to Copy turns taps on a line into editing it, with **Save** and **Cancel** buttons (Esc and Enter still work, and so does double-click).
- The choices made before transcribing (language, **Separate voices**, **Precise word timings**) are now a **Before you start** panel above files and recording, each with a switch and a line saying what it does, instead of two small checkboxes whose explanation was only in a tooltip.
- On a call, the **Voices** panel comes first in the right column, so separating the voices of a call already transcribed is in view, with a progress bar while it listens. The button is called **Separate voices**, like the option, instead of *Tell the voices apart*.

## [1.2.0] - 2026-10-22

Tell the voices apart, on any recording, with no account to create.

### Added

- **Separate voices.** Every line says *Voice 1*, *Voice 2*…, numbered in the order they first speak, for any recording, not only calls recorded here. Tick it before transcribing, press **Tell the voices apart** on a call already transcribed, or pass `--voices`. The number of people is counted, not asked.
- **No Hugging Face token.** pyannote's segmentation-3.0 (MIT, as redistributed by sherpa-onnx) and a 3D-Speaker ERes2Net voice-fingerprint model (Apache-2.0), downloaded from GitHub on first use (32 MB) and checked against a fixed SHA-256. They run on the CPU, about 2.5 seconds per minute of audio.
- **Measured.** On a public AMI meeting never seen while tuning: 12.6%, 11.8% and 11.9% error (DER) with four, three and two people, all counted right. End to end with Whisper, 96% of words get the right voice. `research/voices_ami.py` reproduces it.
- **Names for the voices**, in a Voices panel next to the transcript, with how long each one talks. They're kept in `info.json`, not in the text, and used in the reading views, copy, every download and the summary. The same panel names *You* and *Them* on two-track calls.
- On two tracks, *You* stays a measurement and only the call's side is split into voices.
- **Linux and macOS launchers**, `install.sh` and `start.sh`, checked with `bash -n` and `shellcheck` in CI. Not yet run end to end on a clean machine: see the roadmap.
- A demo GIF and an icon for the README, issue and pull request templates, and this changelog.
- The Northpine example is now a three-voice call.

### Changed

- The speaker column is wider (72 px, long names cut with an ellipsis), and each voice has its own pale colour; the accent stays yours.
- Downloaded `.txt` files carry the names you gave; the `.txt` in the folder keeps the labels.

## [1.1.0] - 2026-10-22

Record calls from the page, and know who spoke.

### Added

- **Record a call** from a browser tab (Google Meet, Zoom, Teams on the web). Your microphone and the call go on two separate tracks, sent to the server every five seconds: an interrupted recording is offered again, not lost.
- **Who spoke.** Every word is assigned to *You* or *Them* from the two tracks, with no speaker-recognition model. Lines split where the speaker changes, and the summary is told who said each line.
- **Word timings.** Click a word to play from it. By default each line's time is shared among its words, at no extra cost. **Precise word timings** (or `--precise`) take them from Whisper's own alignment, at twice the time: 395 s instead of 200 on a 27-minute call, same quality.
- **Several files at once**, queued one after the other.
- **Downloads** as `.srt`, `.vtt` and `.json`, besides `.md` and `.txt`.
- **Tests and CI.** Engine, API and page, on the fictional examples, no GPU needed. Every push runs on Ubuntu and Windows, Python 3.10 and 3.14.
- A fourth fictional call in `examples/`, recorded on two tracks.

### Changed

- The page opens on **New transcription** (drop files, or record a call) instead of on the last call. A breadcrumb, the logo and Esc lead back to it.
- Corrections and the glossary realign the word timings instead of dropping them.
- Calls transcribed with 1.0 open as before; their words become clickable with estimated timings.

## [1.0.0] - 2026-10-22

The first release. Local transcription for recorded business calls, with Whisper large-v3 on your own GPU. Nothing leaves your machine.

### Added

- Drop a recording on the page: the transcript in paragraphs and line by line, with timestamps.
- Whisper large-v3 in its own long-form mode, with the anti-hallucination thresholds set, and the audio normalized before transcribing.
- Phrases Whisper invents on silence (*"Thanks for watching"*, *"Subtitles by…"*) are dropped only where the audio is 12 dB below speech, and each removal is reported with its timestamp.
- A name glossary applied after transcription, not given to Whisper as a prompt, and appliable again to old calls.
- The call strip: the whole recording as one band, with speech, silence, dropped phrases and corrections. Click to listen from there.
- Summaries (*Decided / To do / Open*) from a local LLM, if LM Studio, Ollama or llama-server is running.
- Hand corrections kept with their before and after in `corrections.jsonl`, as a future fine-tuning set.
- Language detection, or a remembered choice; search across every call.
- `--no-model`, to browse transcripts without a GPU, and three fictional calls in `examples/` to try it on.
- `Install.bat`, `Start.bat` and `Stop.bat` for Windows. PyTorch is installed first, from the CUDA index.
- An Italian README.

[Unreleased]: https://github.com/thetouchsite/sottovoce/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/thetouchsite/sottovoce/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/thetouchsite/sottovoce/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/thetouchsite/sottovoce/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/thetouchsite/sottovoce/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/thetouchsite/sottovoce/releases/tag/v1.0.0
