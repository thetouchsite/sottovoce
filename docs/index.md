---
hide:
  - navigation
  - toc
---

# Sottovoce

Call transcription that runs on your own computer, and shows you where the text can't be trusted.
{ .lead }

Drop a recorded call on the page, or record the call from it. You get the transcript, who said what, a summary, a follow-up email, and a map of the places to double-check. Whisper large-v3 on your GPU. Nothing leaves the machine.

[Get started](getting-started.md){ .md-button .md-button--primary } [See it on GitHub](https://github.com/thetouchsite/sottovoce){ .md-button }

![A tour of Sottovoce on fictional calls: the home screen, a call's summary, the call strip, three voices named in the Voices panel, a call recorded on two tracks](images/demo.gif)

## Why Sottovoce

**It shows where the text is weak.**
The *call strip* draws the whole recording as one band: where people speak, where it is silent, where an invented phrase was removed, where a line was corrected. Click anywhere to listen from there.

**It removes what nobody said.**
On silence, Whisper writes the subtitles it learned from: *"Thanks for watching"*, *"Subtitles by…"*. Sottovoce drops those phrases only where the audio is far below speech, and lists every removal with its time.

**It knows who spoke.**
Record a call from the browser and your microphone and the call go on two separate tracks: *You* and *Them* are measured, not guessed. On any other recording, voices are told apart by two small open models, with no account and no token.

**It keeps your names right.**
A glossary fixes the client and product names Whisper can't know, after transcription, and can be applied again to older calls.

**It stays on your machine.**
No account, no telemetry, no remote LLM. Every call is a folder of plain files. Summaries and follow-up emails are written by a model that runs locally.

## In practice

| You want to… | Go to |
| --- | --- |
| Install it and transcribe a first call | [Getting started](getting-started.md) |
| Record a Meet, Zoom or Teams call from the browser | [Recording a call](recording.md) |
| Know who said what on a meeting | [Telling voices apart](voices.md) |
| Get notes for the client's folder, and the email to send after | [Summaries, notes and follow-ups](summaries.md) |
| Read and correct calls from your phone | [From your phone](lan.md) |
| See how well it works, and where it doesn't | [Benchmarks](benchmarks.md) · [Limitations](limitations.md) |

## For teams and companies

Sottovoce is built and maintained by [TouchSite Software](https://www.touchsitesoftware.it). For a firm that handles confidential calls (law, accounting, healthcare, HR), we can install it on your machines, build glossaries for your sector and clients, connect it to the tools you already use, and support it.

**Write to [info@touchsitesoftware.it](mailto:info@touchsitesoftware.it).**
