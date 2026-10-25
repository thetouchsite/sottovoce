"""Signs a release, so that Sottovoce installs it as an update.

    python installer/sign_release.py --new-key          once: makes the key pair
    python installer/sign_release.py dist/Sottovoce-Setup-1.9.0.exe
                                                        each release: latest.json + .sig

The private key is kept out of the repository, in
%USERPROFILE%\\.sottovoce-release\\update-key.pem (~/.sottovoce-release on
Linux and macOS), or where --key says. Keep a copy somewhere safe: without it
no update can be signed, and every computer would have to install the next
version by hand. Whoever has it can ship updates to every computer that has
Sottovoce: it never goes to GitHub, by mail or in a chat.

The public key goes into updates.py (PUBLIC_KEY), as printed by --new-key.

Then upload both files to the release, next to the setup:

    gh release upload v1.9.0 dist/latest.json dist/latest.json.sig
"""
import argparse
import base64
import datetime
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KEY = pathlib.Path.home() / ".sottovoce-release" / "update-key.pem"


def new_key(path: pathlib.Path) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if path.exists():
        raise SystemExit(f"{path} exists already: a new key would orphan every Sottovoce installed with the old one")
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def notes(version: str) -> str:
    """The first paragraph of the version's section in CHANGELOG.md."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n+(.+?)\n\n", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def manifest(setup: pathlib.Path, version: str) -> dict:
    data = setup.read_bytes()
    return {
        "version": version,
        "published": datetime.date.today().isoformat(),
        "notes": notes(version),
        "changelog": f"https://github.com/thetouchsite/sottovoce/blob/v{version}/CHANGELOG.md",
        "windows": {
            "url": f"https://github.com/thetouchsite/sottovoce/releases/download/v{version}/{setup.name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        },
    }


def sign(raw: bytes, key_path: pathlib.Path) -> str:
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    return base64.b64encode(key.sign(raw)).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("setup", nargs="?", type=pathlib.Path)
    ap.add_argument("--key", type=pathlib.Path, default=KEY)
    ap.add_argument("--new-key", action="store_true")
    args = ap.parse_args()
    if args.new_key:
        print(f"  private key: {args.key}  (keep a copy somewhere safe, never on GitHub)")
        print(f'  public key, for updates.py:\n\n  PUBLIC_KEY = "{new_key(args.key)}"\n')
        return
    if not args.setup:
        ap.error("the setup to sign is missing")
    m = re.search(r"Setup-(\d+\.\d+\.\d+)\.exe$", args.setup.name)
    if not m:
        raise SystemExit("expected dist/Sottovoce-Setup-<version>.exe")
    import server
    import updates
    version = m.group(1)
    if version != server.VERSION:
        raise SystemExit(f"the setup is {version}, server.VERSION is {server.VERSION}")
    raw = (json.dumps(manifest(args.setup, version), indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    sig = sign(raw, args.key)
    if not updates.verify(raw, sig):
        raise SystemExit("the signature doesn't verify with updates.PUBLIC_KEY: wrong key?")
    out = args.setup.parent / "latest.json"
    out.write_bytes(raw)
    out.with_name("latest.json.sig").write_text(sig + "\n", encoding="ascii")
    print(f"  {out}\n  {out}.sig\n\n  gh release upload v{version} {out} {out}.sig")


if __name__ == "__main__":
    main()
