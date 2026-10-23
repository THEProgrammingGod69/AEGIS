"""Stateless cloud API (/api/v2): one streamed response carries the whole run, nothing stays on the server."""
import base64
import json

from fastapi.testclient import TestClient

import config
import server

client = TestClient(server.app)


def stream(resp):
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def result(msgs):
    errors = [m for m in msgs if m["type"] == "error"]
    assert not errors, errors
    res = [m for m in msgs if m["type"] == "result"]
    assert len(res) == 1
    return res[0]


def test_v2_health_and_cors():
    h = client.get("/api/v2/health").json()
    assert h["ok"] and h["stateless"] and h["checks"][0] == "GA"
    pre = client.options("/api/v2/forge", headers={"Origin": "https://eagle-eye-enigma.vercel.app",
                                                    "Access-Control-Request-Method": "POST",
                                                    "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "*"


def test_v2_inspect_then_stateless_recheck(runs_dir):
    msgs = stream(client.post("/api/v2/inspect", data={"sample": "01"}))
    assert {"parse", "register", "check", "report"} <= {m["event"]["stage"] for m in msgs if m["type"] == "event"}
    r1 = result(msgs)
    meta = r1["payload"]["meta"]
    assert meta["counts"]["FAIL"] == 4 and meta["version"] == 1
    assert "path" not in meta["inputs"]["ga"]                      # no server paths leak to the browser
    files = r1["files"]
    assert base64.b64decode(files["pdf"])[:4] == b"%PDF"
    assert base64.b64decode(files["checklist"])[:2] == b"PK"
    assert base64.b64decode(files["marked"])[:2] == b"\xff\xd8"
    assert "overlay" not in files                                  # demo drawing: the console ships its overlay
    assert not list(runs_dir.iterdir())                            # nothing kept server-side

    parent = json.dumps(dict(meta=meta, report=r1["report"]))
    with open(next(config.SAMPLES.glob("05_*.jpg")), "rb") as f:
        r2 = result(stream(client.post("/api/v2/inspect", files={"photo": ("after.jpg", f, "image/jpeg"),
                                                                 "parent": ("parent.json", parent, "application/json")})))
    m2 = r2["payload"]["meta"]
    assert m2["version"] == 2 and m2["parent"] == meta["id"] and m2["root"] == meta["id"]
    assert m2["recheck"]["CLOSED"] == 3 and m2["recheck"]["OPEN"] == 1
    assert m2["label"].startswith("Re-check")


def test_v2_forge_scores_against_answer_key(runs_dir):
    r = result(stream(client.post("/api/v2/forge", json={"faults": 2, "seed": 777})))
    score = r["payload"]["meta"]["forge"]["score"]
    assert score["n_planted"] == 2 and not score["false_alarms"]
    assert base64.b64decode(r["files"]["photo"])[:2] == b"\xff\xd8"


def test_v2_errors(runs_dir):
    assert client.post("/api/v2/inspect", data={"sample": "99"}).status_code == 404
    assert client.post("/api/v2/inspect", files={"parent": ("p.json", b"{nope", "application/json")},
                       data={"sample": "01"}).status_code == 400
    msgs = stream(client.post("/api/v2/inspect", files={"photo": ("x.jpg", b"not an image", "image/jpeg")}))
    assert msgs[-1]["type"] == "error" and "photo" in msgs[-1]["detail"]
    assert client.post("/api/v2/forge", json={"faults": 9}).status_code == 422


def test_review_audit_trail(runs_dir):
    import service
    meta = service.run_inspection(next(config.SAMPLES.glob("01_*.jpg")), reports=False)
    r = client.post(f"/api/runs/{meta['id']}/review", json={"item": "FER-X3:3", "decision": "FAIL", "note": "ferrule missing, confirmed"})
    assert r.status_code == 200
    rev = r.json()["reviews"]["FER-X3:3"]
    assert rev["decision"] == "FAIL" and rev["by"] == "Inspector" and rev["at"]
    assert client.post(f"/api/runs/{meta['id']}/review", json={"item": "NOPE", "decision": "PASS"}).status_code == 404
    assert client.post(f"/api/runs/{meta['id']}/review", json={"item": "FER-X3:3", "decision": "MAYBE"}).status_code == 422
    cleared = client.post(f"/api/runs/{meta['id']}/review", json={"item": "FER-X3:3", "decision": "CLEAR"}).json()
    assert "FER-X3:3" not in cleared["reviews"]
    pdf, xlsx = service.build_reports(meta["id"])                    # deferred reports still build later
    assert pdf.exists() and xlsx.exists()
