# Recording a call

Sottovoce records calls that run in a browser tab: Google Meet, and Zoom or Teams on the web.

1. Open the call in a tab of Chrome or Edge.
2. In Sottovoce, give the call a name and press **Start recording**. The browser asks which tab to share: pick the call's tab and leave **Also share tab audio** on.
3. Talk. When the call ends, press **Stop and transcribe**.

## Two tracks: who spoke is measured

Your microphone is recorded on one channel and the call's tab on the other. The call's audio never carries your voice, because the meeting app does not send it back to you. So *You* and *Them* come from the recording itself, with no model guessing.

Each line Whisper writes is laid over the moments in it when someone actually speaks, and each word goes to the track that carries its moment. Lines split where the speaker changes. How often that is right is measured on public meetings in [Benchmarks](benchmarks.md#two-track-calls).

If more than one person is on the call's side, tick **Separate voices** (or press it later on the call): *Them* is split into *Voice 1*, *Voice 2*…, and *You* stays a measurement. See [Telling voices apart](voices.md).

## Nothing is lost if the page closes

The recording is sent to the server every five seconds while it runs. If the tab is closed, the browser crashes or the laptop goes to sleep, the next time the page opens it offers the interrupted recording: transcribe it, or delete it.

## Good practice

- **Use headphones.** Without them your microphone also hears the others from the speakers, and their words can end up on your track.
- **Tell the others you are recording.** Depending on where you are, you may be required to.
- **Recording works on the computer running Sottovoce.** Browsers allow tab and microphone capture only on a secure address, which `127.0.0.1` is and a network address over plain http is not. From a phone you can read, correct and send recordings, not record a call.

## Where it doesn't work yet

- **Firefox and Safari** cannot capture another tab's sound.
- **Desktop apps** (the Zoom, Teams or Webex applications, phone calls through the computer) have no tab to share. Recording them needs system-wide capture: it is on the [roadmap](https://github.com/thetouchsite/sottovoce/blob/main/ROADMAP.md).
