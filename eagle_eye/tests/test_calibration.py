"""Confidence calibration (calibration.py) and where findings belong on the assembly line (assembly.py)."""
import assembly
import calibration
import config
import service


def _rec(result, raw, fault, image=0):
    return {"engine": "demo", "image": image, "id": "X", "result": result, "raw": raw, "fault": fault}


def test_laplace_never_claims_certainty_from_few_items():
    maps = calibration.fit([_rec("PASS", 0.55, False), _rec("PASS", 0.55, False)])
    assert maps["PASS"] == [{"lo": 0.5, "hi": 0.6, "n": 2, "k": 2, "p": 0.75}]       # (2 + 1) / (2 + 2), not 100 %


def test_bins_are_monotonic_and_lookup_takes_the_nearest_bin():
    recs = ([_rec("PASS", 0.85, k == 0) for k in range(10)] +          # 9 of 10 right
            [_rec("PASS", 0.92, k < 4) for k in range(10)] +           # 6 of 10 right: lower than the bin below
            [_rec("PASS", 1.0, False) for _ in range(10)])             # all right
    bins = calibration.fit(recs)["PASS"]
    ps = [b["p"] for b in bins]
    assert ps == sorted(ps) and ps[0] == ps[1] == round((10 / 12 + 7 / 12) / 2, 4)    # pooled by PAV
    assert calibration.lookup(bins, 1.0) == ps[-1] == round(11 / 12, 4)
    assert calibration.lookup(bins, 0.3) == ps[0]                     # below every bin: nearest one


def test_fail_and_review_confidence_is_about_the_fault():
    maps = calibration.fit([_rec("FAIL", 0.9, True)] * 8 + [_rec("REVIEW", 0.5, k < 1) for k in range(8)])
    assert maps["FAIL"][0]["p"] == 0.9                                 # (8 + 1) / (8 + 2) right
    assert maps["REVIEW"][0]["p"] == 0.2                               # (1 + 1) / (8 + 2) faulty


def test_reliability_and_ece():
    curve, ece = calibration.reliability([(0.9, True)] * 9 + [(0.9, False)])
    assert curve == [{"lo": 0.9, "hi": 0.95, "n": 10, "stated": 0.9, "observed": 0.9}] and ece == 0
    _curve, ece = calibration.reliability([(0.6, True)] * 10)
    assert ece == 0.4                                                  # says 60 %, is right every time


def test_apply_adds_item_and_photo_confidence():
    cal = {"engines": {"demo": {"maps": calibration.fit(
        [_rec("PASS", 1.0, False)] * 98 + [_rec("FAIL", 0.85, True)] * 8 + [_rec("REVIEW", 0.4, False)] * 3)}}}
    rep = {"results": [{"id": "GA-PS11", "result": "PASS", "conf": 1.0}, {"id": "LBL-PS12", "result": "FAIL", "conf": 0.8},
                       {"id": "LBL-CB41", "result": "REVIEW", "conf": 0.4}, {"id": "MISS-X", "result": "NOT_IN_VIEW", "conf": 1}]}
    calibration.apply(rep, cal)
    conf = {r["id"]: r["confidence"] for r in rep["results"]}
    assert conf == {"GA-PS11": 0.99, "LBL-PS12": 0.9, "LBL-CB41": 0.2, "MISS-X": None}
    s = rep["confidence"]
    assert s["decided"] == 2 and s["review"] == 1 and s["score"] == round((0.99 + 0.9) / 2, 4)
    assert s["expected_errors"] == round(0.01 + 0.1, 2) and s["lowest"][0]["id"] == "LBL-PS12"


def test_committed_calibration_is_honest():
    cal = calibration.load()
    assert cal and cal["schema"] == calibration.SCHEMA
    demo = cal["engines"]["demo"]
    assert demo["images"] >= 50 and demo["heldout"]["ece_cal"] <= demo["heldout"]["ece_raw"]
    for e in cal["engines"].values():
        for bins in e["maps"].values():
            ps = [b["p"] for b in bins]
            assert ps == sorted(ps) and all(p < 1 for p in ps)       # monotonic, never certain
    assert (config.BASE / "web" / "src" / "data" / "calibration.json").read_text() == calibration.CAL_FILE.read_text()


def test_assembly_places_demo_and_real_findings():
    rep = {"ga": {"devices": [{"tag": "CB43", "type": "breaker", "group": "RAIL-1"}, {"tag": "PS12", "type": "psu"}],
                  "rails": [{"name": "RAIL-1", "tags": ["CB41", "CB42", "CB43", "CB44"]}]}}
    assert assembly.dims({"id": "GA-PS12", "check": "GA", "target": "PS12"}, rep) == {
        "check": "GA", "target": "PS12", "family": "Power supply", "area": "Power supply row", "station": "Kitting and mounting"}
    assert assembly.dims({"id": "LBL-CB43", "check": "LABEL", "target": "CB43"}, rep)["area"] == "Breaker rail (RAIL-1)"
    assert assembly.dims({"id": "FER-X3:3", "check": "FERRULE", "target": "X3:3"}, rep)["area"] == "Terminal strip X3"
    groups = [{"id": "front-PS-1", "view": "front", "family": "PS", "order": ["PS13", "PS23"]}]
    real = assembly.dims({"id": "LBL-PS23", "check": "LABEL", "target": "PS23", "view": "front"}, {"engine_kind": "real"}, groups)
    assert (real["family"], real["area"], real["station"]) == ("Power supply", "Front · PS row 1", "Labelling")
    assert assembly.dims({"id": "UNK-SB89", "check": "UNKNOWN_LABEL", "target": "SB89", "view": "rear"},
                         {"engine_kind": "real"}, groups)["area"] == "Rear view"


def test_runs_store_confidence_and_assembly_line_fields(runs_dir):
    meta = service.run_inspection(next(config.SAMPLES.glob("01_*.jpg")), source="sample")
    assert meta["confidence"]["decided"] >= 30 and 0.5 < meta["confidence"]["score"] <= 1
    by_id = {i["id"]: i for i in meta["issues"]}
    assert by_id["GA-PS12"]["family"] == "Power supply" and by_id["GA-PS12"]["station"] == "Kitting and mounting"
    assert by_id["ORD-RAIL-1"]["area"] == "Breaker rail (RAIL-1)" and by_id["FER-X3:3"]["area"] == "Terminal strip X3"
    assert all(0 < i["confidence"] <= 1 for i in meta["issues"])
