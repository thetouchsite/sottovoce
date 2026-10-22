# Contributing

Thanks for helping. A few things keep this project useful.

## Principles

- **Measure before changing a default.** Every setting in `transcribe.py` was chosen by measuring on a real call, and the comment next to it says what it fixed. If you change one, show the numbers before and after, taken the same way: `research/benchmark.py` and `research/compare.py` exist for that. One run on five minutes of audio is not enough: the models looked even on 600 words and diverged on 2,500.
- **Nothing leaves the machine.** No network calls during transcription, no CDN, no analytics, no fonts from the internet. The page must open offline. The only network use is the one-time model download from Hugging Face, and the optional local LLM on `127.0.0.1`.
- **One page, no build.** `app/index.html` is a single file with no framework and no build step. It weighs 84 KB with its fonts. Keep it that way.
- **Plain files are the database.** One folder per call; the `.txt` is the source the rest is rebuilt from. A feature that needs a database needs a very good reason.
- **Say why in the code.** Comments explain the reason behind a choice, especially when the obvious alternative was tried and failed.
- **Never a silent deletion.** Anything the program removes from a transcript is reported, with its timestamp.

## Good first contributions

**Phrases Whisper invents on silence, in your language.** Whisper repeats the subtitles it was trained on: *"Thanks for watching"*, *"Untertitel im Auftrag des ZDF"*, *"Sous-titres réalisés par…"*. Add the ones you've seen to `SUBTITLE_PHRASES` in `transcribe.py`. Only phrases that belong to subtitles, never to conversation: a plain "thank you" would flag every polite line of every call.

**Linux and macOS.** The Python is cross-platform, but only Windows has been tested and has launchers. `install.sh` and `start.sh`, checked on a clean machine, are on the [roadmap](ROADMAP.md).

**Languages in the picker.** The list is `LANGUAGES` in `app/index.html`; codes are Whisper's.

## Checks before a pull request

Without a GPU, on the fictional examples:

```sh
pip install fastapi uvicorn python-multipart
python -m py_compile server.py transcribe.py summary.py research/*.py
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

Open <http://127.0.0.1:8200> and go through the call strip, the three reading views, search, a correction and the glossary view, at desktop width and at phone width. The browser console must stay empty. Then `git checkout examples/ && git clean -f examples/` to undo what you changed there.

With a GPU, transcribe a recording of your own end to end, and check that `info.json` has a `speech` map, a numeric `names_corrected`, and the detected `language`.

Never commit a real call, a real transcript or a real glossary: `transcripts/` and `glossary.txt` are git-ignored for that reason. Screenshots in pull requests use the fictional examples.

## Reporting a bug

Say what you dropped (format, length, language), what you expected and what you got. Paste the lines from `info.json` that matter, **not** the transcript. If it's about the quality of a transcript, a few lines with the timestamp and what was really said are enough.
