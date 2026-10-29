# Troubleshooting

## The window

- **Nothing seems to happen at a double-click:** Sottovoce may be running already, hidden by the clock: the window comes back. If it doesn't, look for its icon by the clock (it may sit under the arrow **^**).
- **It opens in the browser instead of a window:** the window needs Microsoft's WebView2, part of Windows 11 and of most Windows 10 machines. Install the *Evergreen* runtime from microsoft.com and start it again.
- **What it was doing:** the server's messages, which a terminal used to show, are in `sottovoce.log` in the program folder (`%LOCALAPPDATA%\Programs\Sottovoce`), rewritten at every start.
- **With a terminal, for options like `--lan`:** `%LOCALAPPDATA%\Programs\Sottovoce\Sottovoce.cmd`.

## The installer stops

- **"Sottovoce is running"**: an update can't replace files in use. Quit it (right-click its icon by the clock, then **Quit**), then run the command again.
- **A download failed halfway**: run the command again. What was already downloaded is kept and not fetched twice.
- **Behind a company proxy**: set `HTTPS_PROXY` before running it (in PowerShell, `$env:HTTPS_PROXY = "http://proxy:8080"`). The installer needs github.com, pypi.org, files.pythonhosted.org and download.pytorch.org.
- **It says to update the driver**: an RTX 50 card needs NVIDIA driver 580 or newer, older cards 528 (525 on Linux). Update it from nvidia.com and run the command again.

## Which GPU is used

**Settings → Transcription** says where Whisper runs. To see it from a terminal:

```sh
%LOCALAPPDATA%\Programs\Sottovoce\app\.venv\Scripts\python.exe %LOCALAPPDATA%\Programs\Sottovoce\app\transcribe.py --where
```

- **An Intel GPU is missing from the list:** OpenVINO reaches it through the Intel graphics driver. Update it from intel.com (or Windows Update) and restart Sottovoce. In a virtual machine the host's GPU is usually not visible: Whisper runs on the processor there.
- **The NVIDIA card is there but another path is chosen:** you, or **Measure which is fastest**, chose it; click the card to go back. On some laptops the GPU built into the processor really is faster.
- **An AMD GPU is not listed:** not used yet; Whisper runs on the processor through OpenVINO.

## The NVIDIA GPU is not used

Transcription works but is very slow, and the NVIDIA card stays idle. Almost always this is **the PyTorch trap**: installed as a dependency of `transformers`, pip pulls the default PyTorch from PyPI, which on RTX 50-series cards (Blackwell, `sm_120`) doesn't see the GPU. Everything runs on the CPU and nothing tells you.

Check:

```sh
%LOCALAPPDATA%\Programs\Sottovoce\app\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

(In a clone, `.venv\Scripts\python.exe`; on Linux and macOS, `.venv/bin/python` in the program folder's `app`.)

It should print a version ending in `+cu130` (or your CUDA) and `True`. If not, install PyTorch first, from the CUDA index, then the rest:

```sh
pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cu130
```

With the installer it's simpler: run the install command again, after updating the NVIDIA driver if it asked you to. It reinstalls the right PyTorch every time.

The installer does it in this order; so does *From a clone* in [Getting started](getting-started.md#install).

## A long call freezes the computer

Before 1.9.2, a call of an hour with **Precise word timings** on took tens of GB of RAM (49 GB measured on a 74-minute call) and froze the computer. Update: from 1.9.2 the same call takes 2.7 GB. On a computer without an NVIDIA card, an hour of call keeps the processor busy for the whole transcription: let it work, plugged in.

## Sottovoce closed while transcribing on an Intel GPU

An older Intel GPU (UHD, HD, Iris Plus) is not used by itself from 1.9.2: Whisper runs on the processor instead. If a transcription on the Intel GPU closes Sottovoce, the next start says so in **Settings → Transcription** (*failed here last time*) and uses the processor; you can still pick the GPU there by hand.

## The first transcription is slow

The first transcription downloads Whisper large-v3 (2.9 GB for an NVIDIA card, 1.5 GB through OpenVINO), the first summary the built-in model (8 GB), the first voice separation two small models (32 MB). Each happens once, and the page shows it with a moving bar and the seconds counted. After a pause of ten minutes or more, Whisper is loaded again before transcribing: about ten seconds, shown as *loading the model*.

On Windows, Hugging Face may warn that it can't create symlinks in its cache. It's harmless: files are copied instead.

## Summaries take minutes, or fail

- **With LM Studio or llama.cpp:** check which build runs. A Vulkan build on an RTX 50-series card works but crawls; the CUDA build is many times faster.
- **With the built-in model:** the page says when there isn't enough free GPU memory next to Whisper. Close other GPU programs, or pick a smaller model of yours in **Settings → Summaries and emails**.
- **LM Studio or Ollama, picked in Settings, doesn't answer:** the page says why. *Not installed*: Sottovoce looks for `lms` in `%USERPROFILE%\.lmstudio\bin` and for Ollama where its setup puts it. *Did not start in 60 seconds*: open the program once by hand, then try again. A model deleted in the program since: pick another.
- **No button at all:** no LLM is running and the built-in model is off (`--no-llm`, or `--no-model`), or there is no NVIDIA GPU and no model is picked in Settings.

## Recording

- **"No sound from the computer yet"** (Windows): the others' voices don't reach the computer's output. Check the volume isn't muted, and that the call plays on this computer.
- **"The recording did not start"** (Windows): another program holds the microphone in exclusive mode, or Windows has no default microphone or output. **Settings → System → Sound** shows both.
- **"No sound from the call yet"** (browser): the tab was shared without its audio. Stop, start again, pick the call's tab and leave **Also share tab audio** on.
- **No Start recording button** (browser): recording needs Chrome or Edge on the computer running Sottovoce. Firefox and Safari can't capture another tab's sound, and from a phone the browser doesn't allow it.
- **Sottovoce closed during a call:** open it again. The interrupted recording is offered on the home screen: transcribe it, or delete it.

## The phone can't connect

1. The server must be started with `--lan`, and the phone on the same Wi-Fi.
2. Use the address the server prints **at this start**: the router can give the computer a different one from one day to the next.
3. On Windows, the first time, allow Python on **private networks** when asked. If you missed it: Windows Security → Firewall → Allow an app.
4. The PIN is printed at every start. Five wrong tries lock the phone out for 15 minutes.

## Other

- **Port 8200 in use:** another copy is running, or another program uses it. Stop it, or start with `--port 8300`.
- **A transcription was interrupted** (the server closed mid-way): the call goes back to *Not transcribed* at the next start. Open it and press **Transcribe**.
- **A call was deleted by mistake:** it is in `_deleted/` inside the folder of your calls (`Sottovoce/transcripts` in your home folder, or `transcripts/` in a clone). Move its folder back.
- **A request answered 403:** the server only accepts requests addressed to its own name, and changes coming from its own page. Open it at `http://127.0.0.1:8200` (or the address printed with `--lan`), not through another name. See [SECURITY.md](https://github.com/thetouchsite/sottovoce/blob/main/SECURITY.md).
