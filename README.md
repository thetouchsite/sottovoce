# Sottovoce

![sottovoce: your calls, transcribed on your own machine, and honest about what it couldn't hear](docs/images/cover.png)

**Drop a recorded call on a web page, or record the call from it. Get back the transcript, who said what, a summary, and a map of where the text can't be trusted.** Whisper large-v3 on your own GPU. Nothing leaves your machine.

[![tests](https://github.com/thetouchsite/sottovoce/actions/workflows/tests.yml/badge.svg)](https://github.com/thetouchsite/sottovoce/actions/workflows/tests.yml)

[Italiano](README.it.md) · [Try it without a GPU](#try-it-in-a-minute-no-gpu) · [Record a call](#record-a-call) · [Tell voices apart](#tell-voices-apart) · [What we measured](#what-we-measured) · MIT licence

Built by [TouchSite Software](https://www.touchsitesoftware.it).

![A 24-second tour of Sottovoce on fictional calls: switching on Separate voices on the home screen, a call's summary, a click on the call strip that jumps to that moment in the text, the line-by-line view with three voices in three colours, naming them Maya, Daniel and Priya in the Voices panel, the lines now showing the names, a call recorded on two tracks with You and Them, and back to the start](docs/images/demo.gif)
<sub>Fictional calls from `examples/`: nothing in these images is real client data. Made with `--no-model`, which is why transcription shows as off.</sub>

## Why

Transcription tools hand you a block of text that looks equally confident everywhere. On a real business call, recorded with a phone on the desk, it isn't. Three mistakes cost the most, and they're the ones you can't see:

- **Sentences nobody said.** On silence, Whisper writes the YouTube subtitles it was trained on: *"Thanks for watching"*, *"Subtitles by the Amara.org community"*.
- **Names nobody can find again.** Your client's company comes out spelled five different ways, so search misses it and the summary garbles it.
- **No way to check.** You can't tell which part of the text to doubt without listening to the whole call again.

Sottovoce fixes the first two, and shows you where the third one is.

| Step | What happens | Why it's there |
| --- | --- | --- |
| 1 · Prepare | 16 kHz mono, loudness normalized, speech map measured | Whisper gets **35% faster** on normalized phone audio |
| 2 · Transcribe | Whisper large-v3, long-form, anti-hallucination thresholds | Chunking produced the same words **40 times in a row** |
| 3 · Clean up | Subtitle phrases dropped *only* where the audio is 12 dB below speech; glossary applied | A real "thank you all" stays, invented ones go |
| 4 · Read | Summary, paragraphs, line by line, the call strip, words you can click | Click the strip or a word and listen to the part you doubt |

## What makes it different

- **It tells you where not to trust it.** The *call strip* shows the whole recording as one band: where people speak, where it's silent, where an invented phrase was dropped, where a line was corrected. Click anywhere to listen from there.
- **It records the call too, and knows who spoke.** Record a Google Meet, Zoom or Teams call straight from the page: your microphone and the call's tab go on two separate tracks, so the transcript says *You* and *Them* without a speaker-recognition model.
- **It tells voices apart, with no account to create.** Tick **Separate voices** and every line says *Voice 1*, *Voice 2*…; name them once and the names follow into downloads and the summary. Two small open models on the CPU, fetched once from GitHub: no Hugging Face token, no licence to accept. 12% error on public meetings, with the number of people counted right on every one.
- **Every default was measured.** On a real call, against the alternatives, with the numbers [below](#what-we-measured), including the four approaches that didn't work.
- **Names are fixed after, not suggested before.** Given to Whisper as a prompt, a glossary made the text *worse*. Here it's a correction table, and it can be applied again to old calls when you add a name.
- **Your corrections are kept.** Every line you fix is saved with its *before* and *after*: the dataset you'd need to fine-tune a model on your own calls.
- **Summaries from your own LLM.** If LM Studio, Ollama or llama-server is running, you get *Decided / To do / Open*, in the language of the call. If none is running, the button just isn't there.
- **Nothing leaves the machine, and nothing is hidden.** The server listens on `127.0.0.1`. The page loads nothing from the internet, not even its font. Every call is a folder of plain files: no database, no account, no telemetry.

![Correcting a line by hand in the line-by-line view of a two-track call, with You and Them on every line, next to the Voices panel where they can be named and the phrases to check](docs/images/correcting.png)

## Quick start (Windows)

You need an NVIDIA GPU with about 4 GB of free VRAM, and Python 3.10 or newer (tested on Windows 11, Python 3.14, RTX 5090; the test suite runs on 3.10 and 3.14).

```sh
git clone https://github.com/thetouchsite/sottovoce
cd sottovoce
Install.bat
Start.bat
```

`Install.bat` creates a virtual environment and installs PyTorch with CUDA **before** everything else (see [the PyTorch trap](#the-pytorch-trap)). At the end it prints whether it sees your GPU. `Start.bat` opens <http://127.0.0.1:8200>. The first start downloads the model (2.9 GB, once) and loads it into VRAM in about twenty seconds.

![The New transcription screen: the choices that apply to everything at the top (language, Separate voices, Precise word timings), drop files on the left, record a call on the right, the latest calls below](docs/images/home.png)

The page opens on **New transcription**: drop one or more files on the left (or onto the list of calls), or record a call on the right. A file you add **waits** in the list, tagged *Not transcribed*: open it to listen, rename it, choose how, and press **Transcribe**. 27 minutes of call take about 4 minutes. Every call can be renamed or deleted from its **⋯** menu; deleting moves its folder to `transcripts/_deleted/`, so a wrong tap can be undone from the file explorer. Above both, **Before you start** holds the three choices that apply to either: the language (detected, or picked from the menu), **Separate voices** and **Precise word timings**, each with a line saying what it does. They're remembered. The **IT** button at the bottom of the side bar switches the page to Italian (the calls themselves are never translated). Close the server with the power button, or `Stop.bat`.

**Linux and macOS:** `./install.sh`, then `./start.sh`. They do what the Windows launchers do: PyTorch first, from the CUDA index on Linux when `nvidia-smi` is there, then the rest, then whether the GPU is seen. `./start.sh` passes its arguments to the server, so `./start.sh --no-model` works. On GitHub they're checked for syntax and with `shellcheck` on every push, but not run end to end there: the install downloads gigabytes and needs a GPU. If you run them on a clean machine, tell us how it went (see the [roadmap](ROADMAP.md)). If they fail, these are the steps they take:

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu130   # match your CUDA
pip install -r requirements.txt
cp glossary.example.txt glossary.txt
python server.py
```

On a Mac there's no CUDA: it runs on the CPU, about ten times slower.

### From your phone

`python server.py --lan` (or `Start.bat --lan`, `./start.sh --lan`) makes the page reachable from other devices on the same network: it prints the address to open on your phone. From there you can read, listen, search, correct, name voices, and send a recording from the phone to be transcribed on the PC. Recording a call works only on the computer itself. **There's no password**: anyone on that Wi-Fi can read your calls, so use it at home or in the office, never on a public network. Without `--lan` the server answers only on `127.0.0.1`.

## Try it in a minute, no GPU

The [`examples/`](examples/) folder has four fictional calls, already transcribed: one in Italian, one recorded on two tracks. Browse them without downloading the model:

```sh
pip install fastapi uvicorn python-multipart
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

Then open <http://127.0.0.1:8200>. The strip, the summary, who spoke (two tracks, and three named voices in the Northpine call), search, corrections, downloads and the glossary all work. Only transcribing and recording are switched off.

## Record a call

On **New transcription**, give the call a name and press **Start recording**. The browser asks which tab to share: pick the tab with your call and leave **Also share tab audio** on. Talk. When the call ends, press **Stop and transcribe**.

- **Two tracks.** Your microphone is recorded on the left channel, the call's tab on the right. The call's track never carries your voice, because the meeting app doesn't send it back to you. So *who spoke* is a measurement: each word goes to the track that is louder than usual at that moment. Lines are split where the speaker changes.
- **Clean audio.** The call's sound is captured as the browser plays it, not through a phone on the desk. That was the root of most of the problems measured below.
- **Nothing is lost if the page closes.** The recording reaches the server every five seconds. If the tab is closed, the browser crashes or the laptop sleeps, the page offers the interrupted recording again the next time: transcribe it, or delete it.
- **Where it works.** Chrome or Edge on a computer, for calls that run in a browser tab (Google Meet, Zoom and Teams on the web). Firefox and Safari can't capture another tab's sound. Calls in desktop apps need system-wide capture, which is on the [roadmap](ROADMAP.md).
- **Use headphones**, or your microphone also picks up the others. **Tell the others you're recording**: depending on where you are, you may have to.

## Tell voices apart

On a call with several people, tick **Separate voices** before transcribing, or open a call that's already transcribed and press **Separate voices** at the top of its right column (no need to transcribe again). Every line gets *Voice 1*, *Voice 2*…, numbered in the order they first speak. Name them in the **Voices** panel next to the transcript: the names appear in the three reading views, in what you copy, in every download and in the summary. The `.txt` keeps the labels and `info.json` keeps the names, so a wrong name is undone by changing one field.

- **No account, no gate.** The usual choice, [pyannote](https://github.com/pyannote/pyannote-audio), asks for a Hugging Face token and for accepting its terms before it downloads anything. Sottovoce uses the same segmentation model, pyannote segmentation-3.0 (MIT), as redistributed by [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), with a [3D-Speaker](https://github.com/modelscope/3D-Speaker) ERes2Net voice-fingerprint model (Apache-2.0). Both come from GitHub on first use, 32 MB in all, and are checked against a fixed SHA-256 before they're used.
- **On the CPU.** About 2.5 seconds per minute of audio. The GPU stays with Whisper.
- **You don't say how many people there were.** They're counted.
- **On two tracks**, *You* stays a measurement: only the call's side is split into voices.

### How well it works

Measured on two public [AMI](https://groups.inf.ed.ac.uk/ami/corpus/) meetings, where every speaker is annotated. The threshold was chosen on one meeting and graded on the other, which it never saw. Each meeting has four people; for three and two, the others are muted where they speak alone, so the room and the microphones stay the same.

| people on the call | 4 | 3 | 2 |
| --- | --- | --- | --- |
| error (DER) | 12.6% | 11.8% | 11.9% |
| people counted | 4 of 4 | 3 of 3 | 2 of 2 |

DER adds up missed speech, false alarms and speech given to the wrong person, over all the speech, with the usual 0.25 s tolerance where turns change. It's the standard measure, and published pipelines land roughly between 15% and 25% on AMI. Reproduce it with `python research/voices_ami.py`.

End to end, transcribed by Whisper with voices on, **96% of the words** where one person is speaking got the right voice (14 minutes, three people). On the real 27-minute call from the measurements below, it found the two people in 36 seconds.

**Which fingerprints.** Five models were tried the same way. NVIDIA TitaNet-large scored the same on AMI (12.3% / 11.1% / 12.3%), but on the real call it gave the client's questions to the consultant. WeSpeaker ResNet34 and ResNet293 and 3D-Speaker CAM++ were clearly worse with this grouping.

**Grouping mattered more than the model.** Grouping every fingerprint by average distance, the first version merged three people into one: a few noisy fingerprints from short bursts formed groups of their own. Now only fingerprints from at least a second of clean speech are grouped, and the short ones join the nearest person afterwards.

**Where it goes wrong.** Two similar voices on the same phone can merge into one. A short "yes" or "okay" can go to the wrong person. Someone who talks for less than about 15 seconds in all joins the nearest voice instead of getting their own: on short calls where one person does most of the talking, expect fewer voices than people. When two people talk over each other, the overlapping words go to one of them. And the number of people can't be set by hand yet: see the [roadmap](ROADMAP.md).

## What we measured

These numbers come from **one real 27-minute business call in Italian**, recorded with a phone on a desk. It's one call, not a benchmark suite. But it's the kind of audio this tool is for, and public leaderboards measure studio-read speech instead.

There was no hand-typed reference transcript, so word error rate couldn't be computed. The metric is the **share of words that don't exist in the language** (checked with [`wordfreq`](https://github.com/rspeer/wordfreq)). A hallucinating model doesn't produce noise: it produces plausible words that aren't real. The metric misses a real word put in the wrong place, but an invented word is the mistake that stops a reader. The scripts are in [`research/`](research/).

### Which model

| | non-existent words | time on 27 min | timestamps | invented phrases |
|---|---|---|---|---|
| **whisper-large-v3** | **1.2%** | 168 s | yes | 3 |
| whisper-large-v3-turbo | 2.2% | 50 s | yes | 4 |
| parakeet-tdt-0.6b-v3 | 2.8% | 355 s | no | 0 |

The gap shows on proper nouns. One company name came out of Parakeet spelled eight different ways, and out of large-v3 almost always the same way. Turbo is three times faster and makes twice the mistakes: on 27 minutes it saves two minutes.

**Mind the sample size.** On the first 5 minutes the three models looked even (1.6% / 2.2% / 2.1%). The gap only appeared on 2,500 words instead of 600.

### Three things that mattered more than the model

1. **Normalize loudness before transcribing.** Phone audio has one voice near the mic and the others from the speaker: mean -29.8 dB, peaks at -0.9. Normalized, the text is the same, but Whisper gets **35% faster**, because on a weak signal it discards and retries uncertain windows.
2. **Use Whisper's own long-form mode, not `chunk_length_s`.** Chunking into 30-second slices produced timestamps that went backwards, and the same three words **forty times in a row**.
3. **Set the anti-hallucination thresholds** (`temperature` fallback, `compression_ratio_threshold`, `logprob_threshold`, `no_speech_threshold`, `condition_on_prev_tokens=False`). Without them, a repetition feeds itself from one window into the next.

The right model configured badly gives worse results than the wrong model configured well.

### Removing invented phrases: five attempts, four failures

| approach | non-existent words | invented phrases |
|---|---|---|
| nothing | 31 (1.2%) | 3 |
| cut all silence before transcribing | 42 (1.7%) | 0 |
| cut only pauses over 3 s | 47 (1.8%) | 0 |
| transcribe speech regions separately | 30 (1.2%) | 2 |
| **drop subtitle phrases only where the audio is 12 dB below speech** | **30 (1.2%)** | **0** |

What this taught us:

- **Whisper needs the silence.** Cutting it out (the WhisperX approach) removes the hallucinations, but it also takes away the cue for where words end. The damage comes from the cut itself, however much you cut.
- **`silencedetect` doesn't measure loudness.** It looks for silent stretches of a minimum length, and one crackle breaks the count. It reported "100% speech" at a point measuring -43.9 dB.
- **A file's average loudness isn't its speech level.** The silence drags the average down and makes the threshold too lenient. The reference has to be measured only where people speak.

### Names: correct after, don't prompt before

Whisper accepts an initial prompt (`prompt_ids`) to tell it which names to expect. That's the documented way, so we tried it:

| | segments | non-existent words |
|---|---|---|
| no prompt | 552 | 44 (1.7%) |
| glossary as prompt | **166** | **67 (2.6%)** |

The prompt destabilizes the model. It sends it into long runs (552 segments collapse to 166) and makes it hunt for those names everywhere. So the glossary is a deterministic correction table applied to the output. On the test call it fixed 27 occurrences of five names.

### Word timings: precise, or twice as fast

Whisper can time every word itself, with no second model to download. Same call:

| | time | non-existent words | word timings |
|---|---|---|---|
| **default** | **200 s** | 29 of 2,504 (1.2%) | each line's time shared among its words by length |
| precise word timings | 395 s | 29 of 2,500 (1.2%) | from Whisper's own alignment |

Same quality, twice the time: precise timings need the model's attention weights, and that switches off its fast attention kernel. So the default keeps the speed, and a click on a word lands near it. Tick **Precise word timings** (or `--precise`) when it has to land on it. The text isn't identical word for word between the two modes, but the quality is the same.

### The summary: the backend, not the model

Same GPU, same 3,760-token transcript:

| setup | prompt processing | full summary |
|---|---|---|
| llama.cpp **Vulkan** build, 9B model (Q4) | 6.8 tokens/s, measured | about 9 minutes, projected |
| llama.cpp **CUDA** build via LM Studio, Gemma 4 E4B (Q4) | not reported | **16 seconds**, measured |

The two runs used different models, so this isn't a clean comparison. But a 9B model is roughly twice as slow as a 4B one, not thirty times. The rest is the build: the RTX 5090 is `sm_120`, and the Vulkan build doesn't use it properly. It doesn't fail, it just crawls and says nothing. If summaries take minutes, suspect the build first.

## The PyTorch trap

Install `transformers` on its own and pip pulls the default PyTorch from PyPI. On RTX 50-series cards (Blackwell, `sm_120`) that build doesn't see the GPU. Everything works, on the CPU, ten times slower, and nothing tells you. Install PyTorch **first**, from the CUDA index, which is what `Install.bat` does. Check with:

```sh
.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

It should print a version ending in `+cu130` and `True`.

## Summaries

Summaries come from an LLM that's already running on your machine, spoken to over the OpenAI-compatible API. Sottovoce looks for one on these ports: LM Studio `1234`, Ollama `11434`, llama-server `8080`. Nothing extra to install. And no VRAM held when you don't need it: Whisper takes 3 GB, a useful LLM another 5 to 16. When who spoke is known (two tracks, or voices told apart) the model is told who said each line, with the names you gave, so *To do* can say who does what.

With LM Studio:

```sh
%USERPROFILE%\.lmstudio\bin\lms.exe server start
```

A summary is saved as `summary.md` in the call's folder and read from disk the next time. **Redo** writes a new one. Applying the glossary again deletes the summary, because it was written on the old text.

## The glossary

```text
# glossary.txt
Northpine <- North pine, Nord pine
Trailhead <- Trail head
```

Matching ignores case and respects word boundaries. You can edit the file, or use the glossary view on the page (the book icon), which adds lines without touching your comments. After adding a name, open an older call and press **Apply the glossary again**. Every change goes into `corrections.jsonl` with its before and after, so it can be undone, and the word timings follow the corrected text.

`glossary.txt` is git-ignored, because it holds your clients' names. The repo ships `glossary.example.txt`.

## Downloads

Every call downloads as `.md` (paragraphs, to read or paste), `.txt` (line by line, with timestamps), `.srt` and `.vtt` (subtitles), and `.json` (lines, speakers and word timings, for other programs). The last three are written from the transcript as it is now, corrections included. Voices you named appear by name in all of them.

## What a call looks like on disk

```text
transcripts/
  2026-10-21_Northpine launch sync/
    Northpine launch sync.m4a    the original, kept next to its transcript
    Northpine launch sync.txt    [mm:ss] text, [mm:ss] [Me] text or [mm:ss] [Voice 2] text: the source of everything else
    Northpine launch sync.md     paragraphs, to read or paste
    words.json                   when each word was said, line by line
    info.json                    duration, language, timings, what was dropped, speech map, voice names
    corrections.jsonl            every corrected line, before and after
    summary.md                   if you asked for one
```

`transcripts/` is git-ignored. Your recordings and your clients stay on your machine.

## Command line and API

```sh
python transcribe.py "Client call.mp4" --language it --formats txt,md,srt   # next to the file
python transcribe.py "Recording.webm" --two-tracks --precise
python transcribe.py "Team meeting.m4a" --voices                             # Voice 1, Voice 2…
python summary.py "Client call.md"                                          # with the local LLM
python server.py --port 8300 --data D:\calls --glossary D:\calls\names.txt
python server.py --no-model                                                 # browse, no GPU
```

`--language` takes a Whisper code (`en`, `it`, `de`…). Leave it out to detect the language.

Everything the page does goes through a small HTTP API, documented at <http://127.0.0.1:8200/docs> while the server runs: add a file from your own scripts (`/api/uploads`, then `/api/transcribe/{name}`; or `/api/transcribe` to do both at once), read a call as JSON, search, correct, rename, delete. That reference page is FastAPI's own and loads Swagger UI from a CDN when you open it; the app's page doesn't.

## Development

```sh
pip install -r requirements-dev.txt
pytest tests/test_engine.py tests/test_api.py      # engine and API, no GPU, about a second

pip install playwright && playwright install chromium
pytest tests/test_page.py                          # the page in a real browser
```

The tests run on the fictional calls in `examples/`, with the server started `--no-model`, on every push: Ubuntu and Windows, Python 3.10 and 3.14. Transcription itself needs a GPU and is checked by hand. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository layout

| Path | What |
| --- | --- |
| `transcribe.py` | The engine: ffmpeg, Whisper, the clean-up, who spoke, the formats. Also a command-line tool |
| `voices.py` | Telling voices apart: the two models, their download and checksums, the grouping |
| `server.py` | FastAPI, one job at a time (two in parallel slow each other down: 233 s instead of 190) |
| `summary.py` | The local LLM client |
| `app/index.html` | The page: one file, no build step, no framework, its fonts next to it |
| `examples/` | Four fictional calls, to try the interface with `--no-model` |
| `tests/` | Engine, API and page tests; they run on the examples |
| `research/` | The scripts behind the numbers above: run several models, compare without a reference, grade the voices on AMI |
| `Install.bat`, `Start.bat`, `Stop.bat` | Double-click launchers for Windows |
| `install.sh`, `start.sh` | The same, for Linux and macOS |

## Prior art

Whisper wrappers are everywhere. These four are excellent and shaped this one: [whisper.cpp](https://github.com/ggerganov/whisper.cpp), [WhisperX](https://github.com/m-bain/whisperX), [Buzz](https://github.com/chidiwilliams/buzz) and [Vibe](https://github.com/thewh1teagle/vibe). Sottovoce is narrower. It's for business calls, recorded or recorded here, it tells you where the text is unreliable instead of hiding it, and it shows its measurements.

## Roadmap

Recording calls from desktop apps, telling the number of people when you know it, recognising the same person across calls, and fine-tuning on your own corrections. See [ROADMAP.md](ROADMAP.md), with the reasons and how each one will be judged done. What changed in each release is in [CHANGELOG.md](CHANGELOG.md).

## Contributing

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Especially welcome: the phrases Whisper invents on silence in **your** language (a few lines in `transcribe.py`), and a run of `./install.sh` and `./start.sh` on a clean Linux machine with an NVIDIA GPU.

## Licence

[MIT](LICENSE) © 2026 TouchSite Software. Third-party parts keep their licences: Whisper large-v3 weights (Apache-2.0, downloaded from Hugging Face on first use), pyannote segmentation-3.0 (MIT) and 3D-Speaker ERes2Net (Apache-2.0) for telling voices apart (downloaded from the sherpa-onnx releases on first use), sherpa-onnx (Apache-2.0), Public Sans (SIL OFL 1.1, [`app/fonts/OFL.md`](app/fonts/OFL.md)), and ffmpeg (installed by the `imageio-ffmpeg` package, not shipped in this repository).

*Sotto voce* is Italian for "in a low voice". It's what this tool drops, the phrases that fall below the level of speech, and how it works: quietly, on your own machine. It was built for Italian calls first.
