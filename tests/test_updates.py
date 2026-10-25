"""Updates: what is believed, what is installed, and when. No network: GitHub,
the download and the setup are stood in for; the signatures are real.
"""
import base64
import hashlib
import io
import json
import sys

import pytest

import server
import updates as U

from conftest import ROOT

sys.path.insert(0, str(ROOT / "installer"))
import sign_release  # noqa: E402


@pytest.fixture
def key(tmp_path, monkeypatch):
    """A fresh key pair: the private key in a file, the public one in updates.py."""
    path = tmp_path / "key.pem"
    monkeypatch.setattr(U, "PUBLIC_KEY", sign_release.new_key(path))
    return path


def signed(key, **fields):
    m = {"version": "9.9.9", "notes": "Better.", "windows": {"url": "https://example.invalid/S.exe",
                                                            "sha256": "0" * 64, "size": 3}}
    m.update(fields)
    raw = json.dumps(m).encode()
    return raw, sign_release.sign(raw, key).encode()


def test_versions_compare_as_numbers():
    assert U.newer("1.10.0", "1.9.0") and not U.newer("1.8.0", "1.8.0") and not U.newer("v1.7.1", "1.8.0")
    assert U.version_tuple("v1.8.0") == (1, 8, 0)


def test_only_our_signature_is_believed(key, tmp_path):
    raw, sig = signed(key)
    assert U.verify(raw, sig)
    assert not U.verify(raw.replace(b"9.9.9", b"9.9.8"), sig)            # the manifest changed
    other = tmp_path / "other.pem"
    sign_release.new_key(other)
    assert not U.verify(raw, sign_release.sign(raw, other).encode())   # someone else's key
    assert not U.verify(raw, b"not a signature")
    assert not U.verify(raw, sig, key="")


def test_the_published_key_is_a_real_ed25519_key():
    assert len(base64.b64decode(U.PUBLIC_KEY)) == 32


def test_a_newer_signed_release_is_offered(key, monkeypatch):
    raw, sig = signed(key)
    monkeypatch.setattr(U, "_get", lambda url, timeout=U.TIMEOUT: sig if url.endswith(".sig") else raw)
    assert U.check("1.8.0")["available"]["version"] == "9.9.9"
    assert U.check("9.9.9")["available"] is None


def test_an_unsigned_release_is_ignored(key, monkeypatch):
    raw, sig = signed(key)
    monkeypatch.setattr(U, "_get", lambda url, timeout=U.TIMEOUT: b"AAAA" if url.endswith(".sig") else raw)
    r = U.check("1.8.0")
    assert "signature" in r["error"] and "available" not in r


def test_no_network_is_not_a_failure(monkeypatch):
    def down(url, timeout=U.TIMEOUT):
        raise OSError("offline")
    monkeypatch.setattr(U, "_get", down)
    assert "could not reach" in U.check("1.8.0")["error"]


def serve(monkeypatch, data):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(U.urllib.request, "urlopen", lambda req, timeout=None: R(data))


def test_a_setup_that_is_not_the_signed_one_is_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "folder", lambda: tmp_path)
    serve(monkeypatch, b"tampered")
    m = {"windows": {"url": "https://x/Sottovoce-Setup-9.9.9.exe", "sha256": hashlib.sha256(b"ours").hexdigest()}}
    with pytest.raises(ValueError):
        U.download(m)
    assert list(tmp_path.iterdir()) == []


def test_the_signed_setup_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "folder", lambda: tmp_path)
    serve(monkeypatch, b"ours")
    m = {"windows": {"url": "https://x/Sottovoce-Setup-9.9.9.exe", "sha256": hashlib.sha256(b"ours").hexdigest(),
                     "size": 4}}
    seen = []
    out = U.download(m, lambda d, t: seen.append((d, t)))
    assert out.name == "Sottovoce-Setup-9.9.9.exe" and out.read_bytes() == b"ours" and seen[-1] == (4, 4)


def test_the_setup_runs_after_sottovoce_has_quit_and_starts_it_again(tmp_path):
    cmd = " ".join(U.helper(tmp_path / "Sottovoce-Setup-9.9.9.exe", 4242))
    assert "Wait-Process -Id 4242" in cmd
    assert cmd.index("Wait-Process") < cmd.index("Start-Process")
    assert "/VERYSILENT" in cmd and "/RELAUNCH=1" in cmd and "-WindowStyle Hidden" in cmd
    assert "-Wait " not in cmd.replace("Wait-Process", "")              # it would wait for the new Sottovoce too


def test_a_release_manifest_says_what_the_setup_is(tmp_path):
    setup = tmp_path / "Sottovoce-Setup-1.8.0.exe"
    setup.write_bytes(b"setup")
    m = sign_release.manifest(setup, "1.8.0")
    assert m["windows"]["sha256"] == hashlib.sha256(b"setup").hexdigest() and m["windows"]["size"] == 5
    assert m["windows"]["url"].endswith("/releases/download/v1.8.0/Sottovoce-Setup-1.8.0.exe")
    assert m["notes"].startswith("Sottovoce runs on the computer you have")      # from CHANGELOG.md


def test_a_second_key_is_refused(tmp_path):
    sign_release.new_key(tmp_path / "k.pem")
    with pytest.raises(SystemExit):
        sign_release.new_key(tmp_path / "k.pem")


# --- the server ------------------------------------------------------------------------

@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(server, "update", {"state": "idle", "available": None, "checked_at": None,
                                           "error": None, "done": 0, "total": 0})
    monkeypatch.setattr(server, "update_prefs", {"check": True})
    monkeypatch.setattr(server, "update_off", False)


def test_checking_can_be_turned_off_and_stays_off(client, data, fresh):
    assert client.get("/api/update").json()["check"] is True
    client.post("/api/update", json={"check": False})
    saved = json.loads((data / "transcripts" / "_settings.json").read_text(encoding="utf-8"))
    assert saved["updates"] == {"check": False}
    server.update_prefs["check"] = True
    server.load_settings()
    assert server.update_prefs["check"] is False
    assert not server.checks_updates()


def here():
    from fastapi.testclient import TestClient
    return TestClient(server.app, client=("127.0.0.1", 50000))


def test_an_update_is_installed_only_when_there_is_one_and_from_this_computer(client, fresh, monkeypatch):
    monkeypatch.setattr(U, "installed", lambda: True)
    assert here().post("/api/update/install").status_code == 400                      # nothing to install
    server.update["available"] = {"version": "9.9.9", "windows": {"size": 1}}
    assert client.post("/api/update/install").status_code == 403                      # not from this computer


def test_a_copy_not_installed_by_the_setup_is_told_how(client, fresh, monkeypatch):
    monkeypatch.setattr(U, "installed", lambda: False)
    server.update["available"] = {"version": "9.9.9", "windows": {"size": 1}}
    r = here().post("/api/update/install")
    assert r.status_code == 400 and r.json()["how"]


def test_the_update_waits_for_the_call_then_quits(fresh, monkeypatch, tmp_path):
    events = []
    server.update["available"] = {"version": "9.9.9", "windows": {"size": 1}}
    monkeypatch.setattr(U, "download", lambda m, progress=None: tmp_path / "S.exe")
    busy = iter([True, True, False])
    monkeypatch.setattr(server, "working", lambda: events.append("asked") or next(busy))
    monkeypatch.setattr(server.time, "sleep", lambda s: None)
    monkeypatch.setattr(U, "install", lambda setup: events.append("install"))
    monkeypatch.setattr(server, "quit_app", lambda: events.append("quit"))
    server.install_update()
    assert events == ["asked", "asked", "asked", "install", "quit"]
    assert server.update["state"] == "installing"


def test_a_failed_download_says_why_and_installs_nothing(fresh, monkeypatch):
    server.update["available"] = {"version": "9.9.9", "windows": {"size": 1}}

    def bad(m, progress=None):
        raise ValueError("the downloaded setup is not the one that was signed: deleted")
    monkeypatch.setattr(U, "download", bad)
    monkeypatch.setattr(U, "install", lambda setup: pytest.fail("installed a bad setup"))
    server.install_update()
    assert server.update["state"] == "error" and "not the one that was signed" in server.update["error"]
