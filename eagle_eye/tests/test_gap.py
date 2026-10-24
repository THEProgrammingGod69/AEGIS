"""Fault Forge, synthetic vs real (eval_gap.py): one scorer for both sides, and the API that serves it."""
import json

from fastapi.testclient import TestClient

import eval_gap
from server import app


def test_outcome_ranks_fail_review_pass_unassessed():
    assert eval_gap.outcome(["PASS", "REVIEW", "FAIL"]) == "FAIL"
    assert eval_gap.outcome(["PASS", "REVIEW"]) == "REVIEW"
    assert eval_gap.outcome(["PASS", None]) == "PASS"                  # cleared: an incorrect PASS
    assert eval_gap.outcome(["NOT_IN_VIEW", "SKIP"]) == "unassessed"
    assert eval_gap.outcome([]) == "unassessed"


def _row(outcomes, false_fail=0, reviews=0, judged=10, not_in_view=0, items=12, category="missing"):
    return {"photo": f"{category}.jpg", "faults": [{"category": category, "outcome": o} for o in outcomes], "false_fail": false_fail,
            "reviews": reviews, "judged": judged, "not_in_view": not_in_view, "items": items, "seconds": 2.0}


def test_summary_and_gap_score_both_sides_the_same_way():
    syn = [_row(["FAIL", "FAIL"]), _row(["FAIL"], category="swap")]
    real = [_row(["FAIL", "REVIEW"], reviews=2, not_in_view=6), _row(["PASS", "unassessed"], false_fail=1, category="swap")]
    rep = eval_gap.build(real=real, synth_path="/nonexistent.json")
    assert rep["synthetic"] is None and rep["gap"] is None             # no saved self-test here
    s, r = eval_gap.summarize(syn), rep["real"]
    assert (s["planted"], s["FAIL"], s["fail_rate"]) == (3, 3, 1.0)
    assert (r["planted"], r["FAIL"], r["REVIEW"], r["PASS"], r["unassessed"]) == (4, 1, 1, 1, 1)
    assert (r["fail_rate"], r["flag_rate"], r["incorrect_pass_rate"]) == (0.25, 0.5, 0.25)
    assert r["false_fail"] == 1 and r["false_fail_rate"] == 0.05 and r["review_rate"] == 0.1
    assert r["not_in_view_rate"] == 0.25
    assert r["categories"]["swap"]["PASS"] == 1 and r["categories"]["ferrule"]["planted"] == 0


def test_synthetic_side_matches_the_shipped_self_test():
    rep = eval_gap.build()
    s = rep["synthetic"]
    st = json.loads((eval_gap.config.OUT / "forge" / "summary.json").read_text(encoding="utf-8"))
    assert s["planted"] == st["planted"] and s["FAIL"] == st["caught"]
    assert s["false_fail"] == st["false_alarms"] and s["judged"] == st["correct_items"]
    assert rep["real"] is None and "data/emerson" in rep["real_reason"]


def test_api_serves_the_comparison():
    client = TestClient(app)
    for path in ("/api/forge/gap", "/api/v2/forge/gap"):
        res = client.get(path)
        assert res.status_code == 200
        body = res.json()
        assert body["schema"] == eval_gap.SCHEMA and {c["id"] for c in body["categories"]} >= {"missing", "swap"}
