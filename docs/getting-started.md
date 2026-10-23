# Getting started

## What you need

- **An NVIDIA GPU.** Whisper large-v3 runs on it in half precision; the built-in summary model needs about 8 GB more ([measured](benchmarks.md#the-built-in-summary-model)). Without an NVIDIA GPU it runs on the CPU, much slower.
- **Python 3.10 or newer.** Tested on Windows 11 with Python 3.14 and an RTX 5090; the test suite runs on Python 3.10 and 3.14, on Windows and Ubuntu.
- **Chrome or Edge**, to record calls from the browser.
- About **3 GB** of disk for Whisper, and **8 GB** more if you use the built-in summary model.

## Install

=== "Windows"

    ```bat
    git clone https://github.com/thetouchsite/sottovoce
    cd sottovoce
    Install.bat
    Start.bat
    ```

    `Install.bat` creates a virtual environment, installs PyTorch with CUDA first (see [the PyTorch trap](troubleshooting.md#the-gpu-is-not-used)), then the rest, and prints whether it sees your GPU. `Start.bat` starts the server and opens <http://127.0.0.1:8200>.

=== "Linux and macOS"

    ```sh
    git clone https://github.com/thetouchsite/sottovoce
    cd sottovoce
    ./install.sh
    ./start.sh
    ```

    The same steps as on Windows: PyTorch first, from the CUDA index when `nvidia-smi` is found, then the rest. On a Mac there is no CUDA, so it runs on the CPU. These scripts are checked in CI with `bash -n` and `shellcheck`, but not yet run end to end on a clean machine.

=== "From source, by hand"

    ```sh
    python -m venv .venv
    # Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
    pip install torch --index-url https://download.pytorch.org/whl/cu130   # match your CUDA
    pip install -r requirements.txt
    cp glossary.example.txt glossary.txt
    python server.py
    ```

The first start downloads Whisper large-v3 (2.9 GB, once) and loads it on the GPU. After that the server keeps it loaded: each new file only pays for its own transcription.

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

Any format ffmpeg can open works: mp4, m4a, mp3, wav, ogg, opus, 3gp, webm. The **IT** button at the bottom of the side bar switches the page to Italian. Stop the server with the power button, or `Stop.bat`.

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
