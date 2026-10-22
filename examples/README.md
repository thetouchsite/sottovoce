# Examples

Four **fictional** calls, already transcribed, to try Sottovoce without a GPU and without downloading the model. The companies and people in them are invented: Northpine, Corvel, Okafor and Lund, Halden Studio, Brenna Print.

```sh
pip install fastapi uvicorn python-multipart
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

Open <http://127.0.0.1:8200>.

| Call | Language | What to look at |
| --- | --- | --- |
| Supplier check-in, Brenna Print | English | A call recorded from the page on two tracks: every line says *You* or *Them*. |
| Northpine launch sync | English | The call strip: a long pause while a screen is shared, the invented *"Thanks for watching!"* dropped there (red line), and the lines corrected by the glossary and by hand (blue lines). The summary, written by a local LLM from this transcript. One phrase still to check at the end. |
| Pricing review, Okafor and Lund | English | A short call, no summary yet: the empty state of the summary view. |
| Kickoff Halden Studio | Italian | Language detected from the audio. |

Things to try:

- click the strip, a phrase in **To check**, or a word in **Line by line**: the text jumps to that moment;
- search *photos* or *codes* in the search box on the left;
- **Line by line**, then double-click a line to correct it;
- **Download** a call as subtitles (`.srt`) or as `.json` with the word timings;
- add a name in the glossary view (the book icon), then **Apply the glossary again** on a call;
- **Esc**, the breadcrumb or the logo take you back to the start.

Corrections and glossary changes are written into this folder, as they would be with real calls. `git checkout examples/ && git clean -f examples/` puts it back.

The word timings here are estimated, as in the default mode. There are no recordings, so there's no audio player: with real calls it sits next to the view tabs, and clicking a word plays from it. These calls are also the data the tests in `tests/` run on.
