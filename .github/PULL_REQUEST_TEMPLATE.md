## What and why

<!-- What this changes, and the reason. If it closes an issue: Closes #123 -->

## How it was tested

<!-- The commands you ran, and anything you checked by hand. -->

- [ ] `pytest tests/test_engine.py tests/test_api.py`
- [ ] `pytest tests/test_page.py` (if the page changed)
- [ ] Looked at the page with `python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt`, at desktop and phone width, console empty (if the page changed)

## Numbers, for changes to transcription defaults

<!--
Every default in transcribe.py was measured on a real call. If you change one,
show before and after, measured the same way with research/benchmark.py and
research/compare.py, on more than five minutes of audio. Say what the audio
was (length, language, how it was recorded), not what was said.
Delete this section if it doesn't apply.
-->

| | before | after |
| --- | --- | --- |
| non-existent words | | |
| time | | |

## Checklist

- [ ] No real call, transcript or glossary is included: not in the code, the tests, the screenshots or this description.
