# Contributing

Thanks for helping. This page says how the project is built, how to check a change, and what we look for in a pull request. By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Principles

- **Nothing leaves the machine.** No network calls while transcribing, no CDN, no analytics, no remote LLM. The page must open offline. The only network use is downloading models on first use (Whisper and the summary model from Hugging Face, the voice models from GitHub, checked by SHA-256) and an optional LLM server on `127.0.0.1`.
- **Plain files are the database.** One folder per call; the `.txt` is the source the rest is rebuilt from. A feature that needs a database needs a very good reason.
- **Measure before changing a default.** Every setting in `transcribe.py` was chosen by measuring against the alternatives, and the comment next to it says what it fixed. If you change one, show the numbers before and after, taken with a script in `research/`.
- **Every number has a script.** A figure in the README or the docs comes from a script in `research/` that anyone can re-run, with the command next to it.
- **One page, no build.** `app/index.html` is a single file with no framework and no build step.
- **Never a silent deletion.** Anything the program removes from a transcript is reported, with its time.
- **Say why in the code.** Comments explain the reason behind a choice, especially when the obvious alternative was tried and failed.

## Setting up

For the tests, the API and the page, no GPU is needed:

```sh
git clone https://github.com/thetouchsite/sottovoce && cd sottovoce
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

To transcribe, install the full set with PyTorch for your GPU first, as in [Getting started](docs/getting-started.md#install), *From a clone*.

## Tests

```sh
pytest tests/test_engine.py tests/test_api.py      # engine and API, a few seconds

pip install playwright && playwright install chromium
pytest tests/test_page.py                          # the page in a real browser
SOTTOVOCE_BROWSER=chrome pytest tests/test_page.py # or with the Chrome you have
```

The tests run on the fictional calls in `examples/`, on a temporary copy, with the server started `--no-model`. CI runs them on every push and pull request: Ubuntu and Windows, Python 3.10 and 3.14, plus the page in Chromium, the launchers through `shellcheck`, and the docs through `mkdocs build --strict`.

- **A new feature comes with tests.** A bug fix comes with a test that would have caught it: several tests exist because the bug happened once.
- **Existing behaviour doesn't change without a test that says so.**
- Transcription itself needs a GPU and is checked by hand: transcribe a recording of your own in the default mode and with **Precise word timings**, record a short call from a browser tab, and check `info.json`.

## Measurements

| Script | What it measures | Data |
| --- | --- | --- |
| `research/wer.py` | Word error rate: Whisper alone against the whole engine, and words invented on long pauses | Public FLEURS Italian and AMI meetings, downloaded on first run |
| `research/voices_ami.py` | Telling voices apart (DER) | Public AMI meetings, downloaded on first run |
| `research/two_tracks.py` | Who said each word on two-track calls | Public AMI headset recordings |
| `research/llm.py` | The built-in summary model: time and memory | The examples in the repo |
| `research/benchmark.py`, `research/compare.py` | Whisper models on a recording of yours: speed, invented phrases, non-existent words | Your own audio |

Results go in [docs/benchmarks.md](docs/benchmarks.md) with the hardware, the versions and the command. Data downloaded by the scripts lands in git-ignored folders.

## Documentation

The site is built from `docs/` with MkDocs Material:

```sh
pip install -r requirements-docs.txt
mkdocs serve        # http://127.0.0.1:8000
```

The README stays short and points to the docs. Write in plain, short sentences. Screenshots use the fictional examples only, never real calls.

## Commits and pull requests

- **One subject per pull request.** Keep unrelated changes apart.
- **Commit messages:** a first line that says what changes, in plain words (no prefixes like `feat:`), then a body that says why, and what was measured or tried. Look at `git log` for the tone.
- **Changelog:** add a line under *Unreleased* in [CHANGELOG.md](CHANGELOG.md), in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) form. Versions follow [Semantic Versioning](https://semver.org/).
- **Never commit a real call**, a real transcript or a real glossary: `transcripts/` and `glossary.txt` are git-ignored for that reason.

## Good first contributions

- **Phrases Whisper invents on silence, in your language.** Add the ones you've seen to `SUBTITLE_PHRASES` in `transcribe.py`. Only phrases that belong to subtitles, never to conversation: a plain "thank you" would flag every polite line.
- **A transcription after the one-command install** on Linux with an NVIDIA GPU, or on an Apple-silicon Mac. CI installs and starts it on both, but has no GPU to transcribe with.
- **Languages in the picker:** `LANGUAGES` in `app/index.html`, with Whisper's codes.

## Reporting a bug

Say what you dropped or recorded (format, length, language, browser), what you expected and what you got. Paste the lines from `info.json` that matter, **not** the transcript. For the quality of a transcript, a few lines with their time and what was really said are enough.
