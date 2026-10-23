# Troubleshooting

## The GPU is not used

Transcription works but is very slow, and the GPU stays idle. Almost always this is **the PyTorch trap**: installed as a dependency of `transformers`, pip pulls the default PyTorch from PyPI, which on RTX 50-series cards (Blackwell, `sm_120`) doesn't see the GPU. Everything runs on the CPU and nothing tells you.

Check:

```sh
.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

It should print a version ending in `+cu130` (or your CUDA) and `True`. If not, install PyTorch first, from the CUDA index, then the rest:

```sh
pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cu130
```

`Install.bat` and `install.sh` do it in this order.

## The first start is slow

The first start downloads Whisper large-v3 (2.9 GB), then loads it on the GPU. The first summary downloads the built-in model (8 GB) and the first voice separation downloads two small models (32 MB). Each happens once. Until Whisper is loaded the page says *Loading the model…* and transcription waits.

On Windows, Hugging Face may warn that it can't create symlinks in its cache. It's harmless: files are copied instead.

## Summaries take minutes, or fail

- **With LM Studio or llama.cpp:** check which build runs. A Vulkan build on an RTX 50-series card works but crawls; the CUDA build is many times faster.
- **With the built-in model:** the page says when there isn't enough free GPU memory next to Whisper. Close other GPU programs, or run LM Studio or Ollama with a smaller model; Sottovoce uses a running server first.
- **No button at all:** no LLM is running and the built-in model is off (`--no-llm`, or `--no-model`), or there is no NVIDIA GPU.

## Recording

- **"No sound from the call yet"**: the tab was shared without its audio. Stop, start again, pick the call's tab and leave **Also share tab audio** on.
- **No Start recording button:** recording needs Chrome or Edge on the computer running Sottovoce. Firefox and Safari can't capture another tab's sound, and from a phone the browser doesn't allow it.
- **The page closed during a call:** open it again. The interrupted recording is offered on the home screen: transcribe it, or delete it.

## The phone can't connect

1. The server must be started with `--lan`, and the phone on the same Wi-Fi.
2. Use the address the server prints **at this start**: the router can give the computer a different one from one day to the next.
3. On Windows, the first time, allow Python on **private networks** when asked. If you missed it: Windows Security → Firewall → Allow an app.
4. The PIN is printed at every start. Five wrong tries lock the phone out for 15 minutes.

## Other

- **Port 8200 in use:** another copy is running, or another program uses it. Stop it, or start with `--port 8300`.
- **A transcription was interrupted** (the server closed mid-way): the call goes back to *Not transcribed* at the next start. Open it and press **Transcribe**.
- **A call was deleted by mistake:** it is in `transcripts/_deleted/`. Move its folder back into `transcripts/`.
- **A request answered 403:** the server only accepts requests addressed to its own name, and changes coming from its own page. Open it at `http://127.0.0.1:8200` (or the address printed with `--lan`), not through another name. See [SECURITY.md](https://github.com/thetouchsite/sottovoce/blob/main/SECURITY.md).
