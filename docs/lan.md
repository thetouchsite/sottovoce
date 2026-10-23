# From your phone

Start the server with `--lan`: from a terminal, `%LOCALAPPDATA%\Programs\Sottovoce\Sottovoce.cmd --lan` on Windows, `~/.local/share/sottovoce/sottovoce --lan` on Linux, `~/Library/Application\ Support/Sottovoce/sottovoce --lan` on a Mac, or `python server.py --lan` in a clone. It prints the address to open on your phone, on the same Wi-Fi, and a PIN:

```text
  ON YOUR NETWORK: other devices on this Wi-Fi can open it, with the PIN.
  from your phone:  http://192.168.1.20:8200
  PIN: 482913      (asked once per device; this computer is never asked)
```

## What you can do from the phone

- Read calls in the three views, listen, and tap a word to hear it.
- Correct a line: **Correct**, tap the line, **Save**.
- Name voices, or separate them on a call that has none.
- Send a recording from the phone (a voice memo, a recorded call, a video) and press **Transcribe**: the computer does the work.
- Download notes and transcripts, write the follow-up email and share it to Mail or WhatsApp.

Recording a call works only on the computer itself, and the server can't be stopped from a phone, because it couldn't be started again from there.

## The PIN

- Asked **once per device**; the device is then remembered for a year, across restarts. The computer itself is never asked.
- Made up at the first start and kept in `.lan-pin` (git-ignored). Choose your own with `--pin 123456`; a new PIN logs every device out.
- **Five wrong PINs** from one address lock it out for 15 minutes.

## The limits

The connection is plain `http`: the PIN and the cookie travel unencrypted on the network. That keeps out the curious on a home or office Wi-Fi, not someone who can listen to the traffic. Don't use `--lan` on a network you don't control. Without `--lan` the server answers only on `127.0.0.1`. The full threat model is in [SECURITY.md](https://github.com/thetouchsite/sottovoce/blob/main/SECURITY.md).

The computer's address on your network is given by the router and can change from one day to the next: the server prints the current one at every start.
