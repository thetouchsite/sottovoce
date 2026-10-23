# Recording a call

## On Windows: from the Sottovoce window

Sottovoce records the call from the computer itself: your microphone, and everything the computer plays. Any call works, in any app: Google Meet in a browser, the Teams or Zoom apps, WhatsApp, a phone call through the computer.

1. Start your call.
2. In the Sottovoce window, give the call a name and press **Start recording**.
3. When the call ends, press **Stop and transcribe**: in the window, or in the menu of the icon by the clock.

Nothing is shared on screen and nobody on the call is told: no bar, no border, nothing that reaches the others. On your own screen, Windows shows its microphone icon by the clock, as it does whenever an app uses the microphone, and Sottovoce's icon gets a red dot while it records. You can close the window: the recording goes on by the clock.

**Headphones that change mid-call** are followed. If they run flat, or you plug some in, Sottovoce moves to the device Windows now uses, and the moment in between is silence on that track: the recording goes on.

## On Linux and macOS: from the browser

Sottovoce records calls that run in a browser tab: Google Meet, and Zoom or Teams on the web.

1. Open the call in a tab of Chrome or Edge.
2. In Sottovoce, give the call a name and press **Start recording**. The browser asks which tab to share: pick the call's tab and leave **Also share tab audio** on.
3. Talk. When the call ends, press **Stop and transcribe**.

## Two tracks: who spoke is measured

Your microphone is recorded on one track and the call on the other. The call's audio never carries your voice, because the meeting app does not send it back to you. So *You* and *Them* come from the recording itself, with no model guessing.

Each line Whisper writes is laid over the moments in it when someone actually speaks, and each word goes to the track that carries its moment, counting only what stands out from that track's own background noise. Lines split where the speaker changes. How often that is right is measured on public meetings in [Benchmarks](benchmarks.md#two-track-calls).

If more than one person is on the call's side, tick **Separate voices** (or press it later on the call): *Them* is split into *Voice 1*, *Voice 2*…, and *You* stays a measurement. See [Telling voices apart](voices.md).

## Nothing is lost if Sottovoce closes

A recording is written to disk as it goes. If Sottovoce is closed, the computer switches off, or the browser tab is closed, the next start offers the interrupted recording: transcribe it, or delete it.

## Good practice

- **Use headphones if you can.** Without them your microphone also hears the others from the speakers. Their words mostly still go to the right side, but less often.
- **Tell the others you are recording.** Depending on where you are, you may be required to.
- **Recording works on the computer running Sottovoce.** From a phone you can read, correct and send recordings, not record a call: a phone on the Wi-Fi can't switch on the computer's microphone.

## Where it doesn't work yet

- **On Linux and macOS, desktop apps** (the Zoom, Teams or Webex applications) have no tab to share: recording the computer's own sound is Windows only for now.
- **Firefox and Safari** cannot capture another tab's sound.
