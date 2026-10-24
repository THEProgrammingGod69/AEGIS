"""Showcase cases for the History page (showcase.py): the demo-cabinet cases run for real and behave exactly as their
answer keys say; the API starts the same build as a job."""
import pytest

import service
import showcase


def test_cases_are_numbered_once_and_tell_what_to_look_at():
    cases = [c for c, _spec in showcase.demo_cases() + showcase.real_cases()]
    assert [c["n"] for c in cases] == sorted({c["n"] for c in cases})
    assert len({c["case"] for c in cases}) == len(cases)
    for c in cases:
        assert c["title"] and c["story"] and c["look"] and c["kind"] in ("demo", "real")
        if c["kind"] == "real":
            assert "not a photograph" in c["story"]              # the renders are never passed off as photos


def test_every_demo_case_behaves_as_its_answer_key_says(runs_dir):
    rows = showcase.build(real=False)
    assert [r["case"] for r in rows] == [c["case"] for c, _s in showcase.demo_cases()]
    assert all(r["ok"] for r in rows), [r for r in rows if not r["ok"]]
    metas = {r["case"]: service.get_meta(r["run"]) for r in rows}
    assert metas["demo-recheck"]["parent"] == metas["demo-four-faults"]["id"]          # the re-check chain
    assert all(m["showcase"]["case"] == k and m["label"].startswith("Showcase · ") for k, m in metas.items())
    assert metas["demo-hidden-faults"]["forge"]["score"]["n_planted"] == 3
    assert metas["demo-clean"]["counts"]["FAIL"] == 0 and metas["demo-four-faults"]["counts"]["FAIL"] == 4


def test_a_case_that_does_not_behave_is_reported_not_hidden(runs_dir):
    [(case, spec)] = [cs for cs in showcase.demo_cases() if cs[0]["case"] == "demo-clean"]
    meta = service.run_inspection(service.sample_path("01"), label="x", source="sample", showcase=case)
    problems = showcase._check(meta, spec["expect"])          # the four-faults photo is not a clean cabinet
    assert any("FAIL count 4" in p for p in problems) and any("unexpected FAIL" in p for p in problems)


@pytest.mark.parametrize("real", [0, 3])
def test_api_reports_what_it_can_build_and_starts_the_showcase_job(monkeypatch, runs_dir, real):
    import time

    from fastapi.testclient import TestClient

    import server
    monkeypatch.setattr(showcase, "real_cases", lambda: [None] * real)
    c = TestClient(server.app)
    assert c.get("/api/showcase").json() == {"demo": len(showcase.demo_cases()), "real": real}
    started = []
    monkeypatch.setattr(showcase, "build", lambda **kw: started.append(kw) or [])
    j = c.post("/api/showcase").json()
    assert j["kind"] == "showcase" and j["label"] == "Showcase cases"
    for _ in range(200):                                   # the job runs on the worker thread: let it finish here
        v = c.get(f"/api/jobs/{j['id']}").json()
        if v["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert v["status"] == "done" and started and v["runs"] == []
