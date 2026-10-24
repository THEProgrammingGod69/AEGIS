"""Real-cabinet engine, Phases 3-7: registration, checks, consensus and the pipeline report.

The unit tests run on a small synthetic cabinet model and synthetic OCR tokens (no photo, no OCR, no network), so they
run everywhere. The end-to-end test uses Emerson's drawing set and photos and skips when data/emerson/ is missing.
"""
import json
import math
from pathlib import Path

import numpy as np
import pytest

import consensus
from checks import CHECKS, ORDER, Context, run_checks
from vision.decode import Vocab, classify_tokens
from vision.register import layout_consistent, project, register, unproject

REAL = Path(__file__).resolve().parents[2] / "data" / "emerson"
needs_real = pytest.mark.skipif(not (REAL / "Sanitized_Cabinet_Drawing.pdf").exists(),
                                reason="Emerson drawing set not available (data/emerson/)")

S, T = 10.0, (100.0, 50.0)          # synthetic photo = S * drawing + T
TAGS = {"PS11": (100, 100), "PS12": (140, 100), "PS13": (180, 100), "DS11": (100, 150), "DS12": (140, 150),
        "TS1": (180, 150)}


def _kb():
    tags = [{"tag": t, "family": t[:2], "center": list(c), "label_expected": True, "device_bbox": None, "label": None,
             "instances": [{"bbox": [c[0] - 2, c[1] - 0.7, c[0] + 2, c[1] + 0.7], "center": list(c), "rot": 0,
                            "size_pt": 1.6, "kind": "nameplate", "stray": False}]} for t, c in TAGS.items()]
    return {"schema": "eagle-eye-kb/1", "kb_version": "1.0", "pdf_sha256": "0" * 64, "cabinet": "TEST-01",
            "views": {"front": {"page": 1, "title": "FRONT INSIDE VIEW", "bbox": [80, 80, 200, 170],
                                "region": [80, 80, 200, 170], "tags": tags, "callouts": []}},
            "vocabulary": sorted(TAGS) + ["XP11"], "groups": [
                {"id": "front-PS-1", "view": "front", "family": "PS", "axis": "x", "order": ["PS11", "PS12", "PS13"],
                 "pitch_pt": 40.0}],
            "device_links": [["DS11", "PS11"], ["DS12", "PS13"], ["PS12", "TS1"]],
            "connections": [{"from_device": "PS11", "to_device": "DS11"}],
            "stats": {}}


def _photo():
    return {"rgb": np.zeros((1800, 2400, 3), np.uint8), "sha": "synthetic", "size": [2400, 1800], "ignore": [],
            "quality": {"score": 1.0, "issues": []}, "name": "synthetic.jpg"}


def _tok(text, xy, passes=2, conf=0.99, w=40, h=14):
    x, y = xy
    return {"text": text, "norm": text.upper(), "box": [x - w, y - h, x + w, y + h], "conf": conf, "rot": 0,
            "passes": passes}


def _at(tag, dx=0.0, dy=0.0):
    c = TAGS[tag]
    return (S * c[0] + T[0] + dx, S * c[1] + T[1] + dy)


def _run(tokens, zoom=None, agent_decisions=None, agent_on=False, strong_alone=False):
    kb, photo = _kb(), _photo()
    reg = register(tokens, kb, photo)
    ctx = Context(kb, None, photo, tokens, reg, ocr_region=lambda box, rot, sc: (zoom or {}).get("tokens", []),
                  workers=1)
    findings, _ = run_checks(ctx)
    items = consensus.decide(findings, agent_decisions or {}, agent_on, strong_alone=strong_alone)
    return reg, {f["id"]: f for f in findings}, {r["id"]: r for r in items}


def test_registration_recovers_the_transform():
    toks = [_tok(t, _at(t, dx=3 * math.sin(i), dy=2 * math.cos(i))) for i, t in enumerate(TAGS)]
    reg = register(toks, _kb(), _photo())
    assert reg["localised"] and [f["view"] for f in reg["fits"]] == ["front"]
    f = reg["fits"][0]
    assert abs(f["scale_px_per_pt"] - S) < 0.2 and len(f["inliers"]) == len(TAGS) and not f["outliers"]
    assert np.allclose(project(f, [140, 100]), _at("PS12"), atol=5)
    assert np.allclose(unproject(f, _at("DS12")), [140, 150], atol=0.5)
    assert set(reg["in_view"]) == set(TAGS) and not reg["not_in_view"]


def test_clean_cabinet_passes_everything():
    reg, fs, items = _run([_tok(t, _at(t)) for t in TAGS])
    assert all(r["result"] == "PASS" for r in items.values()), [(k, r["result"]) for k, r in items.items()]
    assert {f"MISS-{t}" for t in TAGS} | {f"LBL-{t}" for t in TAGS} | {"ORD-front-PS-1"} <= set(items)


def test_swapped_labels_are_named_and_need_two_signals():
    toks = [_tok("PS12" if t == "PS11" else "PS11" if t == "PS12" else t, _at(t)) for t in TAGS]
    reg, fs, items = _run(toks)
    o = fs["ORD-front-PS-1"]
    assert o["status"] == "CANDIDATE_FAULT" and o["strength"] == "strong" and o["swaps"] == [("PS11", "PS12")]
    assert fs["LBL-PS11"]["status"] == "SKIP" and fs["LBL-PS11"]["root_cause"] == "ORD-front-PS-1"
    assert items["ORD-front-PS-1"]["result"] == "REVIEW"                 # agent off: one signal is not enough
    _, _, on_prem = _run(toks, strong_alone=True)
    assert on_prem["ORD-front-PS-1"]["result"] == "FAIL"                  # EAGLE_FAIL_WITHOUT_AGENT, strong evidence
    dec = {"ORD-front-PS-1": {"verdict": "CONFIRMED_FAULT", "confidence": 0.9, "reason": "swapped", "model": "m"}}
    _, _, agreed = _run(toks, agent_decisions=dec, agent_on=True)
    assert agreed["ORD-front-PS-1"]["result"] == "FAIL" and "Claude" in agreed["ORD-front-PS-1"]["verified_by"]


def test_missing_part_is_one_root_cause_and_the_agent_can_clear_it():
    toks = [_tok(t, _at(t)) for t in TAGS if t != "PS13"]
    reg, fs, items = _run(toks)
    assert fs["MISS-PS13"]["status"] == "CANDIDATE_FAULT"
    assert fs["LBL-PS13"]["status"] == "SKIP" and fs["LBL-PS13"]["root_cause"] == "MISS-PS13"
    assert items["MISS-PS13"]["result"] == "REVIEW" and items["MISS-PS13"]["hint"]
    ok = {"MISS-PS13": {"verdict": "CONFIRMED_OK", "confidence": 0.9, "reason": "label PS13 is there", "model": "m"}}
    _, _, cleared = _run(toks, agent_decisions=ok, agent_on=True)
    assert cleared["MISS-PS13"]["result"] == "PASS" and cleared["LBL-PS13"]["result"] == "PASS"
    weak = {"MISS-PS13": {"verdict": "CONFIRMED_FAULT", "confidence": 0.6, "reason": "empty rail", "model": "m"}}
    _, fs2, unsure = _run(toks, agent_decisions=weak, agent_on=True)
    expect = "FAIL" if fs2["MISS-PS13"]["strength"] == "strong" else "REVIEW"
    assert unsure["MISS-PS13"]["result"] == expect


def test_without_agent_positive_reads_fail_but_absence_never_does():
    wrong = [_tok("TS2" if t == "TS1" else t, _at(t)) for t in TAGS]
    _, fs, items = _run(wrong, strong_alone=True)
    assert fs["LBL-TS1"]["strength"] == "strong" and items["LBL-TS1"]["result"] == "FAIL"
    assert "2nd OCR pass" in items["LBL-TS1"]["verified_by"]
    missing = [_tok(t, _at(t)) for t in TAGS if t != "PS13"]
    _, fs, items = _run(missing, strong_alone=True)
    assert fs["MISS-PS13"]["status"] == "CANDIDATE_FAULT" and items["MISS-PS13"]["result"] == "REVIEW"
    assert consensus.fail_without_agent()                                    # the default: no API key needed


def test_zoom_reread_finds_an_unread_label():
    toks = [_tok(t, _at(t)) for t in TAGS if t != "PS13"]
    _, fs, items = _run(toks, zoom={"tokens": [_tok("PS13", _at("PS13"), passes=1, conf=0.9)]})
    assert fs["MISS-PS13"]["status"] == "OK" and fs["MISS-PS13"]["rule"] == "MISSING.zoom"
    assert items["LBL-PS13"]["result"] == "PASS"


def test_wrong_label_text_at_a_device():
    toks = [_tok("TS2" if t == "TS1" else t, _at(t)) for t in TAGS]
    _, fs, items = _run(toks)
    assert fs["LBL-TS1"]["status"] == "CANDIDATE_FAULT" and fs["LBL-TS1"]["found"] == "TS2"
    assert fs["MISS-TS1"]["status"] == "OK"                              # something is labelled there
    assert fs.get("UNK-TS2", {}).get("status") in (None, "SKIP")           # one root cause, not two findings


def test_unknown_labels_need_the_drawings_own_letter_pattern():
    toks = [_tok(t, _at(t)) for t in TAGS] + [_tok("PS19", (2300, 1700)), _tok("XC60", (2300, 1300), passes=3)]
    _, fs, _ = _run(toks)
    assert fs["UNK-PS19"]["status"] == "CANDIDATE_FAULT"
    assert "UNK-XC60" not in fs                                           # a model print ('iC60'), not a tag


def test_ferrules_judge_only_certain_reads():
    toks = [_tok(t, _at(t)) for t in TAGS] + [
        _tok("PS11-1/DS11-2", (300, 1700)),                      # linked in the drawing
        _tok("PS12-1/DS12-2", (500, 1700)),                      # verbatim, two passes, not linked
        _tok("P512-1/DS12-4", (700, 1700), passes=1, conf=0.7)]  # garbled single read
    _, fs, _ = _run(toks)
    assert fs["FER-PS11-1/DS11-2"]["status"] == "OK"
    assert fs["FER-PS12-1/DS12-2"]["status"] == "CANDIDATE_FAULT"
    assert not [k for k in fs if k.startswith("FER-") and "DS12-4" in k]


def test_unplaced_photo_still_verifies_what_it_read():
    reg, fs, items = _run([_tok("PS11", (1200, 700))])
    assert not reg["localised"] and reg["hint"]
    assert items["MISS-PS11"]["result"] == "PASS" and items["LBL-PS11"]["result"] == "PASS"
    assert not any(r["result"] == "FAIL" for r in items.values())


def test_labels_too_small_to_read_are_not_judged():
    kb, photo = _kb(), _photo()
    for t in kb["views"]["front"]["tags"]:
        for i in t["instances"]:
            i["size_pt"] = 0.5                                    # ~5 px letters at this scale
    toks = [_tok(t, _at(t)) for t in TAGS if t != "PS13"]
    reg = register(toks, kb, photo)
    ctx = Context(kb, None, photo, toks, reg, ocr_region=lambda *a: [], workers=1)
    fs = {f["id"]: f for f in run_checks(ctx)[0]}
    assert fs["MISS-PS13"]["status"] == "NOT_IN_VIEW" and fs["LBL-PS13"]["status"] == "NOT_IN_VIEW"


def test_layout_rule_is_scale_free():
    toks = [_tok(t, _at(t)) for t in TAGS]
    f = register(toks, _kb(), _photo())["fits"][0]
    assert layout_consistent(f, (_at("PS13")[0] + 900, _at("PS13")[1] - 30), TAGS["PS13"])[0]       # further right
    assert not layout_consistent(f, (_at("PS11")[0] - 900, _at("PS13")[1]), TAGS["PS13"])[0]       # left of PS11


def test_classify_tokens_splits_labels_ferrules_unknown():
    c = classify_tokens([_tok("PS11", (0, 0)), _tok("PS11-1/DS11-2", (0, 0)), _tok("PS19", (0, 0)),
                         _tok("0S12", (0, 0))], Vocab(_kb()["vocabulary"]))
    assert [r["tag"] for r in c["reads"]] == ["PS11", "DS12"] and c["reads"][1]["method"] == "confusion"
    assert [f["norm"] for f in c["ferrules"]] == ["PS11-1/DS11-2"] and [u["tag_like"] for u in c["unknown"]] == ["PS19"]


def test_consensus_table():
    f = lambda st, strength=None: {"id": "X", "check": "LABEL", "target": "PS11", "expected": "PS11", "found": "PS17",
                                   "status": st, "strength": strength, "box": [0, 0, 10, 10], "conf": 0.7,
                                   "evidence": [], "view": "front"}
    d = lambda v, c=0.9: {"X": {"verdict": v, "confidence": c, "reason": "r", "model": "m"}}
    one = lambda st, strength, dec, on: consensus.decide([f(st, strength)], dec, on, strong_alone=False)[0]["result"]
    assert one("CANDIDATE_FAULT", "strong", d("CONFIRMED_FAULT"), True) == "FAIL"
    assert one("CANDIDATE_FAULT", "weak", d("CONFIRMED_FAULT", 0.9), True) == "FAIL"
    assert one("CANDIDATE_FAULT", "weak", d("CONFIRMED_FAULT", 0.7), True) == "REVIEW"
    assert one("CANDIDATE_FAULT", "strong", d("CONFIRMED_OK"), True) == "PASS"
    assert one("CANDIDATE_FAULT", "strong", d("UNCLEAR"), True) == "REVIEW"
    assert one("CANDIDATE_FAULT", "strong", {}, False) == "REVIEW"
    assert one("UNCERTAIN", None, d("CONFIRMED_OK"), True) == "PASS"
    assert one("UNCERTAIN", None, {}, True) == "REVIEW"
    assert one("OK", None, {}, False) == "PASS"
    assert one("NOT_IN_VIEW", None, {}, False) == "NOT_IN_VIEW"


def test_merge_photos_disagreement_is_review():
    a = {"results": [{"id": "MISS-PS11", "check": "MISSING", "target": "PS11", "result": "FAIL", "found": "x",
                      "verified_by": ["OCR"]}]}
    b = {"results": [{"id": "MISS-PS11", "check": "MISSING", "target": "PS11", "result": "PASS", "found": "y",
                      "verified_by": ["OCR"]}]}
    m = consensus.merge_photos([a, b], _kb())
    assert m["items"][0]["result"] == "REVIEW" and m["items"][0]["note"]
    assert m["coverage"]["total"] == len(TAGS)


def test_check_registry():
    assert list(CHECKS) == ORDER and all(hasattr(CHECKS[n], "question") for n in ORDER)


@needs_real
def test_real_left_wall_photo_end_to_end():
    import pipeline
    gt = json.loads((REAL / "ground_truth.json").read_text(encoding="utf-8"))["photos"]
    name = "IMG_20260726_122949440_HDR.jpg"
    [(rep, _)] = pipeline.inspect_real([str(REAL / name)], str(REAL / "Sanitized_Cabinet_Drawing.pdf"), agent=False)
    res = {r["id"]: r["result"] for r in rep["results"]}
    assert rep["engine_kind"] == "real" and rep["registration"]["localised"] and "left" in rep["views"]
    assert not [k for k, v in res.items() if v == "FAIL"]
    verified = {t for t in gt[name]["visible"] if res.get(f"MISS-{t}") == "PASS"}
    assert verified >= {"CB11", "CB12", "CB13", "CB14", "CB15", "CB16"}
    assert res["ORD-left-CB-1"] == "PASS"
    assert rep["H"] == [[4, 0, 0], [0, 4, 0], [0, 0, 1]] and rep["photo_size"] == [3072, 4096]
