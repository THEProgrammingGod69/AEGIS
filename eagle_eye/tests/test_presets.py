"""Wrong-drawing guard and the hosted real-cabinet preset (private Blob storage), without network or OCR."""
import json

import pytest
from fastapi.testclient import TestClient

import blobstore
import config
import server
import service


def _fake_inspect(anchors):
    def inspect(photo_path, ga, wires, enabled=None, on_event=None):
        import numpy as np
        from types import SimpleNamespace
        rep = {"registration": {"anchors": anchors, "targets": 20, "inliers": 0, "outliers": [], "refined": False},
               "ga": {"cabinet": "EE-DEMO-01", "size": [600, 400], "devices": [], "terminals": [], "rails": []},
               "results": [], "counts": {"PASS": 0, "FAIL": 0, "REVIEW": 0, "SKIP": 0}, "H": [[4, 0, 0], [0, 4, 0], [0, 0, 1]],
               "timing": {"total": 0.1}, "warnings": []}
        return rep, SimpleNamespace(photo=np.zeros((40, 60, 3), np.uint8), rect=np.zeros((40, 60, 3), np.uint8))
    return inspect


def test_photo_of_another_cabinet_asks_for_its_drawing(runs_dir, monkeypatch):
    monkeypatch.setattr(service, "inspect", _fake_inspect(0))
    with pytest.raises(service.WrongDrawing, match="drawing set"):
        service.run_inspection(next(config.SAMPLES.glob("02_*.jpg")), source="upload")
    assert not list(runs_dir.iterdir())                       # no all-REVIEW report is stored


def test_uploaded_drawing_is_not_second_guessed_by_the_demo_guard(runs_dir, monkeypatch):
    monkeypatch.setattr(service, "inspect", _fake_inspect(0))
    monkeypatch.setattr(service, "engine_for", lambda ga, engine="auto", prev=None: "legacy")
    m = service.run_inspection(next(config.SAMPLES.glob("02_*.jpg")), ga=config.DEMO_GA, input_names={"ga": "mine.pdf"},
                               reports=False)
    assert m["id"]                                            # a custom drawing: the user's choice, the report stands


def test_blob_sync_mirrors_the_private_preset(tmp_path, monkeypatch):
    store = {"presets/emerson/drawing.pdf": b"%PDF-1.4 x", "presets/emerson/a.jpg": b"\xff\xd8jpg"}
    calls = []

    def fake_call(method, url, data=None, headers=None, timeout=60, api=True):
        calls.append((method, url, api))
        if "prefix=" in url:
            return json.dumps({"blobs": [{"pathname": k, "size": len(v), "url": "https://s.private.blob/" + k}
                                         for k, v in store.items()], "hasMore": False}).encode()
        return store[url.split("https://s.private.blob/")[1]]
    monkeypatch.setattr(blobstore, "_call", fake_call)
    d = blobstore.sync("presets/emerson/", tmp_path / "emerson", force=True)
    assert sorted(p.name for p in d.iterdir()) == ["a.jpg", "drawing.pdf"]
    assert all(api is False for m, u, api in calls if "private.blob" in u)    # downloads: bearer only, no API header
    n = len(calls)
    blobstore.sync("presets/emerson/", tmp_path / "emerson")                    # throttled: no new listing
    assert len(calls) == n


def test_admin_upload_is_hidden_unless_configured(monkeypatch):
    c = TestClient(server.app)
    monkeypatch.setattr(server, "ADMIN_TOKEN", "")
    r = c.post("/api/v2/admin/preset", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 404
    monkeypatch.setattr(server, "ADMIN_TOKEN", "a" * 32)
    monkeypatch.setattr(server, "PRESET_BLOB", "presets/emerson/")
    monkeypatch.setenv("BLOB_READ_WRITE_TOKEN", "vercel_blob_rw_store_secret")
    r = c.post("/api/v2/admin/preset", files={"file": ("x.pdf", b"%PDF", "application/pdf")},
               headers={"x-admin-token": "wrong" * 7})
    assert r.status_code == 403
