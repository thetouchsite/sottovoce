"""The engine's own logic: what can be checked without Whisper.

Each test names the bug or the measurement it protects. Several of them were
real bugs once, caught by eye; these catch them the next time.
"""
import transcribe as T


def test_glossary_respects_word_boundaries_and_case(tmp_path, monkeypatch):
    g = tmp_path / "glossary.txt"
    g.write_text("# comment\nNorthpine <- North pine, Nord pine\nLena <- Lina\n", encoding="utf-8")
    monkeypatch.setattr(T, "GLOSSARY", g)
    segs = [{"start": 0, "text": "north Pine and NORD PINE called Lina, not Linata."}]
    done = T.apply_glossary(segs, T.glossary())
    assert segs[0]["text"] == "Northpine and Northpine called Lena, not Linata."
    assert done == {"Northpine": 2, "Lena": 1}


def test_missing_glossary_corrects_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "GLOSSARY", tmp_path / "absent.txt")
    assert T.glossary() == []


def test_realign_keeps_times_of_unchanged_words():
    words = [[0.0, 0.5, "The"], [0.5, 1.0, "North"], [1.0, 1.5, "pine"], [1.5, 2.0, "team"]]
    out = T.realign(words, "The Northpine team")
    assert [w[2] for w in out] == ["The", "Northpine", "team"]
    assert out[0][:2] == [0.0, 0.5] and out[2][:2] == [1.5, 2.0]
    assert out[1][:2] == [0.5, 1.5]          # the replaced span, whole


def test_realign_joined_tokens_are_the_new_text():
    words = [[0, 1, "a"], [1, 2, "b"], [2, 3, "c"]]
    for text in ("a b c", "a x c", "a b c d", "x", "a  b   c"):
        assert " ".join(w[2] for w in T.realign(words, text)) == " ".join(text.split())


def test_spread_shares_a_segment_by_word_length():
    words, breaks = T.spread([{"text": "a extraordinary", "timestamp": (10.0, 12.0)},
                              {"text": "next", "timestamp": (13.0, 14.0)}])
    assert breaks == {0, 2}
    a, long_word = words[0], words[1]
    assert a[0] == 10.0 and abs(long_word[1] - 12.0) < 1e-6
    assert (long_word[1] - long_word[0]) > 5 * (a[1] - a[0])


def test_tidy_never_goes_backwards_nor_leaves_empty_words():
    out = T.tidy([[1.0, 1.2, "a"], [0.8, 0.8, "b"], [1.5, 1.5, "c"]])
    starts = [w[0] for w in out]
    assert starts == sorted(starts)
    assert all(w[1] - w[0] >= 0.05 for w in out)


def test_lines_follow_whisper_segments_and_split_on_speaker_change():
    words = [[0, 1, "Hello"], [1, 2, "there."], [2, 3, "Hi!"], [3, 4, "Next"], [4, 5, "line"]]
    lines = T.lines_from_words(words, ["Me", "Me", "Them", "Them", "Them"], breaks={0, 3})
    assert [(l["speaker"], l["text"]) for l in lines] == [
        ("Me", "Hello there."), ("Them", "Hi!"), ("Them", "Next line")]


def test_rebuilt_lines_break_on_sentences_and_pauses():
    words = [[0, .3, "One"], [.3, .6, "two"], [.6, .9, "three."], [.9, 1.2, "Four"],
             [3.0, 3.3, "after"], [3.3, 3.6, "pause"]]
    assert [l["text"] for l in T.lines_from_words(words)] == ["One two three.", "Four", "after pause"]


def test_speakers_from_two_tracks():
    import numpy as np
    rate = 1000
    t = np.arange(4 * rate)
    me = np.where(t < 2 * rate, 0.5, 0.0) + 0.001
    them = np.where(t >= 2 * rate, 0.5, 0.0) + 0.001
    me = me + 0.05 * them                      # the microphone hears the speakers, faintly
    words = [[0.2, 0.6, "a"], [1.0, 1.5, "b"], [2.3, 2.8, "c"], [3.1, 3.6, "d"]]
    assert T.label_speakers(words, me, them, rate) == ["Me", "Me", "Them", "Them"]


def test_a_muted_microphone_makes_everything_theirs():
    import numpy as np
    words = [[0.1, 0.4, "a"], [0.5, 0.9, "b"]]
    assert T.label_speakers(words, np.zeros(1000), np.full(1000, 0.3), 1000) == ["Them", "Them"]


def test_txt_round_trip_with_speakers():
    segs = [{"start": 5, "text": "Hello", "speaker": "Me"}, {"start": 65, "text": "[Music] not a tag"}]
    txt = T.as_txt(segs)
    assert txt == "[00:05] [Me] Hello\n[01:05] [Music] not a tag\n"
    assert [T.parse_line(x) for x in txt.splitlines()] == [(5, "Me", "Hello"),
                                                          (65, None, "[Music] not a tag")]


def test_paragraphs_break_on_speaker_and_carry_words():
    segs = [{"start": 0, "end": 1, "text": "a", "speaker": "Me", "words": [[0, 1, "a"]]},
            {"start": 1, "end": 2, "text": "b", "speaker": "Me", "words": [[1, 2, "b"]]},
            {"start": 2, "end": 3, "text": "c", "speaker": "Them", "words": None}]
    ps = T.paragraphs(segs)
    assert [(p["speaker"], p["text"]) for p in ps] == [("Me", "a b"), ("Them", "c")]
    assert ps[0]["words"] == [[0, 1, "a"], [1, 2, "b"]]
    assert "words" not in ps[1]


def test_subtitles_never_run_through_a_silence():
    segs = [{"start": 0, "text": "short"}, {"start": 60, "text": "much later"}]
    assert T.ends(segs, 70)[0] < 2


def test_srt_and_vtt_format():
    segs = [{"start": 3661.5, "text": "hi", "speaker": "Them", "words": [[3661.5, 3662.25, "hi"]]}]
    assert T.as_srt(segs, 4000) == "1\n01:01:01,500 --> 01:01:02,250\nThem: hi\n"
    assert "01:01:01.500 --> 01:01:02.250\n<v Them>hi" in T.as_vtt(segs, 4000)


def test_phantoms_dropped_only_where_it_is_quiet():
    segs = [{"start": 10, "text": "Thanks for watching!"},
            {"start": 20, "text": "Grazie a tutti, a lunedì."},
            {"start": 30, "text": "A real sentence."}]
    loud_at_20 = lambda wav, start: -20.0 if start == 20 else -60.0
    dropped = T.drop_phantoms(segs, None, level=-24.0, volume=loud_at_20)
    assert [s["start"] for s in dropped] == [10]
    assert [s["start"] for s in segs] == [20, 30]
    assert T.suspicious(segs) == [segs[0]]
