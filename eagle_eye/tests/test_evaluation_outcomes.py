"""Regression tests: referrals must not inflate defect recall or invent real measurements."""
import json

import pytest

import config
import evaluation
from eval_real import _fault_outcome, score_forged, score_real
from eval_forge import summarize


def item(tag, result, check="LABEL"):
    return dict(id=("LBL-" if check == "LABEL" else "MISS-") + tag,
                target=tag, check=check, result=result)


def test_presence_does_not_verify_unreadable_label():
    score = score_real([item("PS11", "PASS", "MISSING"), item("PS11", "REVIEW")],
                       {"visible": ["PS11"]})
    assert score["verified"] == [] and score["missed"] == ["PS11"]


def test_real_defect_outcomes_are_separate():
    results = [item("PS11", "FAIL"), item("PS12", "REVIEW"), item("PS13", "PASS"),
               item("PS14", "NOT_IN_VIEW")]
    score = score_real(results, {"deviations": [{"target": f"PS1{i}"} for i in range(1, 5)]})
    assert score["deviations_confirmed"] == ["PS11"]
    assert score["deviations_review"] == ["PS12"]
    assert score["deviations_incorrect_pass"] == ["PS13"]
    assert score["deviations_unassessed"] == ["PS14"]


def test_annotation_for_one_tag_cannot_hide_false_fail_on_a_similar_tag():
    rows = [item("PS11", "FAIL"), item("XPS11", "FAIL")]
    ground_truth = {"deviations": [{"target": "PS11"}]}
    assert score_real(rows, ground_truth)["false_fail"] == ["LBL-XPS11"]
    assert score_forged(rows, {"expect": ["LBL-PS12"], "tags": ["PS12"]}, ground_truth)["false_fail"] == ["LBL-XPS11"]


def test_missing_results_do_not_count_as_detection_or_clearance():
    assert _fault_outcome([]) == "unassessed"
    assert _fault_outcome([item("PS11", "SKIP")]) == "unassessed"
    assert _fault_outcome([item("PS11", "PASS"), item("PS11", "NOT_IN_VIEW", "MISSING")]) == "unassessed"
    assert _fault_outcome([item("PS11", "PASS", "MISSING"), item("PS11", "SKIP")]) == "unassessed"


def test_forged_review_is_referral_not_confirmation():
    score = score_forged([item("PS11", "REVIEW")], {"expect": ["LBL-PS11"], "tags": ["PS11"]}, {})
    assert score["caught"] and score["referred"] and not score["confirmed"]
    assert not score["incorrect_pass"]


def test_absent_catalogue_metrics_are_null(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path)
    for dataset in evaluation.catalogue()["datasets"]:
        assert dataset["status"] == "not_evaluated"
        assert dataset["confirmed"] is None and dataset["incorrect_pass"] is None


@pytest.mark.parametrize("url", ["/api/evaluation", "/api/v2/evaluation"])
def test_evaluation_api_keeps_missing_real_measurements_distinct(url, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import server

    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path)
    response = TestClient(server.app).get(url)
    assert response.status_code == 200
    datasets = {row["source"]: row for row in response.json()["datasets"]}
    assert set(datasets) == {"real", "synthetic"}
    assert datasets["real"]["status"] == "not_evaluated"
    assert datasets["real"]["confirmed"] is None and datasets["real"]["false_fail"] is None
    assert str(tmp_path) not in response.text           # private data locations are never published


def test_historical_referrals_are_not_relabelled_as_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path)
    folder = tmp_path / "real_eval"
    folder.mkdir()
    (folder / "summary.json").write_text(json.dumps({"total": {"deviations": 4, "deviations_flagged": 4},
                                                      "photos": {"photo.jpg": {}}}))
    real = evaluation.catalogue()["datasets"][1]
    assert real["status"] == "legacy" and real["total_faults"] == 4
    assert real["confirmed"] is None and real["referred"] is None


def test_resummarizing_old_synthetic_results_does_not_claim_current_engine():
    row = dict(caught={"LBL-PS11": True}, found={"LBL-PS11": "FAIL"}, n_items=2, n_skip=0,
               false_alarms=[], reviews=[], faults=[], sec=1)
    assert summarize([row])["engine_version"] is None
    assert summarize([dict(row, engine_version=config.VERSION)])["engine_version"] == config.VERSION
