#!/usr/bin/env bash
# Creates .venv and installs everything, PyTorch first. The Linux and macOS
# twin of Install.bat. Run it once. On Linux with an NVIDIA GPU it's about
# 3.5 GB of downloads; the Whisper model (2.9 GB) comes later, on the first
# transcription.
set -euo pipefail
cd "$(dirname "$0")"

trap 'echo; echo "  Something went wrong above. See the README, \"Linux and macOS\"." >&2' ERR

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "  $PY not found: install Python 3.10 or newer first." >&2
    exit 1
fi
if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "  $("$PY" --version 2>&1) is too old: Python 3.10 or newer is needed." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo
    echo "  Creating the virtual environment..."
    # Debian and Ubuntu ship venv as a separate package, and the error
    # it gives without it doesn't say so.
    if ! "$PY" -m venv .venv; then
        echo "  On Debian or Ubuntu: sudo apt install python3-venv, then run this again." >&2
        rm -rf .venv
        exit 1
    fi
fi
VPY=.venv/bin/python
"$VPY" -m pip install --upgrade pip >/dev/null

# PyTorch before everything else. Installed as a dependency of transformers,
# it comes from PyPI, and on recent cards that build may not see the GPU at
# all: it runs on the CPU and says nothing. README, "The PyTorch trap".
echo
case "$(uname -s)" in
    Linux)
        if command -v nvidia-smi >/dev/null 2>&1; then
            echo "  Installing PyTorch with CUDA..."
            "$VPY" -m pip install torch --index-url https://download.pytorch.org/whl/cu130
        else
            echo "  No nvidia-smi, so no NVIDIA GPU to use: installing the plain PyTorch."
            echo "  It will run on the CPU, about ten times slower."
            "$VPY" -m pip install torch
        fi
        ;;
    Darwin)
        echo "  macOS has no CUDA: installing the plain PyTorch."
        echo "  Whisper will run on the CPU, about ten times slower than on an NVIDIA GPU."
        "$VPY" -m pip install torch
        ;;
    *)
        echo "  Unknown system $(uname -s): installing the plain PyTorch."
        "$VPY" -m pip install torch
        ;;
esac

echo
echo "  Installing the rest..."
"$VPY" -m pip install -r requirements.txt

if [ ! -f glossary.txt ]; then
    cp glossary.example.txt glossary.txt
fi

echo
"$VPY" -c "import torch; ok = torch.cuda.is_available(); print('  PyTorch', torch.__version__, '|', ('GPU: ' + torch.cuda.get_device_name(0)) if ok else 'NO GPU FOUND: it will run on the CPU, about ten times slower')"
echo
echo "  Done. Run ./start.sh"
echo
