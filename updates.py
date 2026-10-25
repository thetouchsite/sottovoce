"""Updates: told when there is a new version, installed with one click.

ONE QUESTION GOES OUT. At start and once a day, Sottovoce asks GitHub for the
latest release's `latest.json`: nothing about the calls, nothing about this
computer beyond what any download shows (its address). It can be turned off
in Settings, with --no-update-check, or with SOTTOVOCE_NO_UPDATE_CHECK=1.

NOTHING IS INSTALLED THAT WE DIDN'T SIGN. `latest.json` says the version, its
notes and the SHA-256 of the setup; `latest.json.sig` is its Ed25519
signature, made with a private key that never goes to GitHub. The public key
is below. A manifest whose signature doesn't verify is ignored, and a setup
whose SHA-256 isn't the signed one is deleted, not run: someone who took over
the GitHub account still couldn't ship anything to the computers that have
Sottovoce. installer/sign_release.py makes the key and the signature.

INSTALLED BY THE SETUP ITSELF. On Windows, with Sottovoce installed by its
setup or its install command, the setup is downloaded and run silently after
Sottovoce has quit (install()), then Sottovoce starts again. Never while a
call is being transcribed or recorded: the server waits for that. Elsewhere,
or from a clone, the page says there is a new version and how to get it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = "thetouchsite/sottovoce"
# SOTTOVOCE_UPDATE_URL: another place to ask, for trying an update before it
# is published. What it serves still has to carry our signature.
MANIFEST = (os.environ.get("SOTTOVOCE_UPDATE_URL")
            or f"https://github.com/{REPO}/releases/latest/download/latest.json")
TIMEOUT = 15
EVERY = 24 * 3600

# Ed25519, raw, base64. The private half is kept off GitHub by whoever
# publishes releases (installer/sign_release.py --new-key).
PUBLIC_KEY = "qwCaL7S/exXg24+l5/rNB3zX+EQYYrr5P5GXRCeTWKI="

ROOT = pathlib.Path(__file__).resolve().parent
# The program folder of an install (setup or install.ps1): app\ holds this
# code, bin\uv.exe sits next to it. A clone has neither.
PROGRAM = ROOT.parent


def installed() -> bool:
    """Whether this copy can be updated by the setup: Windows, installed."""
    return os.name == "nt" and (PROGRAM / "bin" / "uv.exe").exists() and ROOT.name == "app"


def version_tuple(v: str) -> tuple[int, ...]:
    """ "v1.10.0" -> (1, 10, 0): versions compare as numbers, not as text."""
    parts = []
    for p in v.strip().lstrip("v").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def newer(latest: str, current: str) -> bool:
    return version_tuple(latest) > version_tuple(current)


def verify(manifest: bytes, signature: bytes, key: str | None = None) -> bool:
    """Whether `signature` (base64 text) is the Ed25519 signature of these bytes."""
    key = PUBLIC_KEY if key is None else key
    if not key:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key)).verify(
            base64.b64decode(signature.strip()), manifest)
        return True
    except (InvalidSignature, ValueError, TypeError, ImportError):
        return False


def _get(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Sottovoce"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(current: str) -> dict:
    """What the latest release offers, from its signed manifest.

    Returns {"available": manifest or None, "checked_at": ...} or {"error": ...}.
    Never raises: an update that can't be checked is not a failure.
    """
    try:
        raw = _get(MANIFEST)
        sig = _get(MANIFEST + ".sig")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return {"error": f"could not reach GitHub: {getattr(e, 'reason', e)}", "checked_at": time.time()}
    if not verify(raw, sig):
        return {"error": "the update's signature does not verify: ignored", "checked_at": time.time()}
    try:
        m = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"error": "the update's description is not readable", "checked_at": time.time()}
    return {"available": m if newer(str(m.get("version", "")), current) else None,
            "checked_at": time.time()}


def folder() -> pathlib.Path:
    """Where a setup waits to be run: in the program folder if installed."""
    return (PROGRAM / "updates") if installed() else pathlib.Path(tempfile.gettempdir()) / "sottovoce-updates"


def download(manifest: dict, progress=None) -> pathlib.Path:
    """The setup, downloaded and checked against the signed SHA-256.

    Raises ValueError if it doesn't match: the file is deleted, never run.
    """
    w = manifest["windows"]
    d = folder()
    d.mkdir(parents=True, exist_ok=True)
    out = d / pathlib.PurePosixPath(w["url"]).name
    part = out.with_suffix(".part")
    h = hashlib.sha256()
    req = urllib.request.Request(w["url"], headers={"User-Agent": "Sottovoce"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
        total, done = int(w.get("size") or 0), 0
        while True:
            block = r.read(1 << 16)
            if not block:
                break
            f.write(block)
            h.update(block)
            done += len(block)
            if progress:
                progress(done, total)
    if h.hexdigest() != w["sha256"].lower():
        part.unlink(missing_ok=True)
        raise ValueError("the downloaded setup is not the one that was signed: deleted")
    os.replace(part, out)
    return out


def helper(setup: pathlib.Path, pid: int) -> list[str]:
    """The command that installs once Sottovoce has quit: it waits for this
    process to end, then starts the setup silently, and the setup starts
    Sottovoce again (/RELAUNCH=1). It doesn't wait for the setup: Start-Process
    -Wait would also wait for the Sottovoce the setup starts, for ever. Each
    step goes into <setup>.helper.log, the setup's own into <setup>.log."""
    log = setup.with_suffix(".helper.log")
    script = (f"Set-Content -Path '{log}' -Value \"waiting for {pid}\"; "
              f"Wait-Process -Id {pid} -Timeout 120 -ErrorAction SilentlyContinue; "
              f"Add-Content -Path '{log}' -Value 'starting the setup'; "
              f"Start-Process -FilePath '{setup}' -ArgumentList "
              f"'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/RELAUNCH=1',"
              f"'/LOG=\"{setup.with_suffix('.log')}\"'; "
              f"Add-Content -Path '{log}' -Value 'started'")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-ExecutionPolicy", "Bypass", "-Command", script]


# Out of Sottovoce's job, if it runs in one, so that quitting doesn't take the
# helper with it.
BREAKAWAY = 0x01000000          # CREATE_BREAKAWAY_FROM_JOB


def install(setup: pathlib.Path):
    """Starts the helper on its own: the caller quits Sottovoce right after.

    A console of its own, never shown (CREATE_NO_WINDOW): PowerShell started
    with no console at all (DETACHED_PROCESS) exited before doing anything.
    """
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    args = dict(close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.Popen(helper(setup, os.getpid()), creationflags=flags | (BREAKAWAY if os.name == "nt" else 0), **args)
    except OSError:                     # a job that doesn't allow it
        subprocess.Popen(helper(setup, os.getpid()), creationflags=flags, **args)


def how_to_update() -> str:
    """For a copy the setup can't update: what to do instead."""
    if (ROOT / ".git").exists():
        return "git pull"
    if os.name == "nt":
        return "irm https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.ps1 | iex"
    return "curl -fsSL https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.sh | bash"


if __name__ == "__main__":
    import server
    print(json.dumps(check(sys.argv[1] if len(sys.argv) > 1 else server.VERSION), indent=1))
