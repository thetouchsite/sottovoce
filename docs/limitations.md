# Limitations

What Sottovoce doesn't do, or doesn't do well yet. Most of these are on the [roadmap](https://github.com/thetouchsite/sottovoce/blob/main/ROADMAP.md).

## Hardware and platforms

- **An NVIDIA GPU is expected.** Whisper large-v3 runs on CUDA; without it, it runs on the CPU, much slower. Apple Silicon and AMD GPUs are not accelerated yet.
- **Transcription is tested on Windows.** The installer runs end to end in CI on Windows, Ubuntu and macOS, with PyTorch for the CPU; nobody has yet transcribed with it on a Linux machine with an NVIDIA GPU, or on a Mac.
- **The installer is a command, not a program to double-click.** A downloadable `.exe` would need a code-signing certificate, paid every year, or Windows warns that it *protected your PC*. A command pasted in PowerShell gets no such warning.
- **Intel Macs are not supported:** PyTorch no longer ships for them.
- **The built-in summary model needs about 8 GB of GPU memory** next to Whisper. On a smaller card, use LM Studio or Ollama with a smaller model.

## Recording

- **Calls in a browser tab only**, in Chrome or Edge. Desktop apps (Zoom, Teams, Webex) and phone calls through the computer can't be recorded yet. From the Sottovoce window, recording opens the browser.
- **The window and the icon by the clock are Windows only.** On Linux and macOS, Sottovoce opens in the browser and is stopped from the page or its terminal.
- **No live transcript** during the call: the transcript arrives when the call ends.

## Who spoke

- **On two-track calls**, about 9 words in 10 go to the right person on [real microphones](benchmarks.md#two-track-calls). Fast, overlapping exchanges are where it errs most.
- **Telling voices apart** can merge two similar voices, give a short "yes" to the wrong person, and fold someone who talks for less than about 15 seconds into the nearest voice. The number of people can't be set by hand. See [Telling voices apart](voices.md#where-it-goes-wrong).

## The text

- **Whisper still makes mistakes**, on names above all: the [glossary](glossary.md) fixes the ones you know about.
- **A sentence right after a long pause can be lost.** Whisper sometimes writes a subtitle phrase over it; the phrase is removed, the sentence isn't brought back: 34 words of 1,175 on the [long-pauses test](benchmarks.md#long-pauses). It's on the roadmap.
- **Invented phrases are removed only when known.** The list covers the subtitle phrases Whisper is known to produce in several languages; a new one, or one said where the audio is not quiet, stays and is flagged *to check*.
- **Measured languages:** the measurements so far are on Italian and English. Whisper understands many more, but they haven't been measured here.

## On the network

- **`--lan` is plain http** with a PIN. Fine at home or in the office, not on a network you don't control. See [SECURITY.md](https://github.com/thetouchsite/sottovoce/blob/main/SECURITY.md).
- **No user accounts.** Anyone who reaches the server (on the computer itself, or with the PIN on the network) sees every call.
