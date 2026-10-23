# Getting started

## What you need

- **An NVIDIA GPU.** Whisper large-v3 runs on it in half precision; the built-in summary model needs about 8 GB more ([measured](benchmarks.md#the-built-in-summary-model)). Without an NVIDIA GPU it runs on the CPU, much slower.
- **Nothing else to install first.** The installer brings its own Python. From a clone, you need Python 3.10 or newer.
- **Chrome or Edge**, to record calls from the browser.
- About **3 GB** of disk for Whisper, and **8 GB** more if you use the built-in summary model.

## Install

=== "Windows"

    In PowerShell:

    ```powershell
    irm https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.ps1 | iex
    ```

    Then open **Sottovoce** from the Start menu or the desktop.

=== "Linux and macOS"

    In a terminal:

    ```sh
    curl -fsSL https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.sh | bash
    ```

    Then open **Sottovoce** from the applications menu (Linux) or `~/Applications` (macOS), or run the launcher the installer names at the end. A Mac needs Apple silicon: PyTorch no longer ships for Intel Macs.

=== "From a clone"

    For development, or to follow `main`. You need Python 3.10 or newer.

    ```sh
    git clone https://github.com/thetouchsite/sottovoce
    cd sottovoce
    python -m venv .venv
    # Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
    python installer/gpu.py                  # which PyTorch: cu130, cu126, cpu or pypi
    pip install torch --index-url https://download.pytorch.org/whl/cu130   # the one it said
    pip install -r requirements.txt
    cp glossary.example.txt glossary.txt
    python server.py
    ```

    PyTorch goes first, from its own index: see [the PyTorch trap](troubleshooting.md#the-gpu-is-not-used). On a Mac, `pip install torch` from PyPI. The calls are kept in `transcripts/` inside the clone. `installer/start.cmd` (Windows) and `installer/start.sh` start the server and open the page once it answers.

The first start downloads Whisper large-v3 (2.9 GB, once) and loads it on the GPU. After that the server keeps it loaded: each new file only pays for its own transcription.

### What the installer does

1. Downloads [uv](https://github.com/astral-sh/uv) (MIT or Apache-2.0) at a fixed version, checked against its SHA-256.
2. Downloads the latest release of Sottovoce.
3. With uv, installs Python 3.12 and a virtual environment, all inside the program folder.
4. Asks `installer/gpu.py` which PyTorch sees your GPU: CUDA 13.0 for RTX 20 to RTX 50 and GTX 16 with a driver 580 or newer, CUDA 12.6 for older cards or drivers, the CPU build without an NVIDIA GPU. It installs that one first ([why](troubleshooting.md#the-gpu-is-not-used)), then the rest.
5. Creates the folder for your calls, the shortcuts and, on Windows, the entry in **Settings → Apps**.

| | Windows | Linux | macOS |
| --- | --- | --- | --- |
| The program | `%LOCALAPPDATA%\Programs\Sottovoce` | `~/.local/share/sottovoce` | `~/Library/Application Support/Sottovoce` |
| Your calls and the glossary | `%USERPROFILE%\Sottovoce` | `~/Sottovoce` | `~/Sottovoce` |
| The models | `%USERPROFILE%\.cache\huggingface` | `~/.cache/huggingface` | `~/.cache/huggingface` |

Your calls are not in *Documents* on purpose: on many Windows computers OneDrive keeps a copy of *Documents* in the cloud, and the calls must not leave the machine.

### Updating and removing

**Update:** stop Sottovoce, then run the same install command again. Only what changed is downloaded; your calls, the voice models and the PIN your phone knows stay.

**Remove:** on Windows, **Settings → Apps → Sottovoce → Uninstall**. On Linux and macOS, run `uninstall.sh` in the program folder. Your calls stay. The models (about 11 GB) stay in the Hugging Face cache: delete it too if nothing else uses it.

## Try it without a GPU

The `examples/` folder has four fictional calls, already transcribed: one in Italian, one recorded on two tracks, one with three named voices. Browse them without downloading anything:

```sh
pip install -r requirements-dev.txt
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

Open <http://127.0.0.1:8200>. Everything works except transcribing and recording.

## Your first call

![The New transcription screen](images/home.png)

1. **Choose how**, in *Before you start*: the language (or let it be detected), **Separate voices**, **Precise word timings**. The choices are remembered.
2. **Add a recording.** Drop it on the page or onto the list of calls. It waits there, tagged *Not transcribed*: open it to listen, rename it, then press **Transcribe**. Or [record a call](recording.md) from the page.
3. **Read it.** Summary, paragraphs, line by line. Click a word to hear it. The call strip at the top shows where the text needs a look.

Any format ffmpeg can open works: mp4, m4a, mp3, wav, ogg, opus, 3gp, webm. The **IT** button at the bottom of the side bar switches the page to Italian. Stop the server with the power button at the bottom of the side bar, or by closing its window.

## Command line

```sh
python transcribe.py "Client call.mp4" --language it --formats txt,md,srt   # writes next to the file
python transcribe.py "Recording.webm" --two-tracks --precise
python transcribe.py "Team meeting.m4a" --voices
python server.py --port 8300 --data D:\calls --glossary D:\calls\names.txt
python server.py --no-model                                                 # browse only
python server.py --lan                                                      # open to your phone, with a PIN
```

The page talks to the server through a small HTTP API, documented at <http://127.0.0.1:8200/docs> while it runs: add and transcribe files from your own scripts, read a call as JSON, search, correct, rename, delete.

## Where your calls are

```text
transcripts/
  2026-10-21_Northpine launch sync/
    Northpine launch sync.m4a    the original recording
    Northpine launch sync.txt    [mm:ss] [Voice 2] text: the source of everything else
    Northpine launch sync.md     paragraphs, to read or paste
    words.json                   when each word was said
    info.json                    duration, language, voice names, what was removed
    corrections.jsonl            every corrected line, before and after
    summary.md                   the summary, if asked for
    followup.md                  the follow-up email, if asked for
```

No database: delete a folder and the call is gone; copy it and you have a backup. Calls deleted from the page are moved to `transcripts/_deleted/`, not erased.
