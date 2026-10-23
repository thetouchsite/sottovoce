"""The installer's choice of PyTorch: the wrong build runs on the CPU and says
nothing, so every card generation is pinned here."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "installer"))
import gpu  # noqa: E402


def test_recent_cards_with_a_recent_driver_get_cuda_13():
    for name, cap in [("NVIDIA GeForce RTX 5090 Laptop GPU", "12.0"),
                      ("NVIDIA GeForce RTX 4070", "8.9"), ("NVIDIA GeForce RTX 2060", "7.5"),
                      ("NVIDIA GeForce GTX 1660 Ti", "7.5")]:
        assert gpu.pick("Windows", (name, "581.57", cap))[0] == "cu130", name


def test_older_cards_get_cuda_12_6():
    assert gpu.pick("Linux", ("NVIDIA GeForce GTX 1080", "580.65.06", "6.1"))[0] == "cu126"
    build, why = gpu.pick("Windows", ("NVIDIA GeForce GTX 970", "472.12", None))
    assert build == "cu126" and "528" in why


def test_an_older_driver_falls_back_to_cuda_12_6():
    assert gpu.pick("Windows", ("NVIDIA GeForce RTX 3080", "560.94", "8.6"))[0] == "cu126"


def test_rtx_50_with_an_old_driver_is_told_to_update_it():
    build, why = gpu.pick("Windows", ("NVIDIA GeForce RTX 5070", "572.16", "12.0"))
    assert build == "cu130" and "580" in why and "update" in why


def test_generation_is_found_by_name_when_the_driver_cannot_say():
    assert gpu.pick("Linux", ("NVIDIA GeForce RTX 5080", "575.51", None))[0] == "cu130"
    assert gpu.pick("Linux", ("NVIDIA GeForce GTX 1050", "580.65", None))[0] == "cu126"


def test_drivers_compare_as_numbers():
    assert gpu.version("581.57") > gpu.version("580.9")
    assert gpu.version("1000.1") > gpu.version("999.99")


def test_no_nvidia_gpu_gets_the_cpu_index_and_macos_gets_pypi():
    assert gpu.pick("Windows", None)[0] == "cpu"
    assert gpu.pick("Linux", None)[0] == "cpu"
    assert gpu.pick("Darwin", None)[0] == "pypi"
    assert gpu.pick("Linux", ("NVIDIA Tesla K80", "470.82", "3.7"))[0] == "cpu"


def test_the_oldest_driver_for_cuda_12_6_differs_by_system():
    assert "update" not in gpu.pick("Linux", ("NVIDIA GeForce GTX 1080", "525.60.13", "6.1"))[1]
    assert "update" in gpu.pick("Windows", ("NVIDIA GeForce GTX 1080", "527.56", "6.1"))[1]
