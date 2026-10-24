"""Regression checks for the real-photo/demo mismatch, registration and cabinet approval boundaries."""
import io
import json
import numpy as np
import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

import config
import inspector
import pipeline
import server
import service


def _jpeg():
    out = io.BytesIO()
    Image.new("RGB", (80, 60), "gray").save(out, format="JPEG")
    return out.getvalue()


def _counts(**updates):
    return dict(PASS=0, FAIL=0, REVIEW=0, SKIP=0, NOT_IN_VIEW=0) | updates


@pytest.mark.parametrize("path", ["/api/inspect", "/api/v2/inspect"])
def test_upload_requires_an_intentional_drawing_before_work_starts(path, monkeypatch):
    monkeypatch.setattr(server.JOBS, "submit", lambda *a, **k: pytest.fail("inspection must not be scheduled"))
    response = TestClient(server.app).post(path, files={"photo": ("emerson.jpg", _jpeg(), "image/jpeg")})
    assert response.status_code == 400
    assert "matching GA drawing" in response.json()["detail"]


def test_old_accidental_demo_run_does_not_authorize_another_demo_upload():
    with pytest.raises(inspector.InspectionError, match="matching GA drawing"):
        service.validate_request(prev={"source": "upload", "engine_kind": "legacy"})
    service.validate_request(engine="legacy")  # deliberate synthetic mode
    service.validate_request(prev={"source": "sample", "engine_kind": "legacy"})


@pytest.mark.parametrize("path", ["/api/inspect", "/api/v2/inspect"])
def test_corrupt_image_and_pdf_are_actionable_before_streaming(path):
    client = TestClient(server.app)
    response = client.post(path, files={"photo": ("photo.jpg", b"not an image", "image/jpeg")})
    assert response.status_code == 400 and "photo" in response.json()["detail"]
    response = client.post(path, files={"ga": ("drawing.pdf", b"not a pdf", "application/pdf")}, data={"sample": "01"})
    assert response.status_code == 400 and "GA drawing PDF" in response.json()["detail"]


def test_empty_input_upload_is_rejected():
    response = TestClient(server.app).post("/api/v2/inputs", data={"kind": "ga"},
                                          files={"file": ("drawing.pdf", b"", "application/pdf")})
    assert response.status_code == 400


def test_scanned_drawing_explains_required_input(tmp_path):
    import pymupdf
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_image(page.rect, stream=_jpeg())
        doc.save(path)
    with pytest.raises(inspector.InspectionError, match="selectable text"):
        service.validate_input(path, "ga")


def test_new_drawing_overrides_old_demo_engine(monkeypatch):
    monkeypatch.setattr(pipeline, "is_real_drawing", lambda p: True)
    assert service.engine_for("emerson.pdf", prev="legacy") == "real"
    assert service.engine_for(None, prev="real") == "real"
    assert service.engine_for("emerson.pdf", engine="legacy", prev="real") == "legacy"


def test_partial_recheck_reuses_previous_ga_but_replacement_drawing_does_not_inherit_wires(tmp_path, monkeypatch):
    ga = tmp_path / "original.pdf"
    ga.write_bytes(b"original")
    monkeypatch.setattr(service, "input_path", lambda *args: ga)
    previous = {"id": "20261024-120000-abcd", "inputs": {
        "ga": {"demo": False, "name": "original.pdf"}, "wires": {"demo": True}}}
    resolved = service.inherited_inputs(previous, wires="new.xlsx")
    assert resolved[:3] == (ga, "new.xlsx", None)
    assert resolved[3]["ga"] == "original.pdf"
    assert service.inherited_inputs(previous, ga="different.pdf")[:3] == ("different.pdf", None, None)


@pytest.mark.parametrize("counts, n", [(_counts(), 0), (_counts(SKIP=4), 4),
                                       (_counts(PASS=2, NOT_IN_VIEW=5), 7)])
def test_empty_skipped_or_partial_inspections_never_approve_cabinet(counts, n):
    assert service.verdict(counts, n)["label"] == "REVIEW"


def test_partial_check_selection_and_incomplete_real_coverage_block_approval():
    assert service.verdict(_counts(PASS=1), 1, rep={"enabled": ["LABEL"]})["label"] == "REVIEW"
    report = {"engine_kind": "real", "enabled": pipeline.real_enabled(None),
              "coverage": {"verified": 2, "total": 10, "approval_allowed": False, "complete": False}}
    assert service.verdict(_counts(PASS=4), 4, rep=report)["label"] == "REVIEW"
    report["coverage"].update(verified=10, approval_allowed=True, complete=True)
    assert service.verdict(_counts(PASS=20), 20, rep=report)["label"] == "PASS"


def test_failed_geometric_fit_skips_checks_and_reports_one_root_issue(monkeypatch):
    ga = {"cabinet": "TEST", "size": [100, 100], "devices": [
        {"tag": "PS11", "box": [10, 10, 20, 20], "label_box": [12, 12, 10, 5]}], "terminals": [], "rails": []}
    reg = {"anchors": 12, "targets": 20, "inliers": 0, "outliers": [], "refined": False}
    monkeypatch.setattr(inspector, "load_photo", lambda p: np.zeros((100, 100, 3), dtype=np.uint8))
    monkeypatch.setattr(inspector, "parse_ga", lambda p: ga)
    monkeypatch.setattr(inspector, "read_wire_list", lambda p: [])
    monkeypatch.setattr(inspector, "register", lambda *a: (np.zeros((400, 400, 3), dtype=np.uint8), np.eye(3), reg.copy()))
    monkeypatch.setattr(inspector, "Backplate", lambda *a: pytest.fail("must not evaluate an unregistered region"))
    report, _ = inspector.inspect("photo.jpg", "drawing.pdf", "wires.xlsx", enabled=["GA", "LABEL"])
    assert report["registration"]["valid"] is False
    assert report["counts"] == {"PASS": 0, "FAIL": 0, "REVIEW": 1, "SKIP": 2}
    assert [r["id"] for r in report["results"] if r["result"] == "REVIEW"] == ["REG-DRAWING"]
    assert all(r.get("root_cause") == "REG-DRAWING" for r in report["results"] if r["result"] == "SKIP")


def test_selected_preset_supplies_drawing_without_replacing_uploaded_photo(monkeypatch):
    captured = {}
    monkeypatch.setattr(server, "_preset", lambda *a: {"ga": config.DEMO_GA, "photo": config.DEMO_PHOTO, "title": "Real"})

    def run(photo, ga, *a, **kwargs):
        captured.update(photo_bytes=photo.read_bytes(), ga=ga, **kwargs)
        return {"id": "20261024-120000-abcd"}

    def stream(work, cleanup=None, **kwargs):
        try:
            return JSONResponse(list(work(lambda e: None, [])))
        finally:
            if cleanup:
                cleanup()

    monkeypatch.setattr(service, "run_inspection", run)
    monkeypatch.setattr(server, "_stream", stream)
    response = TestClient(server.app).post("/api/v2/inspect", data={"preset": "emerson", "engine": "real"},
                                          files={"photo": ("mine.jpg", _jpeg(), "image/jpeg")})
    assert response.status_code == 200
    assert captured["photo_bytes"] == _jpeg() and captured["photo_name"] == "mine.jpg"
    assert captured["ga"] == config.DEMO_GA and captured["source"] == "upload"


def test_preset_with_uploaded_photo_fingerprint_requests_that_photo(monkeypatch):
    monkeypatch.setattr(server, "_preset", lambda *a: {"ga": config.DEMO_GA, "photo": config.DEMO_PHOTO, "title": "Real"})
    monkeypatch.setattr(service, "has_result", lambda *a, **kw: False)
    response = TestClient(server.app).post("/api/v2/inspect", data={"preset": "emerson", "engine": "real",
                                           "photo_sha": "a" * 64, "photo_name": "my-upload.jpg"})
    assert response.status_code == 409 and response.json()["need"] == ["photo"]


def test_historical_weak_registration_cannot_return_verified_passes(runs_dir):
    rid = "20261024-120000-abcd"
    folder = runs_dir / rid
    folder.mkdir()
    ga = {"cabinet": "TEST", "size": [100, 100], "devices": [], "terminals": [], "rails": []}
    warnings = [{"code": "weak_registration", "message": "no matching labels"}]
    service.write_json(folder / "report.json", {"ga": ga, "results": [{"id": "GA-X", "result": "PASS"}],
        "counts": _counts(PASS=1), "warnings": warnings, "registration": {"anchors": 0}, "enabled": ["GA"]})
    service.write_json(folder / "meta.json", {"id": rid, "engine_kind": "legacy", "warnings": warnings})
    meta, report = service.get_meta(rid), service.get_report(rid)
    assert meta["verdict"]["label"] == "REVIEW" and meta["counts"]["PASS"] == 0
    assert report["results"][0]["id"] == "REG-DRAWING" and meta["historical_guard"]


@pytest.mark.parametrize("registration", [{"localised": False}, {"valid": False},
                                            {"valid": True, "localised": False}])
def test_historical_real_unplaced_report_loses_conclusions_and_approval(runs_dir, registration):
    rid = "20261024-120000-bbcd"
    folder = runs_dir / rid
    folder.mkdir()
    rows = [{"id": f"LBL-{i}", "check": "LABEL", "target": str(i), "result": result,
             "found": "old reading", "box": [0, 0, 5, 5], "evidence": ["old evidence"],
             "marker": i + 1, "recheck": "CLOSED", "verified_by": ["OCR", "geometry"]}
            for i, result in enumerate(("PASS", "FAIL", "REVIEW", "NOT_IN_VIEW"))]
    original = {"engine_kind": "real", "ga": {"cabinet": "REAL"}, "results": rows,
        "counts": _counts(PASS=1, FAIL=1, REVIEW=1, NOT_IN_VIEW=1), "registration": registration,
        "photo_size": [800, 600], "recheck": {"CLOSED": 1}, "warnings": [],
        "coverage": {"verified": 4, "total": 4, "approval_allowed": True, "complete": True}}
    service.write_json(folder / "report.json", original)
    service.write_json(folder / "meta.json", {"id": rid, "engine_kind": "real", "warnings": []})
    meta, report = service.get_meta(rid), service.get_report(rid)
    assert meta["verdict"]["label"] == "REVIEW" and meta["counts"] == report["counts"]
    assert report["counts"] == _counts(REVIEW=1, SKIP=3, NOT_IN_VIEW=1)
    assert meta["registration"]["valid"] is False and meta["registration"]["localised"] is False
    assert meta["coverage"]["verified"] == 0 and not meta["coverage"]["approval_allowed"]
    assert not meta["recheck"] and "recheck" not in report
    assert [r["id"] for r in meta["issues"]] == ["REG-DRAWING"]
    assert all(not r.get("verified_by") for r in report["results"] if r["result"] == "SKIP")
    assert service.read_json(folder / "report.json") == original  # preserve the original audit record


def test_historical_metadata_also_blocks_invalid_real_report(runs_dir):
    rid = "20261024-120000-bbcd"
    folder = runs_dir / rid
    folder.mkdir()
    service.write_json(folder / "report.json", {"engine_kind": "real", "ga": {"cabinet": "REAL"},
        "results": [], "registration": {}, "counts": _counts(), "warnings": []})
    service.write_json(folder / "meta.json", {"id": rid, "engine_kind": "real", "registration": {"valid": False}})
    assert service.get_meta(rid)["counts"]["REVIEW"] == 1
    assert service.get_report(rid)["registration"]["valid"] is False


def test_valid_real_low_anchor_fit_is_not_subject_to_legacy_threshold(runs_dir):
    rid = "20261024-120000-bbcd"
    folder = runs_dir / rid
    folder.mkdir()
    rep = {"engine_kind": "real", "ga": {"cabinet": "REAL"}, "results": [{"id": "LBL-X", "result": "PASS",
               "check": "LABEL", "target": "X", "view": "front", "verified_by": ["OCR", "geometry"]}],
           "registration": {"anchors": 3, "inliers": 3, "valid": True, "localised": True, "views": ["front"]},
           "coverage": {"total": 1, "verified": 1, "complete": True, "approval_allowed": True}, "warnings": []}
    service.write_json(folder / "report.json", rep)
    service.write_json(folder / "meta.json", {"id": rid, "engine_kind": "real", "registration": {"valid": True}})
    assert service.get_report(rid) == rep
    assert not service.get_meta(rid).get("historical_guard")


@pytest.mark.parametrize("path", ["/api/inspect", "/api/v2/inspect"])
@pytest.mark.parametrize("checks", ["", " , ", "BOGUS", "GA,BOGUS"])
def test_empty_and_unknown_check_selection_returns_400_before_inspection(path, checks, monkeypatch):
    monkeypatch.setattr(server.JOBS, "submit", lambda *a, **k: pytest.fail("must not schedule an invalid selection"))
    response = TestClient(server.app).post(path, data={"sample": "01", "checks": checks})
    assert response.status_code == 400 and "check" in response.json()["detail"].lower()


def test_omitted_checks_keep_defaults_and_direct_empty_lists_are_rejected():
    assert server._enabled(None) is None
    assert server._enabled(" ga, LABEL,ga ") == ["GA", "LABEL"]
    assert service._enabled_for("legacy", None) == inspector.ORDER
    for enabled in ([], ["BOGUS"], ["GA", "BOGUS"]):
        with pytest.raises(inspector.InspectionError, match="check"):
            service.validate_request(engine="legacy", enabled=enabled)


@pytest.mark.parametrize("path", ["/api/inspect", "/api/v2/inspect"])
def test_real_only_check_is_rejected_in_explicit_demo_mode(path):
    response = TestClient(server.app).post(path, data={"sample": "01", "engine": "legacy", "checks": "MISSING"})
    assert response.status_code == 400 and "MISSING" in response.json()["detail"]


def test_replacing_demo_ga_routes_real_engine_and_never_closes_old_issues(runs_dir, tmp_path, monkeypatch):
    new_ga = tmp_path / "emerson.pdf"
    new_ga.write_bytes(config.DEMO_GA.read_bytes())
    previous = {"id": "20261024-120000-abcd", "source": "upload", "engine_kind": "legacy", "version": 1,
        "inputs": {"ga": {"demo": True, "name": config.DEMO_GA.name}}, "cabinet": "EE-DEMO-01"}
    old_report = {"ga": {"cabinet": "EE-DEMO-01"}, "registration": {"valid": True}, "results": [
        {"id": "LBL-PS11", "check": "LABEL", "target": "PS11", "result": "FAIL", "found": "wrong", "marker": 1}]}
    selected = []

    def engine(kind, photo, inputs, enabled, emit, work, d, rec):
        selected.append(kind)
        art = work / "art"
        art.mkdir(parents=True)
        Image.open(photo).save(art / "preview.jpg")
        report = {"engine_kind": "real", "ga": {"cabinet": "EMERSON", "size": [80, 60], "devices": [], "terminals": [], "rails": []},
            "results": [{"id": "LBL-PS11", "check": "LABEL", "target": "PS11", "expected": "PS11", "found": "PS11",
                         "result": "PASS", "box": [0, 0, 5, 5], "evidence": [], "conf": 1.0}],
            "registration": {"valid": True, "localised": True, "anchors": 4, "inliers": 4, "outliers": [],
                             "targets": 4, "refined": False}, "counts": _counts(PASS=1), "enabled": enabled,
            "warnings": [], "H": np.diag([4, 4, 1]).tolist(), "timing": {"total": 0.01},
            "coverage": {"verified": 1, "total": 1, "approval_allowed": True}}
        return report, art, 1.0

    monkeypatch.setattr(pipeline, "is_real_drawing", lambda p: True)
    monkeypatch.setattr(service, "_engine", engine)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(_jpeg())
    meta = service.run_inspection(photo, ga=new_ga, parent_data=(previous, old_report), reports=False)
    assert selected == ["real"] and meta["engine_kind"] == "real"
    assert meta["recheck"] is None and any(w["code"] == "drawing_changed" for w in meta["warnings"])
    assert not any(r.get("recheck") == "CLOSED" for r in service.get_report(meta["id"])["results"])


def _stored_real_report(runs_dir, bad_row=None, coverage=True):
    rid = "20261024-130000-bbcd"
    folder = runs_dir / rid
    folder.mkdir()
    good = {"id": "LBL-PS11", "check": "LABEL", "target": "PS11", "result": "PASS", "found": "PS11",
            "view": "front", "verified_by": ["OCR", "geometry"], "evidence": [], "box": [0, 0, 10, 5]}
    rows = [good]
    if bad_row:
        rows.append(dict(good, id="LBL-PS12", target="PS12", found="PS12", **bad_row))
    rep = {"engine_kind": "real", "ga": {"cabinet": "REAL"}, "photo_size": [80, 60], "results": rows,
           "enabled": pipeline.real_enabled(None), "registration": {"valid": True, "localised": True, "views": ["front"]},
           "counts": _counts(PASS=len(rows)), "warnings": []}
    if coverage:
        rep["coverage"] = {"total": len(rows), "verified": len(rows), "complete": True, "approval_allowed": True}
    meta = {"id": rid, "cabinet": "REAL", "engine_kind": "real", "photo": "preview.jpg", "warnings": [],
            "counts": rep["counts"], "verdict": {"label": "PASS"}}
    service.write_json(folder / "report.json", rep)
    service.write_json(folder / "meta.json", meta)
    (folder / "preview.jpg").write_bytes(_jpeg())
    return rid, folder, rep


@pytest.mark.parametrize("bad_row", [
    {"view": "back"}, {"rule": "LABEL.read_view_not_placed"}, {"verified_by": ["Claude"]},
    {"verified_by": ["OCR"]}, {"result": "FAIL", "candidate": "CANDIDATE_FAULT", "strength": "weak", "verified_by": ["Claude"]},
])
def test_historical_real_row_requires_its_own_local_evidence(runs_dir, bad_row):
    rid, folder, original = _stored_real_report(runs_dir, bad_row)
    report, meta = service.get_report(rid), service.get_meta(rid)
    assert [r["result"] for r in report["results"]] == ["PASS", "REVIEW"]
    assert report["coverage"]["verified"] == 1 and not report["coverage"]["approval_allowed"]
    assert meta["verdict"]["label"] == "REVIEW" and meta["historical_guard"]
    assert service.read_json(folder / "report.json") == original


def test_historical_real_missing_coverage_never_reuses_old_pass_verdict(runs_dir):
    rid, _, _ = _stored_real_report(runs_dir, coverage=False)
    report, meta = service.get_report(rid), service.get_meta(rid)
    assert report["results"][0]["result"] == "PASS"  # this individual label has local proof
    assert meta["verdict"]["label"] == "REVIEW" and not report["coverage"]["approval_allowed"]


def test_archived_unsafe_exports_blocked_but_preview_and_guarded_json_available(runs_dir):
    rid, folder, original = _stored_real_report(runs_dir, {"verified_by": ["Claude"]})
    client = TestClient(server.app)
    for name in ("pdf", "checklist", "marked", "rectified", "overlay"):
        (folder / service.FILES[name]).write_bytes(b"archived unsafe export")
        response = client.get(f"/api/runs/{rid}/files/{name}")
        assert response.status_code == 422 and "new inspection" in response.json()["detail"]
    response = client.get(f"/api/runs/{rid}/files/json")
    assert response.status_code == 200 and response.json()["results"][1]["result"] == "REVIEW"
    assert service.read_json(folder / "report.json") == original
    assert service.artefact(rid, "json").name == "report.safe.json"
    assert client.get(f"/api/runs/{rid}/files/preview").status_code == 200
    with pytest.raises(inspector.InspectionError, match="new inspection"):
        service.build_reports(rid)


def test_current_guarded_report_still_allows_its_safely_generated_exports(runs_dir):
    rid, folder, _ = _stored_real_report(runs_dir, {"verified_by": ["Claude"]})
    safe = service.get_report(rid)
    safe["safety_schema"] = service.SAFETY_SCHEMA
    service.write_json(folder / "report.json", safe)
    (folder / "EAGLE_EYE_QC_Report.pdf").write_bytes(b"safely regenerated report")
    assert not service.get_meta(rid)["historical_guard"]
    assert service.artefact(rid, "pdf").read_bytes() == b"safely regenerated report"


def test_review_verdict_covers_manual_and_unsupported_requirements():
    verdict = service.verdict(_counts(REVIEW=2), 2)
    assert "2 unresolved checks" in verdict["headline"]
    assert "manual check" in verdict["detail"] and "could not be read" not in verdict["detail"]


def test_preset_recheck_recovers_drawing_after_input_cache_is_lost(runs_dir, monkeypatch):
    captured = {}
    parent = {"meta": {"id": "20261024-120000-abcd", "source": "preset", "engine_kind": "real", "version": 1,
                        "inputs": {"ga": {"demo": False, "sha256": service.sha256_file(config.DEMO_GA),
                                           "ext": ".pdf", "name": "drawing.pdf"}}},
              "report": {"ga": {"cabinet": "REAL"}, "results": []}}
    monkeypatch.setattr(server, "_preset", lambda *a: {"ga": config.DEMO_GA, "photo": config.DEMO_PHOTO, "title": "Real"})

    def run(photo, ga, *a, **kwargs):
        captured.update(ga=ga, **kwargs)
        return {"id": "20261024-130000-abcd"}

    def stream(work, cleanup=None, **kwargs):
        try:
            return JSONResponse(list(work(lambda e: None, [])))
        finally:
            if cleanup:
                cleanup()

    monkeypatch.setattr(service, "run_inspection", run)
    monkeypatch.setattr(server, "_stream", stream)
    response = TestClient(server.app).post("/api/v2/inspect", data={"preset": "emerson", "engine": "real"},
        files={"photo": ("new-view.jpg", _jpeg(), "image/jpeg"),
               "parent": ("parent.json", json.dumps(parent), "application/json")})
    assert response.status_code == 200
    assert captured["ga"] == config.DEMO_GA and captured["parent_data"][0]["id"] == parent["meta"]["id"]
