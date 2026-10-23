"""Transcription on Intel hardware with OpenVINO: the integrated Arc GPU,
the NPU, the processor. The same clips and the same scoring as research/cpu.py.

    python research/intel.py                         the first 10 FLEURS Italian clips
    python research/intel.py --configs gpu-turbo     one of them

    gpu          Whisper large-v3, int8, on the Intel GPU
    gpu-turbo    large-v3-turbo, int8, on the Intel GPU
    npu-turbo    large-v3-turbo, int8, on the NPU
    cpu          large-v3, int8, on the processor, through OpenVINO

The models are the OpenVINO organisation's conversions on Hugging Face,
downloaded once. Needs (apart from the engine, no PyTorch):
    pip install openvino-genai huggingface_hub transformers jiwer soundfile
"""
import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import soundfile as sf                                    # noqa: E402

import wer as W                                           # noqa: E402

CONFIGS = {
    "gpu": ("OpenVINO/whisper-large-v3-int8-ov", "GPU.0"),
    "gpu-turbo": ("OpenVINO/whisper-large-v3-turbo-int8-ov", "GPU.0"),
    "npu-turbo": ("OpenVINO/whisper-large-v3-turbo-int8-ov", "NPU"),
    "cpu": ("OpenVINO/whisper-large-v3-int8-ov", "CPU"),
    # Not Intel: OpenVINO reaches an NVIDIA card too, through OpenCL. For the
    # comparison with PyTorch and CUDA on the same card.
    "nvidia": ("OpenVINO/whisper-large-v3-int8-ov", "GPU.1"),
}


def pipeline(repo, device):
    import openvino_genai as og
    from huggingface_hub import snapshot_download
    return og.WhisperPipeline(snapshot_download(repo), device)


def transcribe(pipe, wav):
    audio, rate = sf.read(str(wav), dtype="float32")
    assert rate == 16000, rate
    config = pipe.get_generation_config()
    config.language = "<|it|>"
    config.task = "transcribe"
    config.return_timestamps = False
    return pipe.generate(audio.tolist(), config).texts[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--configs", default=",".join(CONFIGS))
    args = ap.parse_args()
    import openvino as ov
    core = ov.Core()
    print(f"\n  OpenVINO {ov.__version__}: " + ", ".join(f"{d} = {core.get_property(d, 'FULL_DEVICE_NAME')}"
                                                     for d in core.available_devices))
    items = W.fleurs(args.limit)
    audio = sum(sf.info(str(f)).duration for f, _ in items)
    norm = W.normalizer("it")
    print(f"  FLEURS it_it test, first {len(items)} clips: {audio:.0f} s of audio\n")
    print("  config      WER     seconds   x real time")
    results = {}
    for c in [c.strip() for c in args.configs.split(",") if c.strip()]:
        repo, device = CONFIGS[c]
        try:
            pipe = pipeline(repo, device)
            transcribe(pipe, items[0][0])                 # compiles for the device, off the clock
        except Exception as e:
            print(f"  {c:10}  does not run here: {type(e).__name__}: {str(e)[:120]}", flush=True)
            continue
        t0 = time.time()
        hyps = [transcribe(pipe, f) for f, _ in items]
        secs = time.time() - t0
        s = W.score([r for _, r in items], hyps, norm)
        results[c] = {**s, "seconds": round(secs, 1), "audio_seconds": round(audio, 1), "device": device, "model": repo}
        print(f"  {c:10}  {s['wer']:6.1%}  {secs:8.0f}   {audio / secs:10.2f}", flush=True)
        del pipe
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "intel.json").write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
