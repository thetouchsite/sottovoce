# Summaries, notes and follow-ups

## The summary

The **Summary** tab of a call asks a local LLM for a few lines of synthesis, then *Decided*, *To do* and *Open*, in the language of the call. When who spoke is known (two tracks, or voices told apart) the model is told who said each line, with the names you gave, so *To do* can say who does what. The summary is saved as `summary.md` and read from disk the next time; **Redo** writes a new one.

## Notes, for the client's folder

**Download → Notes** gives one Markdown file to keep with a client's documents: date, length, who took part and how long each talked, the summary, then the whole transcript with names and minutes. Its headings are in the language of the call (*Appunti, Partecipanti, Trascrizione* for an Italian call). It is meant to sit next to the client's other documents, and to be read by whoever, or whatever assistant, works on that client next.

## The follow-up email

Under the transcript, **Write the follow-up** asks the same local LLM for the email to send after the call: from you to the others, by the names you gave the voices, in the call's language and tone. It has a subject, a line of thanks, what was decided, the next steps and who takes them, and what is still open.

The model is told not to invent: a date, a price or a name that was not said comes out as a `[placeholder]`. Edit the text in place (the changes are saved), copy it, write it again, or on a phone share it straight to Mail or WhatsApp. It is saved as `followup.md`.

The summary and the email are deleted when the lines they were written from change (voices separated again, the glossary applied again), so they never describe a text that no longer exists.

## Which model writes them

Chosen once in **Settings → Summaries and emails**, and remembered:

- **Automatic**, the default: a local LLM server that is already running (LM Studio on port 1234, Ollama on 11434, llama-server on 8080), over the OpenAI-compatible API; if none is, the model built in.
- **Built in: Qwen3 4B Instruct** (Apache-2.0, no account), the way Sottovoce uses Whisper: downloaded from Hugging Face the first time (8 GB), loaded on the GPU when asked, unloaded after ten minutes unused so the memory goes back to Whisper. It needs an NVIDIA GPU.
- **One of your LM Studio models.** Settings lists them, with their size, from LM Studio's own command line (`lms ls`). LM Studio doesn't need to be open: when a summary is asked, Sottovoce starts its server without a window (`lms server start`), LM Studio loads the model for the request and lets it go ten minutes after (the request's `ttl`). If LM Studio's just-in-time loading is turned off, Sottovoce loads the model with `lms load`.
- **One of your Ollama models**, read from Ollama's models folder, so Ollama doesn't need to be running to list them. Sottovoce starts `ollama serve` when a summary is asked; Ollama loads the model and lets it go after five minutes, as it always does.

Whatever Sottovoce started, it stops when it quits: the computer is left as it was found. A server you started yourself is left alone.

This is the way to a faster or larger model, to summaries on a computer without an NVIDIA GPU, or to a GPU too small for both models.

Nothing is ever sent to a remote LLM.

| On the example calls, RTX 5090 Laptop | Seconds |
| --- | --- |
| Follow-up email of a 1-minute call, model already loaded | 7.2 |
| Summary of an 11-minute call, model already loaded | 10.3 to 10.9 |
| Follow-up email, including loading the model from disk | 55.8 |
| GPU memory held by the model | 7.8 GB |

```sh
python research/llm.py
```

Options: `--no-llm` turns the built-in model off; `SOTTOVOCE_LLM=<hugging face id>` picks another one. If the built-in model doesn't fit next to Whisper on your GPU, the page says so: run LM Studio or Ollama with a smaller model instead.
