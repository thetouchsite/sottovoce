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
