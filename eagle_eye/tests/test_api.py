"""REST API end to end through FastAPI's test client."""
import time

from fastapi.testclient import TestClient

import config
import server

client = TestClient(server.app)


def wait(job_id, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.3)
    raise TimeoutError(job_id)


def test_health_and_catalogues():
    h = client.get("/api/health").json()
    assert h["ok"] and h["checks"] == ["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"]
    assert [s["id"] for s in client.get("/api/samples").json()] == ["01", "02", "03", "04", "05"]
    assert {c["name"] for c in client.get("/api/checks").json()} >= {"GA", "ORDER"}
    assert client.get("/api/samples/03/image?w=200").headers["content-type"] == "image/jpeg"


def test_inspect_recheck_and_downloads(runs_dir):
    j = wait(client.post("/api/inspect", data={"sample": "01"}).json()["id"])
    assert j["status"] == "done", j["error"]
    assert {"parse", "register", "check", "consensus", "report"} <= {e["stage"] for e in j["events"]}
    assert client.get(f"/api/runs/{j['run_id']}").json()["meta"]["counts"]["FAIL"] == 4

    with open(next(config.SAMPLES.glob("05_*.jpg")), "rb") as f:
        r = client.post("/api/inspect", data={"parent": j["run_id"]}, files={"photo": ("after.jpg", f, "image/jpeg")})
    j2 = wait(r.json()["id"])
    assert j2["status"] == "done" and j2["kind"] == "recheck"
    assert client.get(f"/api/runs/{j2['run_id']}").json()["meta"]["recheck"]["CLOSED"] == 3
    assert len(client.get(f"/api/runs/{j2['run_id']}/chain").json()) == 2

    pdf = client.get(f"/api/runs/{j['run_id']}/files/pdf?download=1")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and "attachment" in pdf.headers["content-disposition"]
    assert client.get(f"/api/runs/{j['run_id']}/files/checklist").status_code == 200
    assert client.get(f"/api/runs/{j['run_id']}/items/FER-X3:3/expected").status_code == 200


def test_bad_inputs_are_rejected_cleanly(runs_dir):
    assert client.post("/api/inspect", files={"photo": ("cabinet.gif", b"GIF89a", "image/gif")}).status_code == 400
    assert client.post("/api/inspect", data={"sample": "99"}).status_code == 404
    assert client.get("/api/runs/20200101-000000-dead").status_code == 404
    assert client.get("/api/runs/..%2F..%2Fetc").status_code == 404
    j = wait(client.post("/api/inspect", files={"photo": ("x.jpg", b"not an image", "image/jpeg")}).json()["id"])
    assert j["status"] == "error" and "photo" in j["error"]


def test_forge_endpoint(runs_dir):
    j = wait(client.post("/api/forge", json={"faults": 2, "strength": 1.0, "seed": 777, "count": 1}).json()["id"])
    assert j["status"] == "done", j["error"]
    score = client.get(f"/api/runs/{j['run_id']}").json()["meta"]["forge"]["score"]
    assert score["n_planted"] == 2 and not score["false_alarms"]
    assert client.get("/api/forge/selftest").json()["summary"]["caught"] == 87
