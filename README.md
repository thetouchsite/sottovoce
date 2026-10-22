# Sottovoce

![sottovoce: your calls, transcribed on your own machine, and honest about what it couldn't hear](docs/images/cover.png)

**Drop a recorded call on a web page. Get back the transcript, a summary, and a map of where the text can't be trusted.** Whisper large-v3 on your own GPU. Nothing leaves your machine.

[Italiano](README.it.md) · [Try it without a GPU](#try-it-in-a-minute-no-gpu) · [What we measured](#what-we-measured) · MIT licence

Built by [TouchSite Software](https://www.touchsitesoftware.it).

![Sottovoce with a fictional 10-minute call open: the call strip, the figures, the summary, the phrases to check and the glossary](docs/images/screenshot.png)
<sub>A fictional demo call. Nothing in these images is real client data.</sub>

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
| 4 · Read | Summary, paragraphs, line by line, the call strip | Click the strip and listen to the part you doubt |

## What makes it different

- **It tells you where not to trust it.** The *call strip* shows the whole recording as one band: where people speak, where it's silent, where an invented phrase was dropped, where a line was corrected. Click anywhere to listen from there.
- **Every default was measured.** On a real call, against the alternatives, with the numbers [below](#what-we-measured), including the four approaches that didn't work.
- **Names are fixed after, not suggested before.** Given to Whisper as a prompt, a glossary made the text *worse*. Here it's a correction table, and it can be applied again to old calls when you add a name.
- **Your corrections are kept.** Every line you fix is saved with its *before* and *after*: the dataset you'd need to fine-tune a model on your own calls.
- **Summaries from your own LLM.** If LM Studio, Ollama or llama-server is running, you get *Decided / To do / Open*, in the language of the call. If none is running, the button just isn't there.
- **Nothing leaves the machine, and nothing is hidden.** The server listens on `127.0.0.1`. The page loads nothing from the internet, not even its font. Every call is a folder of plain files: no database, no account, no telemetry.

![Correcting a line by hand in the line-by-line view, next to the phrases to check and the names found in the call](docs/images/correcting.png)

## Quick start (Windows)

You need an NVIDIA GPU with about 4 GB of free VRAM, and Python 3.10 or newer (tested on Windows 11, Python 3.14, RTX 5090).

```sh
git clone https://github.com/thetouchsite/sottovoce
cd sottovoce
Install.bat
Start.bat
```

`Install.bat` creates a virtual environment and installs PyTorch with CUDA **before** everything else (see [the PyTorch trap](#the-pytorch-trap)). At the end it prints whether it sees your GPU. `Start.bat` opens <http://127.0.0.1:8200>. The first start downloads the model (2.9 GB, once) and loads it into VRAM in about twenty seconds. 27 minutes of call then take about 4 minutes.

Pick the language from the menu next to **Transcribe a recording**, or leave *Detect language*. Close the server with the power button on the page, or `Stop.bat`.

**Linux and macOS:** the Python code is cross-platform, but only Windows 11 has been tested.

```sh
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu130   # match your CUDA
pip install -r requirements.txt
cp glossary.example.txt glossary.txt
python server.py
```

On a Mac there's no CUDA: it runs on the CPU, about ten times slower.

## Try it in a minute, no GPU

The [`examples/`](examples/) folder has three fictional calls, already transcribed, one of them in Italian. Browse them without downloading the model:

```sh
pip install fastapi uvicorn python-multipart
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

Then open <http://127.0.0.1:8200>. The strip, the summary, search, corrections and the glossary all work. Only *Transcribe* is switched off.

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

Summaries come from an LLM that's already running on your machine, spoken to over the OpenAI-compatible API. Sottovoce looks for one on these ports: LM Studio `1234`, Ollama `11434`, llama-server `8080`. Nothing extra to install. And no VRAM held when you don't need it: Whisper takes 3 GB, a useful LLM another 5 to 16.

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

Matching ignores case and respects word boundaries. You can edit the file, or use the glossary view on the page (the book icon), which adds lines without touching your comments. After adding a name, open an older call and press **Apply the glossary again**. Every change goes into `corrections.jsonl` with its before and after, so it can be undone.

`glossary.txt` is git-ignored, because it holds your clients' names. The repo ships `glossary.example.txt`.

## What a call looks like on disk

```text
transcripts/
  2026-10-21_Northpine launch sync/
    Northpine launch sync.m4a    the original, kept next to its transcript
    Northpine launch sync.txt    [mm:ss] text, the source everything else is rebuilt from
    Northpine launch sync.md     paragraphs, to read or paste
    info.json                    duration, language, timings, what was dropped, speech map
    corrections.jsonl            every corrected line, before and after
    summary.md                   if you asked for one
```

`transcripts/` is git-ignored. Your recordings and your clients stay on your machine.

## Command line

```sh
python transcribe.py "Client call.mp4" --language it     # writes .txt and .md next to the file
python summary.py "Client call.md"                       # summarizes with the local LLM
python server.py --port 8300 --data D:\calls --glossary D:\calls\names.txt
python server.py --no-model                              # browse transcripts, no GPU needed
```

`--language` takes a Whisper code (`en`, `it`, `de`…). Leave it out to detect the language.

## Repository layout

| Path | What |
| --- | --- |
| `transcribe.py` | The engine: ffmpeg, Whisper, the clean-up. Also a command-line tool |
| `server.py` | FastAPI, one job at a time (two in parallel slow each other down: 233 s instead of 190) |
| `summary.py` | The local LLM client |
| `app/index.html` | The page: one file, no build step, no framework, 84 KB with its fonts |
| `examples/` | Three fictional calls, to try the interface with `--no-model` |
| `research/` | The scripts behind the numbers above: run several models, compare without a reference |
| `Install.bat`, `Start.bat`, `Stop.bat` | Double-click launchers for Windows |

## Prior art

Whisper wrappers are everywhere. These four are excellent and shaped this one: [whisper.cpp](https://github.com/ggerganov/whisper.cpp), [WhisperX](https://github.com/m-bain/whisperX), [Buzz](https://github.com/chidiwilliams/buzz) and [Vibe](https://github.com/thewh1teagle/vibe). Sottovoce is narrower. It's for recorded business calls, it tells you where the text is unreliable instead of hiding it, and it shows its measurements.

## Roadmap

Word-level timestamps, recording system audio straight from the PC, and fine-tuning on your own corrections. See [ROADMAP.md](ROADMAP.md), with the reasons and how each one will be judged done.

## Contributing

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Especially welcome: the phrases Whisper invents on silence in **your** language (a few lines in `transcribe.py`), and tests on Linux and macOS.

## Licence

[MIT](LICENSE) © 2026 TouchSite Software. Third-party parts keep their licences: Whisper large-v3 weights (Apache-2.0, downloaded from Hugging Face on first use), Public Sans (SIL OFL 1.1, [`app/fonts/OFL.md`](app/fonts/OFL.md)), and ffmpeg (installed by the `imageio-ffmpeg` package, not shipped in this repository).

*Sotto voce* is Italian for "in a low voice". It's what this tool drops, the phrases that fall below the level of speech, and how it works: quietly, on your own machine. It was built for Italian calls first.
