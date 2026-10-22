# Changelog

What changed in each release, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Add first, transcribe when you choose.** A file dropped on the page, or onto the list of calls, is added and waits there tagged *Not transcribed*: open it to listen to it, rename it, pick the language and the options, and press **Transcribe**, with an estimate of how long it takes. The home lists what is waiting, with **Transcribe all**. The state lives on disk, so the list stays true after a reload, and a transcription cut short by a restart goes back to waiting. A failed one keeps its recording and can be tried again (before, the upload was deleted).
- **Rename and delete** from a call's **⋯** menu, transcribed or not. Renaming moves the folder and its files; deleting moves the folder to `transcripts/_deleted/`, never erases it.
- `/api/uploads`, `/api/transcribe/{name}`, `/api/history/{name}/rename` and `DELETE /api/history/{name}`. `/api/transcribe` still adds and transcribes in one call, for scripts.
- `--lan` opens the page to other devices on your network, to read, correct and send recordings from a phone. Off by default, and the server says at every start that there is no password. `Start.bat` now passes its arguments on, like `start.sh`.

### Changed

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

[Unreleased]: https://github.com/thetouchsite/sottovoce/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/thetouchsite/sottovoce/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/thetouchsite/sottovoce/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/thetouchsite/sottovoce/releases/tag/v1.0.0
