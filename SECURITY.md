# Security

Sottovoce handles recordings and transcripts of business calls. This page says what it protects, how, and where the protection stops.

## Reporting a problem

Please report security problems privately, through **[GitHub's private vulnerability reporting](https://github.com/thetouchsite/sottovoce/security/advisories/new)**, not in a public issue. Include what you did, what happened, and the version (shown at `http://127.0.0.1:8200/api/status`).

Fixes go into the latest release. Older releases are not patched.

## What runs where

- **Everything runs on your computer.** Whisper, the voice models and the built-in summary model run locally. Recordings, transcripts and summaries are plain files in `transcripts/`. There is no account, no telemetry, no remote LLM. OpenVINO installs a telemetry package of its own, `openvino-telemetry`: only OpenVINO's model converter uses it (`ovc`), and Sottovoce never runs the converter.
- **What goes out, and when.** On first use, models are downloaded: Whisper large-v3 (for PyTorch, or OpenVINO's conversion) and the summary model from Hugging Face, the two voice models from the sherpa-onnx releases on GitHub (these two are checked against a fixed SHA-256 before use). At start and once a day, Sottovoce asks GitHub for the latest release's `latest.json`, to say whether a newer version is out: no data about the calls or the computer goes with it, and it can be turned off (see [Updates](#updates)). Nothing else leaves the machine. A model picked in LM Studio or Ollama is asked on this computer only (127.0.0.1). The page loads nothing from the internet. The API reference at `/docs` is FastAPI's own page and loads Swagger UI from a CDN when you open it.

## Threat model

### Default: this computer only

The server listens on `127.0.0.1`. Other devices cannot reach it.

A browser on the same computer can still be used against it, by a web page you visit. Two defences, both tested in `tests/test_api.py`:

| Attack | What it would do | Defence |
| --- | --- | --- |
| **Cross-site request** (a page posts a form or a `fetch` to `127.0.0.1:8200`) | Change things: stop the server, delete or rename a call, edit the glossary | Requests that change state (`POST`, `PUT`, `PATCH`, `DELETE`) are refused with 403 when the browser says they come from another site (`Origin`, or `Sec-Fetch-Site: cross-site`). |
| **DNS rebinding** (a site makes its own name resolve to `127.0.0.1`, so the browser treats the server as same-origin) | Read every transcript through `/api/history` | Only the names the server is reached by are accepted in the `Host` header: `127.0.0.1`, `localhost` and `[::1]` on its port. A rebound name is refused with 403. |

Not covered: **other programs and other users on the same computer.** Anything that runs on the machine can talk to `127.0.0.1:8200` without a browser. On a shared computer, protect the account and the disk (BitLocker, FileVault, LUKS): the transcripts are not encrypted at rest.

### Updates

- **One question, once a day.** At start and every 24 hours Sottovoce downloads `latest.json` from the latest GitHub release. GitHub sees the computer's address, as for any download; nothing else is sent. **Settings → Updates**, `--no-update-check` or `SOTTOVOCE_NO_UPDATE_CHECK=1` turn it off.
- **Signed, or ignored.** `latest.json` gives the version, its notes and the SHA-256 of the setup; `latest.json.sig` is its Ed25519 signature. The public key is in `updates.py`; the private key never goes to GitHub. A manifest whose signature doesn't verify is ignored. A setup whose SHA-256 isn't the signed one is deleted, never run. Someone who took over the GitHub account or the release could not ship an update without the key.
- **Installed by the computer itself.** Only from the computer running Sottovoce (not from a phone with `--lan`), only when no call is being transcribed or recorded, by the same setup that installs it, run silently once Sottovoce has quit.
- **Signing a release:** `python installer/sign_release.py dist/Sottovoce-Setup-<version>.exe`, then upload `latest.json` and `latest.json.sig` next to the setup.

### `--lan`: your local network, with a PIN

`--lan` makes the page reachable from other devices on the network, for example your phone. Then:

- Other devices must give a **PIN** once. It is made up at the first start (six digits), kept in `.lan-pin` (git-ignored), and printed at every start; `--pin` chooses your own. After the PIN, a device keeps a cookie signed with a secret that never leaves the machine (HMAC-SHA256), valid for a year. A new PIN invalidates every cookie.
- **Five wrong PINs** from one address lock it out for 15 minutes.
- The computer itself is never asked for the PIN.
- The `Host` check also accepts this computer's own addresses and name. Requests from other sites are still refused.

The limits, plainly:

- **The connection is plain `http`.** The PIN and the cookie travel unencrypted on the network. On a home or office Wi-Fi this keeps out the curious. It does not stop someone who can listen to the traffic: on a network you don't control, don't use `--lan`.
- **Six digits are not a password.** The lockout makes guessing slow (five tries every 15 minutes: 480 a day from one address), not impossible from many addresses.
- Anyone on the network who has the PIN sees every call.

## Supply chain

- The installer downloads uv at a fixed version and checks it against its SHA-256 before running it. Python dependencies come from PyPI, PyTorch from its own index, Python itself from uv's builds.
- The voice models are pinned by SHA-256 (`voices.py`). Whisper and the summary model are fetched by name from Hugging Face, not pinned to a revision.
- CI runs the tests on every push and pull request (`.github/workflows/tests.yml`). It has no secrets and does not publish anything.
