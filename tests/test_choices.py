"""Where Whisper runs and who writes the summaries: the choices, what they
remember, and the programs started for them. No model, no GPU, no LM Studio
or Ollama needed: the hardware and the programs are stood in for.
"""
import json
import subprocess

import pytest

import server
import summary as S
import transcribe as T


@pytest.fixture
def paths(monkeypatch):
    """A computer with the paths asked for, and nothing chosen or measured."""
    def have(*found):
        monkeypatch.setattr(T, "_found", list(found))
        monkeypatch.setattr(T, "chosen", {"path": None, "turbo": False})
        monkeypatch.setattr(T, "measured", {})
        monkeypatch.setattr(T, "openvino", lambda: True)
        monkeypatch.delenv("SOTTOVOCE_ENGINE", raising=False)
    return have


@pytest.fixture
def no_llm_choice(monkeypatch):
    monkeypatch.setattr(S, "choice", {"program": None, "model": None})


# --- where Whisper runs -------------------------------------------------------------

def test_the_first_path_found_is_taken_unless_another_is_chosen(paths, monkeypatch):
    paths("cuda", "intel-gpu", "cpu")
    assert T.path() == "cuda" and T.model() == "openai/whisper-large-v3"
    T.choose("intel-gpu")
    assert T.path() == "intel-gpu" and T.model() == "OpenVINO/whisper-large-v3-int8-ov"
    monkeypatch.setenv("SOTTOVOCE_ENGINE", "cpu")              # forcing wins over choosing
    assert T.path() == "cpu"
    T.choose("")                                              # back to automatic
    monkeypatch.delenv("SOTTOVOCE_ENGINE")
    assert T.path() == "cuda"


def test_a_path_this_computer_does_not_have_falls_back_to_the_first(paths, monkeypatch):
    paths("intel-gpu", "cpu")
    monkeypatch.setenv("SOTTOVOCE_ENGINE", "cuda")
    assert T.path() == "intel-gpu"


def test_the_processor_runs_pytorch_where_openvino_is_missing(paths, monkeypatch):
    paths("cpu")
    monkeypatch.setattr(T, "openvino", lambda: False)
    assert T.program() == "torch" and T.model() == "openai/whisper-large-v3"


def test_turbo_changes_the_model_on_every_path(paths):
    paths("cuda", "cpu")
    T.choose(turbo=True)
    assert T.model("cuda") == "openai/whisper-large-v3-turbo"
    assert T.model("cpu") == "OpenVINO/whisper-large-v3-turbo-int8-ov"


def test_changing_path_lets_the_loaded_model_go(paths, monkeypatch):
    paths("cuda", "intel-gpu", "cpu")
    gone = []
    monkeypatch.setattr(T, "release", lambda: gone.append(1))
    T.choose("cuda")                                          # the same as automatic: nothing to do
    assert not gone
    T.choose("intel-gpu")
    assert gone == [1]


def test_the_speed_measured_here_wins_over_the_default(paths):
    paths("cuda", "cpu")
    assert T.speed() == T.SPEEDS[("cuda", False)][0] and T.speed(precise=True) == T.SPEEDS[("cuda", False)][1]
    T.measured[T.key()] = 9.5
    assert T.speed() == 9.5
    T.choose(turbo=True)
    assert T.speed() is None                                  # never measured: no estimate rather than a wrong one


def test_openvino_word_pieces_join_into_words():
    pieces = [(0.0, 0.4, " L"), (0.4, 0.9, "'incidente"), (0.9, 1.1, " è"), (1.1, 1.6, " avvenuto")]
    assert T.join_pieces(pieces) == [[0.0, 0.9, "L'incidente"], [0.9, 1.1, "è"], [1.1, 1.6, "avvenuto"]]


def test_languages_are_stored_as_codes_whoever_names_them():
    assert T._code("<|it|>") == "it"
    assert T._code("italian") == "it"
    assert T._code("en") == "en"


def test_with_no_language_it_is_found_first_and_the_call_is_transcribed_in_it(monkeypatch, tmp_path):
    asked = []

    class Engine:
        def language(self, audio):
            return "<|it|>"

        def segments(self, wav, language, speech=None):
            asked.append(language)
            return [{"text": " Buongiorno a tutti", "timestamp": (0.0, 1.5)}]

    monkeypatch.setattr(T, "engine", lambda: Engine())
    import numpy as np
    import soundfile as sf
    wav = tmp_path / "a.wav"
    sf.write(str(wav), np.zeros(16000, dtype="float32"), 16000)
    words, language, breaks = T.listen(wav)
    assert asked == ["it"] and language == "it"
    assert [w[2] for w in words] == ["Buongiorno", "a", "tutti"] and breaks == {0}


# --- what the server remembers ------------------------------------------------------

def test_the_choices_survive_a_restart(client, data, paths, no_llm_choice):
    paths("cuda", "intel-gpu", "cpu")
    assert client.post("/api/engine", json={"path": "intel-gpu", "turbo": True}).status_code == 200
    assert client.post("/api/llm/choice", json={"program": "LM Studio", "model": "gemma-4-e4b-it"}).status_code == 200
    saved = json.loads((data / "transcripts" / "_settings.json").read_text(encoding="utf-8"))
    assert saved["engine"] == {"path": "intel-gpu", "turbo": True}
    T.chosen.update(path=None, turbo=False)
    S.choice.update(program=None, model=None)
    server.load_settings()
    assert T.chosen == {"path": "intel-gpu", "turbo": True}
    assert S.choice == {"program": "LM Studio", "model": "gemma-4-e4b-it"}


def test_the_settings_file_is_not_a_call(client):
    server.save_settings()
    assert all(not c["folder"].startswith("_") for c in client.get("/api/history").json()["history"])


def test_a_path_that_is_not_here_is_refused(client, paths):
    paths("cpu")
    assert client.post("/api/engine", json={"path": "cuda"}).status_code == 400


def test_the_engine_view_lists_each_path_with_its_speed(client, paths, monkeypatch):
    paths("cuda", "intel-gpu", "cpu")
    monkeypatch.setattr(T, "downloaded", lambda repo=None: repo == "openai/whisper-large-v3")
    T.measured[T.key(False, "intel-gpu")] = 8.0
    e = client.get("/api/engine").json()
    assert e["path"] == "cuda" and e["automatic"] and e["can_measure"]
    by = {p["id"]: p for p in e["paths"]}
    assert by["cuda"]["downloaded"] and not by["intel-gpu"]["downloaded"]
    assert by["intel-gpu"]["speed"] == 8.0 and by["intel-gpu"]["measured"]
    assert by["intel-gpu"]["download_gb"] == T.SIZE_GB["OpenVINO/whisper-large-v3-int8-ov"]


def test_a_slow_call_moves_the_estimate_half_way(client, paths):
    paths("cpu")
    server.remember_speed("cpu|m|segments", 4.0)
    server.remember_speed("cpu|m|segments", 2.0)
    assert T.measured["cpu|m|segments"] == 3.0


@pytest.mark.parametrize("found, compared", [
    (("cuda", "intel-gpu", "cpu"), ["cuda", "intel-gpu"]),     # two GPUs: the processor would lose
    (("cuda", "cpu"), []),                                     # one way that matters: nothing to compare
    (("intel-gpu", "cpu"), ["intel-gpu", "cpu"]),              # a small Intel GPU can lose to the processor
    (("cpu",), []),
])
def test_what_is_worth_measuring(paths, found, compared):
    paths(*found)
    assert server.to_measure() == compared


def test_measuring_picks_the_fastest_and_says_so(client, data, paths, monkeypatch):
    paths("cuda", "intel-gpu", "cpu")
    fast = {"cuda": 6.0, "intel-gpu": 9.0}
    monkeypatch.setattr(T, "engine", lambda: None)
    monkeypatch.setattr(server, "latest_call",
                        lambda: (data / "transcripts" / "x.wav", "it"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)

    def run(wav, language):
        return {"seconds": 180.0, "transcribing_seconds": 180.0 / fast[T.path()], "engine": T.key()}
    monkeypatch.setattr(T, "run", run)
    server.measure_engines()
    assert server.measuring["state"] == "done" and server.measuring["results"] == fast
    assert T.path() == "intel-gpu" and not T.chosen["turbo"]
    assert T.measured[T.key(False, "cuda")] == 6.0


def test_a_failed_measurement_leaves_the_choice_as_it_was(client, paths, monkeypatch):
    paths("cuda", "intel-gpu", "cpu")
    monkeypatch.setattr(server, "latest_call", lambda: None)
    server.measure_engines()
    assert server.measuring["state"] == "error" and T.chosen["path"] is None


def test_no_estimate_when_the_speed_is_unknown(paths):
    paths("intel-gpu", "cpu")
    assert T.speed() == T.SPEEDS[("intel-gpu", False)][0]
    assert T.speed(precise=True) is None                      # the page then shows a moving bar


# --- who writes the summaries -------------------------------------------------------

def test_ollama_models_are_read_from_its_folder(tmp_path, monkeypatch):
    m = tmp_path / "manifests"
    for rel, size in (("registry.ollama.ai/library/llama3.2/latest", 2_000_000_000),
                      ("registry.ollama.ai/library/nomic-embed-text/latest", 300),
                      ("hf.co/someone/tiny-gguf/Q4_K_M", 1_000_000_000)):
        f = m / rel
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"layers": [{"size": size}]}), encoding="utf-8")
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path))
    ids = {x["id"]: x["gb"] for x in S.ollama_models()}
    assert ids == {"hf.co/someone/tiny-gguf:Q4_K_M": 1.0, "llama3.2:latest": 2.0}


def test_lmstudio_output_is_read_past_its_greeting():
    assert S._json_in('Waking up LM Studio service...\n[{"modelKey": "a"}]') == [{"modelKey": "a"}]
    assert S._json_in("nothing") is None


def test_lmstudio_lists_only_models_that_write(monkeypatch):
    monkeypatch.setattr(S, "lms", lambda: "lms")
    monkeypatch.setattr(S, "_cli", lambda args, timeout=60: json.dumps([
        {"type": "llm", "modelKey": "gemma-4-e4b-it", "displayName": "Gemma 4 E4B", "sizeBytes": 5_300_000_000},
        {"type": "embedding", "modelKey": "nomic-embed"}]))
    assert S.lmstudio_models() == [{"id": "gemma-4-e4b-it", "name": "Gemma 4 E4B", "gb": 5.3}]


def test_the_program_picked_is_started_and_asked_with_its_model(monkeypatch):
    monkeypatch.setattr(S, "choice", {"program": "LM Studio", "model": "gemma-4-e4b-it"})
    monkeypatch.setattr(S, "start", lambda program: 1234)
    monkeypatch.setattr(S, "who_answers", lambda: pytest.fail("the one picked is asked, not the first found"))
    sent = {}

    def post(url, body, timeout):
        sent.update(url=url, body=body)
        return {"choices": [{"message": {"content": "Three lines."}}], "model": body["model"]}
    monkeypatch.setattr(S, "_post", post)
    r = S.ask("instructions", "request")
    assert r["text"] == "Three lines." and r["program"] == "LM Studio"
    assert sent["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert sent["body"]["model"] == "gemma-4-e4b-it"
    assert sent["body"]["ttl"] == S.IDLE                       # it leaves memory like the built-in model


def test_a_program_that_cannot_start_says_why(monkeypatch):
    monkeypatch.setattr(S, "choice", {"program": "Ollama", "model": "llama3.2:latest"})

    def start(program):
        raise RuntimeError("Ollama is not installed on this computer")
    monkeypatch.setattr(S, "start", start)
    assert S.ask("i", "r") == {"error": "Ollama is not installed on this computer"}


def test_the_built_in_model_picked_is_used_even_with_a_server_on(monkeypatch):
    monkeypatch.setattr(S, "choice", {"program": "Sottovoce", "model": None})
    monkeypatch.setattr(S, "who_answers", lambda: pytest.fail("a running server is not asked"))
    monkeypatch.setattr(S, "builtin", lambda: {"program": "Sottovoce", "builtin": True})
    monkeypatch.setattr(S, "_builtin_ask", lambda i, r: {"text": "ok", "program": "Sottovoce"})
    assert S.ask("i", "r")["text"] == "ok"


def test_only_what_sottovoce_started_is_stopped(monkeypatch):
    done = []
    monkeypatch.setattr(S, "lms", lambda: "lms")
    monkeypatch.setattr(S, "_cli", lambda args, timeout=60: done.append(args[1:]))
    monkeypatch.setattr(S, "_lmstudio", {"service_was_up": True, "server": False, "models": set()})
    S.stop_started()
    assert done == []                                         # LM Studio was already on: left alone
    S._lmstudio.update(service_was_up=False, server=True, models={"gemma-4-e4b-it"})
    S.stop_started()
    assert done == [["unload", "gemma-4-e4b-it"], ["server", "stop"], ["daemon", "down"]]


def test_lmstudio_is_asked_how_it_was_before_anything_wakes_it(monkeypatch):
    calls = []

    def run(args, **kw):
        calls.append(args[1:])
        out = '{"status":"not-running"}' if args[1:] == ["daemon", "status", "--json"] else "[]"
        return subprocess.CompletedProcess(args, 0, stdout=out)
    monkeypatch.setattr(S, "lms", lambda: "lms")
    monkeypatch.setattr(S, "_lmstudio", {"service_was_up": None, "server": False, "models": set()})
    monkeypatch.setattr(subprocess, "run", run)
    S.lmstudio_models()
    assert calls == [["daemon", "status", "--json"], ["ls", "--json"]]
    assert S._lmstudio["service_was_up"] is False


def test_the_choice_needs_a_known_program_and_a_model(client, no_llm_choice):
    assert client.post("/api/llm/choice", json={"program": "Other"}).status_code == 400
    assert client.post("/api/llm/choice", json={"program": "Ollama"}).status_code == 400
    assert client.post("/api/llm/choice", json={"program": None}).json()["choice"] == {"program": None, "model": None}


# --- OpenVINO's loops ----------------------------------------------------------------

class Chunk:
    def __init__(self, a, b, text):
        self.start_ts, self.end_ts, self.text = a, b, text


def openvino_with(answers):
    """An OpenVINO engine whose model answers from the list, one per call."""
    import numpy as np

    class Result:
        def __init__(self, chunks):
            self.chunks = chunks

    e = T._OpenVINO.__new__(T._OpenVINO)
    asked = []

    def generate(audio, language, words=False, temperature=0.0):
        asked.append((len(audio) / 16000, temperature))
        return Result(answers.pop(0))
    e._generate = generate
    e._audio = lambda wav: np.zeros(60 * 16000, dtype="float32")
    return e, asked


LOOP = "Il t-rex è " + "un'esplosione di " * 40


def test_a_loop_is_recognised_and_a_sentence_is_not():
    assert T.looped(LOOP)
    assert not T.looped("Depongono le uova e camminano sulle due zampe posteriori.")
    assert T.unloop("Il t-rex è un'esplosione di un'esplosione di un'esplosione di fine") == "Il t-rex è un'esplosione di fine"
    assert T.unloop("no no, dico no") == "no no, dico no"                # twice is speech, not a loop


def test_a_loop_over_silence_is_dropped(tmp_path):
    e, asked = openvino_with([[Chunk(0.0, -1.0, LOOP), Chunk(30.0, 37.0, " Depongono le uova.")]])
    out = e.segments("a.wav", "it", speech=[(31.0, 38.0)])
    assert out == [{"text": " Depongono le uova.", "timestamp": (30.0, 37.0)}]
    assert len(asked) == 1                                               # nothing was done again


def test_a_loop_where_someone_speaks_is_done_again_on_the_spoken_part():
    e, asked = openvino_with([[Chunk(0.0, -1.0, LOOP)], [Chunk(0.0, 4.0, " Ciao a tutti, iniziamo.")]])
    out = e.segments("a.wav", "it", speech=[(25.0, 40.0)])
    assert out == [{"text": " Ciao a tutti, iniziamo.", "timestamp": (24.7, 28.7)}]
    assert asked[1] == (pytest.approx(5.3, abs=0.01), 0.0)               # from 24.7 to the window's end, greedy first


def test_a_loop_that_comes_back_every_time_keeps_one_copy():
    tries = len(T.DECODE["temperature"])
    e, asked = openvino_with([[Chunk(0.0, -1.0, LOOP)]] + [[Chunk(0.0, -1.0, LOOP)] for _ in range(tries)])
    out = e.segments("a.wav", "it", speech=[(0.0, 30.0)])
    assert [t for _, t in asked[1:]] == list(T.DECODE["temperature"])   # warmer each time, as PyTorch does
    assert out[0]["text"] == "Il t-rex è un'esplosione di"


# --- a GPU that may not take it ----------------------------------------------------------

def test_an_old_intel_gpu_is_left_to_the_processor():
    assert T.recent_intel("Intel(R) Arc(TM) 140T GPU (32GB) (iGPU)")
    assert T.recent_intel("Intel(R) Iris(R) Xe Graphics")
    assert not T.recent_intel("Intel(R) UHD Graphics 620")          # the MateBook D that froze
    assert not T.recent_intel("NVIDIA GeForce RTX 5090 Laptop GPU")


def test_a_path_avoided_is_not_taken_by_itself_but_can_be_chosen(paths, monkeypatch):
    paths("intel-gpu", "cpu")
    monkeypatch.setattr(T, "avoid", {"intel-gpu"})
    assert T.path() == "cpu"
    T.choose("intel-gpu")
    assert T.path() == "intel-gpu"


def test_sottovoce_that_died_on_the_intel_gpu_avoids_it_next_time(client, data, paths, monkeypatch):
    paths("intel-gpu", "cpu")
    monkeypatch.setattr(T, "avoid", set())
    server.save_settings(trying="intel-gpu")          # what was written before the transcription that never ended
    server.load_settings()
    assert "intel-gpu" in T.avoid and T.path() == "cpu"
    saved = json.loads((data / "transcripts" / "_settings.json").read_text(encoding="utf-8"))
    assert saved["avoid"] == ["intel-gpu"] and saved.get("trying") is None


def test_an_error_on_the_intel_gpu_is_done_again_on_the_processor(client, paths, monkeypatch):
    paths("intel-gpu", "cpu")
    monkeypatch.setattr(T, "avoid", set())
    monkeypatch.setattr(T, "release", lambda: None)
    tried = []

    def run(original, language, progress, **how):
        tried.append(T.path())
        if T.path() == "intel-gpu":
            raise RuntimeError("CL_OUT_OF_RESOURCES")
        return {"ok": True}
    monkeypatch.setattr(T, "run", run)
    assert server.transcribe_safely("call.wav", "it", None) == {"ok": True}
    assert tried == ["intel-gpu", "cpu"] and "intel-gpu" in T.avoid
