"""The server's API on the fictional examples, without the model.

Everything the page does goes through here, so these are the page's
guarantees: what it reads, what it writes, and what it refuses.
"""
import json

import pytest

from conftest import NORTHPINE, SUPPLIER


def test_history_is_newest_first(client):
    h = client.get("/api/history").json()["history"]
    stamps = [c["transcribed_at"] for c in h]
    assert stamps == sorted(stamps, reverse=True)
    assert "speech" not in h[0]                          # the map is for the strip only


def test_a_call_opens_with_lines_words_and_speakers(client):
    c = client.get(f"/api/history/{SUPPLIER}").json()
    assert c["two_tracks"] is True
    assert {s["speaker"] for s in c["segments"]} == {"Me", "Them"}
    assert all(s.get("words") for s in c["segments"])
    first = c["segments"][0]
    assert " ".join(w[2] for w in first["words"]) == first["text"]
    assert first["end"] > first["start"]


def test_the_folder_name_cannot_escape_the_data_folder(client):
    assert client.get("/api/history/..%2F..%2Fserver.py").status_code == 404
    assert client.get("/api/audio/..%2Fglossary.txt").status_code == 404


def test_search_finds_and_names_the_minute(client):
    r = client.get("/api/search", params={"q": "photos"}).json()
    assert r["total"] >= 2
    hit = r["results"][0]["lines"][0]
    assert "photo" in hit["snippet"].lower() and ":" in hit["minute"]


def test_a_correction_keeps_the_speaker_the_before_and_the_word_times(client, data):
    before = client.get(f"/api/history/{SUPPLIER}").json()["segments"][0]
    new = before["text"].replace("Tomasz", "Tomek")
    r = client.post(f"/api/correct/{SUPPLIER}", json={"index": 0, "text": new}).json()
    assert r["saved"]
    after = client.get(f"/api/history/{SUPPLIER}").json()["segments"][0]
    assert after["text"] == new and after["speaker"] == "Me"
    assert after["words"][0][:2] == before["words"][0][:2]          # "Hi" kept its time
    d = data / "transcripts" / SUPPLIER
    log = [json.loads(x) for x in (d / "corrections.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[-1]["before"] == before["text"] and log[-1]["after"] == new
    assert "[Me] " + new in next(d.glob("*.txt")).read_text(encoding="utf-8")
    assert "Tomek" in next(d.glob("*.md")).read_text(encoding="utf-8")


def test_a_correction_refuses_nonsense(client):
    assert client.post(f"/api/correct/{NORTHPINE}", json={"index": 999, "text": "x"}).status_code == 400
    assert client.post(f"/api/correct/{NORTHPINE}", json={"index": 0, "text": " "}).status_code == 400


def test_the_glossary_applies_again_to_an_old_call(client, data):
    added = client.post("/api/glossary", json={"right": "Tomek", "variants": ["Tomasz"]}).json()
    assert added["added"]
    r = client.post(f"/api/reapply/{SUPPLIER}").json()
    assert r["corrected"] == 2 and r["names"] == {"Tomek": 2}
    c = client.get(f"/api/history/{SUPPLIER}").json()
    assert c["names_corrected"] == 2
    assert all(" ".join(w[2] for w in s["words"]) == s["text"] for s in c["segments"])
    assert client.post(f"/api/reapply/{SUPPLIER}").json()["corrected"] == 0


def test_the_glossary_refuses_rules_that_would_break_it(client):
    for body in ({"right": "", "variants": ["a"]}, {"right": "A <- B", "variants": ["c"]},
                 {"right": "A", "variants": ["b, c"]}, {"right": "Same", "variants": ["same"]}):
        assert client.post("/api/glossary", json=body).status_code == 400


def test_downloads_in_every_format(client):
    base = f"/api/history/{SUPPLIER}/download"
    assert client.get(base + ".txt").text.startswith("[00:00] [Me] Hi Tomasz")
    srt = client.get(base + ".srt").text
    assert srt.startswith("1\n00:00:00,000 --> ") and "Me: Hi Tomasz" in srt
    assert client.get(base + ".vtt").text.startswith("WEBVTT")
    j = client.get(base + ".json").json()
    assert j["lines"][0]["speaker"] == "Me" and j["lines"][0]["words"][0]["word"] == "Hi"
    assert client.get(base + ".exe").status_code == 404


def test_no_model_means_no_transcription_but_everything_else(client):
    r = client.post("/api/transcribe", files={"file": ("a.wav", b"RIFF", "audio/wav")})
    assert r.status_code == 503 and "--no-model" in r.json()["error"]
    assert client.get("/health").text == "ok"
    assert client.get("/api/status").json()["off"] is True


def test_a_recording_is_kept_piece_by_piece_until_finished_or_deleted(client, data):
    rid = client.post("/api/recordings", json={"name": "Weekly"}).json()["id"]
    for piece in (b"one-", b"two-", b"three"):
        client.post(f"/api/recordings/{rid}/chunk", content=piece)
    listed = client.get("/api/recordings").json()["recordings"]
    assert [(r["id"], r["name"], r["bytes"]) for r in listed] == [(rid, "Weekly", 13)]
    assert (data / "transcripts" / "_recordings" / f"{rid}.webm").read_bytes() == b"one-two-three"
    # Without the model it cannot be transcribed, and must not be lost either.
    assert client.post(f"/api/recordings/{rid}/finish", json={}).status_code == 503
    assert client.get("/api/recordings").json()["recordings"]
    assert client.delete(f"/api/recordings/{rid}").json()["deleted"]
    assert client.get("/api/recordings").json()["recordings"] == []


def test_recording_ids_are_checked(client):
    assert client.post("/api/recordings/..%2F..%2Fx/chunk", content=b"x").status_code == 404
    assert client.delete("/api/recordings/nothex").status_code == 404


def test_summary_without_an_llm_explains_itself(client, monkeypatch):
    import summary
    monkeypatch.setattr(summary, "who_answers", lambda: None)
    monkeypatch.setattr(summary, "builtin", lambda: None)       # and no GPU for the built-in one
    assert client.get("/api/llm").json()["available"] is False
    assert client.get(f"/api/history/{NORTHPINE}").json()["summary"]      # the saved one stays
    r = client.post(f"/api/summary/{NORTHPINE}?redo=true")
    assert r.status_code == 503 and "no LLM" in r.json()["error"]



def test_voices_are_listed_with_talk_time_and_named_without_touching_the_text(client, data):
    o = client.get(f"/api/history/{NORTHPINE}").json()
    assert [x["tag"] for x in o["speakers"]] == ["Voice 1", "Voice 2", "Voice 3"]
    assert [x["lines"] for x in o["speakers"]] == [22, 22, 10]
    assert all(x["seconds"] > 60 and x["name"] is None for x in o["speakers"])
    assert o["speakers_found"] == 3

    r = client.post(f"/api/speakers/{NORTHPINE}", json={"names": {"Voice 1": "  Maya ", "Voice 3": "Priya"}})
    assert r.json()["speaker_names"] == {"Voice 1": "Maya", "Voice 3": "Priya"}
    d = data / "transcripts" / NORTHPINE
    assert "[Voice 1]" in (d / "Northpine launch sync.txt").read_text(encoding="utf-8")
    assert "· Maya**" in (d / "Northpine launch sync.md").read_text(encoding="utf-8")
    base = f"/api/history/{NORTHPINE}/download"
    assert client.get(base + ".txt").text.startswith("[00:00] [Maya] Okay")
    assert "Priya:" in client.get(base + ".srt").text
    # An empty name gives the label back.
    r = client.post(f"/api/speakers/{NORTHPINE}", json={"names": {"Voice 1": ""}})
    assert r.json()["speaker_names"] == {"Voice 3": "Priya"}


def test_voice_names_are_checked(client):
    url = f"/api/speakers/{NORTHPINE}"
    assert client.post(url, json={"names": {"Voice 9": "X"}}).status_code == 400
    assert client.post(url, json={"names": {"Voice 1": "[Me]"}}).status_code == 400
    assert client.post(url, json={"names": {"Voice 1": "x" * 41}}).status_code == 400
    assert client.post(url, json={}).status_code == 400
    assert client.post("/api/speakers/nowhere", json={"names": {}}).status_code == 404


def test_telling_voices_apart_later_needs_the_packages_and_the_recording(client, monkeypatch):
    import server
    monkeypatch.setattr(server, "voices_installed", lambda: False)
    r = client.post(f"/api/voices/{NORTHPINE}")
    assert r.status_code == 503 and "pip install" in r.json()["error"]
    monkeypatch.setattr(server, "voices_installed", lambda: True)
    r = client.post(f"/api/voices/{NORTHPINE}")              # the examples carry no audio
    assert r.status_code == 404 and "recording" in r.json()["error"]
    assert client.post("/api/voices/nowhere").status_code == 404


# --- adding first, transcribing when asked ------------------------------------------

def fake_run(monkeypatch, fail=False):
    """Whisper's place taken by a function that returns two lines at once."""
    import server
    import transcribe as T

    def run(source, language=None, progress=None, **kw):
        if fail:
            raise RuntimeError("the decoder gave up")
        progress and progress("transcribing", 4.0)
        words = [[0.0, 0.4, "Hello"], [0.4, 0.9, "there."], [1.2, 1.6, "Second"], [1.6, 2.0, "line."]]
        segs = T.lines_from_words(words, None, {0, 2})
        return {"segments": segs, "seconds": 4.0, "speech_seconds": 3.0, "corrected": {},
                "phantoms": [], "speech": [(0.0, 2.0)], "language": language or "en",
                "word_times": "estimated"}

    monkeypatch.setattr(server.T, "run", run)
    monkeypatch.setitem(server.engine_state, "ready", True)
    monkeypatch.setitem(server.engine_state, "off", False)


def wait_for(client, folder, status, tries=200):
    import time
    for _ in range(tries):
        e = next((e for e in client.get("/api/history").json()["history"] if e["folder"] == folder), None)
        if e and e["status"] == status:
            return e
        time.sleep(0.02)
    raise AssertionError(f"{folder} never became {status}: {e}")


def test_an_added_recording_waits_and_is_transcribed_when_asked(client, data, monkeypatch):
    r = client.post("/api/uploads", files={"file": ("Weekly sync.m4a", b"not really audio", "audio/mp4")})
    folder = r.json()["folder"]
    assert folder.endswith("_Weekly sync")
    e = wait_for(client, folder, "waiting")
    assert e["name"] == "Weekly sync.m4a" and e["words"] == 0
    o = client.get(f"/api/history/{folder}").json()
    assert o["pending"] and o["status"] == "waiting" and o["audio"] == "Weekly sync.m4a"
    # Without the model it waits, it is not lost.
    assert client.post(f"/api/transcribe/{folder}", json={}).status_code == 503

    fake_run(monkeypatch)
    r = client.post(f"/api/transcribe/{folder}", json={"language": "en", "precise": True})
    assert "job" in r.json()
    e = wait_for(client, folder, "done")
    assert e["words"] == 4 and e["language"] == "en" and "uploaded_at" in e
    assert [s["text"] for s in client.get(f"/api/history/{folder}").json()["segments"]] \
        == ["Hello there.", "Second line."]
    assert client.post(f"/api/transcribe/{folder}", json={}).status_code == 409   # done already


def test_a_failed_transcription_keeps_the_recording(client, data, monkeypatch):
    folder = client.post("/api/uploads", files={"file": ("Broken.wav", b"x", "audio/wav")}).json()["folder"]
    fake_run(monkeypatch, fail=True)
    client.post(f"/api/transcribe/{folder}", json={})
    e = wait_for(client, folder, "failed")
    assert "decoder gave up" in e["error"]
    assert (data / "transcripts" / folder / "Broken.wav").exists()
    fake_run(monkeypatch)
    client.post(f"/api/transcribe/{folder}", json={})
    wait_for(client, folder, "done")


def test_a_restart_puts_an_interrupted_transcription_back_to_waiting(client, data):
    import server
    folder = client.post("/api/uploads", files={"file": ("Cut.wav", b"x", "audio/wav")}).json()["folder"]
    d = data / "transcripts" / folder
    server.write_info(d, {**server.read_info(d), "status": "transcribing"})
    server.sweep()
    assert server.read_info(d)["status"] == "waiting"


def test_a_call_is_renamed_with_its_files(client, data):
    r = client.post(f"/api/history/{SUPPLIER}/rename", json={"name": "  Brenna  Print, October "})
    new = r.json()["folder"]
    assert new == "2026-10-22_Brenna Print, October"
    d = data / "transcripts" / new
    assert sorted(f.name for f in d.iterdir() if f.suffix in (".txt", ".md")) \
        == ["Brenna Print, October.md", "Brenna Print, October.txt"]
    o = client.get(f"/api/history/{new}").json()
    assert o["name"] == "Brenna Print, October" and len(o["segments"]) == 13
    assert not (data / "transcripts" / SUPPLIER).exists()
    assert client.post(f"/api/history/{new}/rename", json={"name": " "}).status_code == 400
    assert client.post(f"/api/history/{new}/rename",
                       json={"name": "Northpine launch sync"}).status_code == 200   # another day: no clash


def test_renaming_onto_another_call_is_refused(client):
    r = client.post(f"/api/history/{NORTHPINE}/rename", json={"name": "Northpine launch sync"})
    assert r.status_code == 200                                # same name: nothing to do
    import server
    d = server.DATA / "2026-10-21_Other"
    d.mkdir()
    server.write_info(d, {"original": "x.wav"})
    assert client.post(f"/api/history/{NORTHPINE}/rename", json={"name": "Other"}).status_code == 409


def test_deleting_moves_the_call_to_a_bin(client, data):
    r = client.delete(f"/api/history/{NORTHPINE}")
    assert r.json() == {"deleted": True, "kept_in": f"_deleted/{NORTHPINE}"}
    assert (data / "transcripts" / "_deleted" / NORTHPINE / "info.json").exists()
    folders = [e["folder"] for e in client.get("/api/history").json()["history"]]
    assert NORTHPINE not in folders and "_deleted" not in folders
    assert client.get("/api/search?q=Trailhead").json()["total"] == 0
    assert client.delete(f"/api/history/{NORTHPINE}").status_code == 404


# --- the PIN, with --lan -------------------------------------------------------------

def lan_client(monkeypatch, tmp_path, host):
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "PIN_FILE", tmp_path / ".lan-pin")
    monkeypatch.setattr(server, "lan", {"pin": None, "secret": b""})
    monkeypatch.setattr(server, "pin_tries", {})
    pin = server.pin_setup("246810")
    return TestClient(server.app, client=(host, 50000)), pin


def test_another_device_needs_the_pin_once(client, monkeypatch, tmp_path):
    phone, pin = lan_client(monkeypatch, tmp_path, "192.168.1.50")
    assert phone.get("/api/history").status_code == 401
    r = phone.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pin"
    assert "Sottovoce" in phone.get("/pin").text
    assert phone.get("/health").status_code == 200              # allowed: says nothing
    assert phone.post("/api/pin", json={"pin": "000000"}).status_code == 403
    assert phone.post("/api/pin", json={"pin": pin}).json() == {"ok": True}
    assert phone.get("/api/history").status_code == 200          # the cookie lets it in
    assert phone.get(f"/api/history/{NORTHPINE}").json()["name"]


def test_this_computer_is_never_asked(client, monkeypatch, tmp_path):
    here, _ = lan_client(monkeypatch, tmp_path, "127.0.0.1")
    assert here.get("/api/history").status_code == 200


def test_five_wrong_pins_lock_a_device_out(client, monkeypatch, tmp_path):
    phone, pin = lan_client(monkeypatch, tmp_path, "192.168.1.51")
    for _ in range(5):
        assert phone.post("/api/pin", json={"pin": "111111"}).status_code == 403
    assert phone.post("/api/pin", json={"pin": pin}).status_code == 429     # even the right one


def test_the_pin_is_kept_and_a_new_one_logs_everyone_out(client, monkeypatch, tmp_path):
    import server
    phone, pin = lan_client(monkeypatch, tmp_path, "192.168.1.52")
    phone.post("/api/pin", json={"pin": pin})
    assert server.pin_setup() == pin                                # kept across restarts
    assert phone.get("/api/history").status_code == 200
    server.pin_setup("135790")                                      # changed
    assert phone.get("/api/history").status_code == 401


# --- notes and the follow-up email ---------------------------------------------------

def test_notes_put_summary_and_transcript_in_one_file_in_the_calls_language(client):
    r = client.get(f"/api/history/{NORTHPINE}/download.notes")
    assert "Northpine%20launch%20sync%20-%20notes.md" in r.headers["content-disposition"]
    t = r.text
    assert t.startswith("# Northpine launch sync\n")
    assert "## Summary" in t and "### Decided" in t and "## Transcript" in t
    assert "People: Voice 1 (02:24), Voice 2 (01:42), Voice 3 (01:19)" in t
    assert "**00:00 · Voice 1** — Okay, I think everyone's here." in t
    it = client.get("/api/history/2026-10-17_Kickoff Halden Studio/download.notes")
    assert "appunti.md" in it.headers["content-disposition"]
    assert "## Riassunto" in it.text and "## Trascrizione" in it.text and "Nessun riassunto" in it.text


def test_the_follow_up_is_written_saved_edited_and_dropped_when_the_lines_change(client, data, monkeypatch):
    import summary
    asked = {}

    def fake(text, me=None, others=None, known=False, model=None):
        asked.update(me=me, others=others, known=known, text=text)
        return {"text": "Subject: next steps\n\nHi Tomasz", "model": "m", "program": "p"}

    monkeypatch.setattr(summary, "followup", fake)
    client.post(f"/api/speakers/{SUPPLIER}", json={"names": {"Me": "Daniel", "Them": "Tomasz"}})
    r = client.post(f"/api/followup/{SUPPLIER}").json()
    assert r["text"].startswith("Subject: next steps")
    assert asked["me"] == "Daniel" and asked["others"] == ["Tomasz"] and asked["known"]
    assert asked["text"].startswith("Daniel: Hi Tomasz")
    assert client.get(f"/api/history/{SUPPLIER}").json()["followup"].startswith("Subject")
    assert client.post(f"/api/followup/{SUPPLIER}").json()["from_disk"]           # not rewritten
    client.post(f"/api/followup/{SUPPLIER}", json={"text": "Subject: mine"})      # edited by hand
    assert client.get(f"/api/history/{SUPPLIER}").json()["followup"] == "Subject: mine\n"
    client.post(f"/api/reapply/{SUPPLIER}")
    # the glossary did not change this call: the email stays
    assert (data / "transcripts" / SUPPLIER / "followup.md").exists()


def test_without_an_llm_the_follow_up_explains_itself(client, monkeypatch):
    import summary
    monkeypatch.setattr(summary, "who_answers", lambda: None)
    monkeypatch.setattr(summary, "builtin", lambda: None)       # and no GPU for the built-in one
    r = client.post(f"/api/followup/{NORTHPINE}")
    assert r.status_code == 503 and "no LLM" in r.json()["error"]


def test_with_no_server_the_built_in_model_writes(client, monkeypatch):
    import summary
    monkeypatch.setattr(summary, "who_answers", lambda: None)
    monkeypatch.setattr(summary, "builtin", lambda: {"program": "Sottovoce", "model": "Qwen3-4B-Instruct-2507",
                                                     "builtin": True, "downloaded": False})
    assert client.get("/api/llm").json()["builtin"] is True
    seen = {}

    def fake(instructions, request):
        seen["request"] = request
        return {"text": "Oggetto: prossimi passi", "model": "Qwen3-4B-Instruct-2507", "program": "Sottovoce"}

    monkeypatch.setattr(summary, "_builtin_ask", fake)
    r = client.post(f"/api/followup/{NORTHPINE}").json()
    assert r["text"] == "Oggetto: prossimi passi" and "Voice 1:" in seen["request"]



# --- only its own address, only its own pages -----------------------------------------

def guarded(monkeypatch, *addresses):
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "allowed_hosts", server.hosts_for(8200, addresses))
    return TestClient(server.app, base_url="http://127.0.0.1:8200")


def test_a_foreign_host_is_refused_as_dns_rebinding_would_send_it(client, monkeypatch):
    c = guarded(monkeypatch)
    assert c.get("/api/history").status_code == 200
    assert c.get("/api/history", headers={"host": "localhost:8200"}).status_code == 200
    assert c.get("/api/history", headers={"host": "evil.example:8200"}).status_code == 403
    assert c.get("/api/history", headers={"host": "127.0.0.1:9999"}).status_code == 403


def test_with_lan_this_computers_address_is_accepted(client, monkeypatch):
    c = guarded(monkeypatch, "192.168.1.12")
    assert c.get("/api/history", headers={"host": "192.168.1.12:8200"}).status_code == 200
    assert c.get("/api/history", headers={"host": "192.168.1.99:8200"}).status_code == 403


def test_a_change_sent_from_another_site_is_refused(client, monkeypatch):
    c = guarded(monkeypatch)
    url = "/api/recordings"                   # harmless: it only starts an empty recording
    assert c.post(url, json={}, headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post(url, json={}, headers={"origin": "null"}).status_code == 403
    assert c.post(url, json={}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    # its own page, and a script with no Origin at all
    assert c.post(url, json={}, headers={"origin": "http://127.0.0.1:8200"}).status_code == 200
    assert c.post(url, json={}).status_code == 200
    # reading is not a change: a cross-site GET still can't read the answer (same-origin policy)
    assert c.get("/api/status", headers={"origin": "https://evil.example"}).status_code == 200


def test_info_is_never_read_half_written(data):
    import threading
    import server
    d = data / "transcripts" / NORTHPINE
    info = server.read_info(d)
    stop, bad = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:
                server.read_info(d)
            except (ValueError, OSError) as e:   # an empty or cut file, or refused
                bad.append(e)
    r = threading.Thread(target=reader)
    r.start()
    for i in range(200):
        server.write_info(d, {**info, "n": i})
    stop.set()
    r.join()
    assert bad == [] and server.read_info(d)["n"] == 199
    assert not (d / "info.json.tmp").exists()



# --- recording from the computer itself (recorder.py), with a stand-in -------------

class FakeCapture:
    """Writes a second of a quiet stereo WAV when stopped: no devices."""

    def __init__(self, path):
        self.path, self.seconds, self.levels, self.error = path, 0.0, [0.2, 0.1], None

    def start(self):
        import recorder
        self.path.write_bytes(recorder.header(0))

    def stop(self):
        import recorder
        self.path.write_bytes(recorder.header(0) + b"\x00\x00" * 2 * recorder.RATE)
        return self.path


@pytest.fixture
def here(client, monkeypatch):
    """The same server, asked from the computer it runs on."""
    import recorder
    import server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(recorder, "available", lambda: True)
    monkeypatch.setattr(recorder, "Capture", FakeCapture)
    yield TestClient(server.app, client=("127.0.0.1", 50000))
    server.capture = None


def test_a_phone_cannot_switch_on_the_computers_microphone(here, client):
    assert client.post("/api/capture", json={}).status_code == 403          # not 127.0.0.1
    assert here.get("/api/capture").json() == {"available": True, "recording": None}


def test_a_computer_recording_is_one_at_a_time_and_discarded_without_a_trace(here, data):
    rid = here.post("/api/capture", json={"name": "Weekly"}).json()["id"]
    now = here.get("/api/capture").json()["recording"]
    assert now["id"] == rid and now["name"] == "Weekly" and now["levels"] == [0.2, 0.1]
    assert here.post("/api/capture", json={}).status_code == 409
    assert here.get("/api/recordings").json()["recordings"] == []          # live, not interrupted
    assert here.post("/api/shutdown").status_code == 409                    # the power button waits
    assert here.post("/api/capture/stop", json={"keep": False}).json() == {"discarded": True}
    assert list((data / "transcripts" / "_recordings").iterdir()) == []


def test_a_kept_recording_without_the_model_waits_with_the_choices_made(here, data):
    here.post("/api/capture", json={"name": "Weekly", "language": "it", "voices": True})
    r = here.post("/api/capture/stop", json={})
    assert r.status_code == 503                                             # --no-model here
    listed = here.get("/api/recordings").json()["recordings"]
    assert [(x["name"], x["language"], x["voices"], x["from"]) for x in listed] == [("Weekly", "it", True, "computer")]
    assert listed[0]["bytes"] == 44 + 4 * 48000
