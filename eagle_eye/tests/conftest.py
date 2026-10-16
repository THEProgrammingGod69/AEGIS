import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402


@pytest.fixture()
def runs_dir(tmp_path, monkeypatch):
    """Isolate the run store so tests never touch out/runs/."""
    d = tmp_path / "runs"
    d.mkdir()
    monkeypatch.setattr(config, "RUNS", d)
    return d
