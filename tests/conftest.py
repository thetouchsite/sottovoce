"""Shared fixtures. Nothing here needs a GPU, a model or the network.

The tests run on a fresh copy of examples/ in a temporary folder, so they can
correct lines, apply the glossary and add names without touching the repo.
"""
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

NORTHPINE = "2026-10-21_Northpine launch sync"
SUPPLIER = "2026-10-22_Supplier check-in, Brenna Print"


@pytest.fixture
def data(tmp_path):
    """A copy of the fictional calls and their glossary."""
    shutil.copytree(ROOT / "examples" / "transcripts", tmp_path / "transcripts")
    shutil.copy(ROOT / "examples" / "glossary.txt", tmp_path / "glossary.txt")
    return tmp_path


@pytest.fixture
def client(data):
    """The server, without the model, on the copy."""
    from fastapi.testclient import TestClient
    import server
    server.engine_state.update(ready=False, error=None, off=False)
    server.start(data / "transcripts", data / "glossary.txt", model=False)
    return TestClient(server.app)
