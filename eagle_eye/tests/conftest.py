import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402


@pytest.fixture()
def runs_dir(tmp_path, monkeypatch):
    """Isolate the run store and the fingerprint caches so tests never touch out/runs/ or out/cache/."""
    d = tmp_path / "runs"
    d.mkdir()
    monkeypatch.setattr(config, "RUNS", d)
    import service
    for name in ("RESULTS", "INPUTS", "WORK"):
        monkeypatch.setattr(service, name, tmp_path / "cache" / name.lower())
    return d


@pytest.fixture(autouse=True)
def _no_small_print(monkeypatch):
    """Unit tests feed synthetic tokens on blank synthetic photos; the small-print OCR pass (vision.ocr) would scan
    those blank tiles magnified for nothing. Tests of the guided reading pass their own reader."""
    from vision import ocr
    monkeypatch.setattr(ocr, "read_small_print", lambda *a, **kw: [])
