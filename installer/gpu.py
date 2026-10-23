"""Which PyTorch to install on this computer: the one that sees its GPU.

    python installer/gpu.py        prints one line: the build, then why

Run by install.ps1 and install.sh before anything else is installed, so it
uses only the standard library. The build is one of:

    cu130   CUDA 13.0: RTX 20 to RTX 50 and GTX 16, with a driver 580 or newer
    cu126   CUDA 12.6: GTX 9 and GTX 10, or a newer card with an older driver
    cpu     no NVIDIA GPU: PyTorch from its CPU index, not PyPI's
    pypi    macOS: PyPI's own build, which has Apple's GPU support in it

The PyPI build is the trap on Windows and Linux: on Linux it is 555 MB of
CUDA 13 plus gigabytes of nvidia-* packages, on Windows it is CPU only, and
neither says so. PyTorch 2.14 has no CUDA 12.8 build, so an RTX 50 card with
a driver older than 580 has no build that sees it: it gets cu130 and is told
to update the driver.
"""
import json
import platform
import shutil
import subprocess
import sys

INDEX = "https://download.pytorch.org/whl/"

# compute_cap is not a query field on older drivers: the generation by name.
BY_NAME = [("RTX 50", 12.0), ("RTX 40", 8.9), ("RTX 30", 8.6), ("RTX 20", 7.5),
           ("GTX 16", 7.5), ("TITAN RTX", 7.5), ("TITAN V", 7.0), ("GTX 10", 6.1),
           ("TITAN X", 5.2), ("GTX 9", 5.2)]


def version(text):
    """ "581.57" -> (581, 57): drivers compare as numbers, not as text."""
    try:
        return tuple(int(p) for p in text.strip().split(".")[:2])
    except ValueError:
        return (0,)


def capability(name, cap):
    try:
        return float(cap)
    except (TypeError, ValueError):
        pass
    for part, cc in BY_NAME:
        if part.lower() in name.lower():
            return cc
    return None


def pick(system, gpu):
    """(build, reason). `gpu` is (name, driver, compute_cap) of the first
    NVIDIA card, or None; compute_cap may be None."""
    if system == "Darwin":
        return "pypi", "macOS: PyTorch with Apple's GPU support"
    if gpu is None:
        return "cpu", "no NVIDIA GPU: it will run on the CPU, about ten times slower"
    name, driver, cap = gpu
    cc = capability(name, cap)
    new_driver = version(driver) >= (580,)
    if cc is not None and cc < 5.0:
        return "cpu", f"{name} is too old for PyTorch: it will run on the CPU"
    if cc is None or cc >= 7.5:
        if new_driver:
            return "cu130", f"{name}, driver {driver}: CUDA 13.0"
        if cc is not None and cc >= 12.0:
            return "cu130", (f"{name} needs driver 580 or newer, this one is {driver}: "
                             "update it from nvidia.com, until then it runs on the CPU")
    oldest = (528, 33) if system == "Windows" else (525, 60)
    if version(driver) < oldest:
        return "cu126", (f"{name} needs driver {oldest[0]}.{oldest[1]} or newer, this one is {driver}: "
                         "update it from nvidia.com, until then it runs on the CPU")
    return "cu126", f"{name}, driver {driver}: CUDA 12.6"


def first_gpu():
    """The first NVIDIA card, from nvidia-smi, or None."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    for fields in ("name,driver_version,compute_cap", "name,driver_version"):
        try:
            r = subprocess.run([smi, f"--query-gpu={fields}", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0 and r.stdout.strip():
            row = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
            return (row[0], row[1], row[2] if len(row) > 2 else None)
    return None


def main():
    build, why = pick(platform.system(), first_gpu())
    if "--json" in sys.argv:
        print(json.dumps({"build": build, "index": "" if build == "pypi" else INDEX + build,
                          "why": why}))
    else:
        print(build, why)


if __name__ == "__main__":
    main()
