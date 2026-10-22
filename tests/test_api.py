"""The server's API on the fictional examples, without the model.

Everything the page does goes through here, so these are the page's
guarantees: what it reads, what it writes, and what it refuses.
"""
import json

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
