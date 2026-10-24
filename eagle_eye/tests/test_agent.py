"""Claude vision verifier (agent/): tool loop, validation, budget, cache, transcript, backends.

No network and no API key: every model answer comes from a scripted fake client, on a synthetic photo and a stub KB.
"""
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from agent import backends, drawing_extract, prompts, tools, verifier
from agent import config as acfg
from agent.backends import (AnthropicBackend, FakeClient, ReplayBackend, RecordingWrapper, ScriptedBackend,
                            fake_message, refusal_message, text_block, tool_use_block)

FIXTURE = Path(__file__).parent / "fixtures" / "agent_replay_sample.json"
FAKE_KEY = "sk-ant-api03-xxxx-THIS-IS-A-FAKE-KEY-0000"
PHOTO_SHA = "synth0001"
KB = {
    "vocabulary": ["PS11", "PS12", "CB13", "CB14", "DS11"],
    "views": {"front": {"tags": [{"tag": t, "family": t[:2], "center": [100 + 50 * i, 60]}
                                 for i, t in enumerate(["PS11", "PS12", "CB13", "CB14"])]},
              "left": {"tags": [{"tag": "DS11", "family": "DS", "center": [40, 80]}]}},
}
REG = {"in_view": {t: {"view": "front", "predicted": [x, 205]}
                   for t, x in (("PS11", 260), ("PS12", 460), ("CB13", 660), ("CB14", 860))}}
FINDINGS = [
    {"id": "LBL-PS11", "check": "LABEL", "target": "PS11", "view": "front", "expected": "PS11", "found": "PS1l",
     "status": "CANDIDATE_FAULT", "strength": "strong", "box": [200, 150, 320, 260], "rule": "LABEL.read_at_predicted",
     "question": "Does the white label in this crop read PS11?", "evidence": ["read 'PS1l' x1 pass"],
     "reads": [{"raw": "PS1l", "tag": None, "conf": 0.61, "passes": 1, "box": [222, 190, 300, 214], "method": None}],
     "hint": "Re-photo the PS11 label from 30 cm, straight on"},
    {"id": "MISS-CB13", "check": "MISSING", "target": "CB13", "view": "front", "expected": "CB13", "found": None,
     "status": "CANDIDATE_FAULT", "strength": "weak", "box": [600, 150, 720, 260], "question": "Is CB13 present?"},
    {"id": "LBL-PS12", "check": "LABEL", "target": "PS12", "view": "front", "expected": "PS12", "found": "PS1?",
     "status": "UNCERTAIN", "box": [400, 150, 520, 260], "question": "Does the label read PS12?"},
    {"id": "LBL-CB14", "check": "LABEL", "target": "CB14", "status": "OK", "box": [800, 150, 920, 260]},
    {"id": "LBL-DS11", "check": "LABEL", "target": "DS11", "status": "NOT_IN_VIEW", "box": None},
]
BOX = {"LBL-PS11": [200, 150, 320, 260], "MISS-CB13": [600, 150, 720, 260], "LBL-PS12": [400, 150, 520, 260]}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """No credential or agent setting leaks in from the machine; the decision cache lives in tmp."""
    for k in list(os.environ):
        if k.startswith("EAGLE_AGENT_") or k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EAGLE_AGENT_CACHE_DIR", str(tmp_path / "agent_cache"))
    backends._CACHE.clear()


def make_photo():
    rgb = np.full((900, 1200, 3), 60, np.uint8)
    for x in (200, 400, 600, 800):
        rgb[150:260, x:x + 120] = 230
    return {"rgb": rgb, "sha": PHOTO_SHA, "size": [1200, 900], "ignore": [[0, 860, 300, 900], [900, 860, 1200, 900]]}


def make_ctx(findings=FINDINGS, ocr_calls=None):
    calls = ocr_calls if ocr_calls is not None else []

    def ocr(box, rotations, scale):
        calls.append((list(box), tuple(rotations), scale))
        return [{"text": "PS11", "norm": "PS11", "box": [222, 190, 300, 214], "conf": 0.93, "rot": 0},
                {"text": "0S21", "norm": "0S21", "box": [222, 230, 300, 250], "conf": 0.40, "rot": 0}]

    return tools.SimpleContext(make_photo(), KB, None, findings, reg=REG, ocr_region=ocr,
                               drawing_crop=lambda tag: Image.new("RGB", (240, 140), "white"))


def decide(fid, verdict="CONFIRMED_OK", conf=0.9, boxes=None, hint=None, reason="label reads PS11", id=None):
    return fake_message([tool_use_block("record_decision", {
        "finding_id": fid, "verdict": verdict, "confidence": conf, "reason": reason,
        "evidence_boxes": [BOX.get(fid, [10, 10, 50, 50])] if boxes is None else boxes, "rephoto_hint": hint}, id=id)])


def fid_of(params):
    first = params["messages"][0]["content"]
    text = " ".join(b["text"] for b in first if isinstance(b, dict) and b.get("type") == "text")
    ids = re.findall(r'finding_id="([^"]+)"', text)
    return ids[-1] if ids else "overview"


def by_finding(scripts):
    """Fake-client handler: scripts[finding_id][turn] answers that conversation's n-th request (order-independent)."""
    def handler(params):
        fid = fid_of(params)
        if fid == "overview" and fid not in scripts:
            return fake_message([text_block("overview notes")])
        seq = scripts[fid]
        turn = sum(1 for m in params["messages"] if m["role"] == "assistant")
        item = seq[turn]
        return item(params) if callable(item) else item
    return handler


def run(findings, script=None, handler=None, ctx=None, **kw):
    b = ScriptedBackend(script=script, handler=handler)
    res = verifier.verify(findings, ctx or make_ctx(), backend=b, **kw)
    return res, b.client.requests


# ------------------------------------------------------------------ tools
def test_tool_definitions_are_strict_and_grammar_safe():
    for t in tools.TOOLS:
        assert t["strict"] is True
        sch = t["input_schema"]
        assert sch["additionalProperties"] is False and set(sch["required"]) == set(sch["properties"])
    blob = json.dumps(tools.TOOLS)
    for kw in ("minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength"):
        assert kw not in blob                     # unsupported by strict tools: enforced client side instead
    assert [t["name"] for t in tools.TOOLS][-1] == "record_decision"


def test_tool_runner_rejects_invented_items_and_bad_regions():
    ctx = make_ctx()
    r = tools.ToolRunner(ctx, "LBL-PS11")
    out = r.run("project_tag", {"tag": "PS99"})
    assert out.is_error and "never invent" in out.content
    assert json.loads(r.run("project_tag", {"tag": "ps11"}).content) == {"tag": "PS11", "predicted": [260.0, 205.0],
                                                                       "in_photo": True}
    assert r.run("drawing_crop", {"tag": "XG99"}).is_error
    img = r.run("drawing_crop", {"tag": "CB13"})
    assert not img.is_error and img.content[1]["type"] == "image"
    assert r.run("zoom", {"region_xyxy": [5000, 5000, 6000, 6000], "scale": 2}).is_error
    assert r.run("zoom", {"region_xyxy": [1, 2, 3], "scale": 2}).is_error
    assert r.run("get_expected_items", {"view": "bogus", "region_xyxy": None}).is_error
    items = json.loads(r.run("get_expected_items", {"view": "front", "region_xyxy": [150, 100, 500, 300]}).content)
    assert [i["tag"] for i in items["items"]] == ["PS11", "PS12"]
    assert r.run("nope", {}).is_error
    ocr = json.loads(r.run("ocr_region", {"region_xyxy": [190, 140, 330, 270], "rotations": [90, 0]}).content)
    assert ocr["rotations"] == [0, 90] and ocr["tokens"][0]["family"] == "PS"
    assert ocr["tokens"][1]["repaired"] == "DS21"            # kb.tags.coerce_to_family
    over = tools.ToolRunner(ctx, None, allow_decision=False)
    assert over.run("record_decision", {"finding_id": "LBL-PS11"}).is_error


def test_zoom_crops_original_photo_capped_and_masks_watermark():
    ctx = make_ctx()
    r = tools.ToolRunner(ctx, "LBL-PS11")
    out = r.run("zoom", {"region_xyxy": [0, 0, 1200, 900], "scale": 6})
    assert not out.is_error and max(r.crops[-1]["size"]) <= 1568
    small = r.run("zoom", {"region_xyxy": [-50, 150, 60, 200], "scale": 1})      # clamped to the photo, upscaled
    assert r.crops[-1]["box"] == [0, 150, 60, 200] and max(r.crops[-1]["size"]) >= tools.MIN_ZOOM_SIDE
    assert "x6.40" in small.content[0]["text"]
    px = tools.region_pixels(ctx.photo, (0, 800, 1200, 900))
    assert tuple(px[80, 10]) == tools.GREY and tuple(px[80, 600]) == (60, 60, 60)
    assert ctx.photo["rgb"][880, 10, 0] == 60                                      # original never modified


# ------------------------------------------------------------------ the loop
def test_zoom_then_ocr_then_record_decision(tmp_path):
    ocr_calls = []
    res, reqs = run([FINDINGS[0], FINDINGS[3], FINDINGS[4]], ctx=make_ctx(ocr_calls=ocr_calls), run_dir=tmp_path,
                    script=[fake_message([text_block("Zooming."),
                                          tool_use_block("zoom", {"region_xyxy": [190, 140, 330, 270], "scale": 3})]),
                            fake_message([tool_use_block("ocr_region", {"region_xyxy": [190, 140, 330, 270],
                                                                        "rotations": [0]})]),
                            decide("LBL-PS11", "CONFIRMED_OK", 0.93, boxes=[[190, 140, 330, 270]])])
    assert list(res["decisions"]) == ["LBL-PS11"]           # OK / NOT_IN_VIEW findings are never sent
    d = res["decisions"]["LBL-PS11"]
    assert (d["verdict"], d["source"], d["cached"], d["calls"]) == ("CONFIRMED_OK", "api", False, 3)
    assert d["evidence_boxes"] == [[190.0, 140.0, 330.0, 270.0]] and d["model"] == "claude-opus-5-5"
    assert {c["kind"] for c in d["crops"]} >= {"overview", "evidence", "drawing", "zoom"}
    assert res["calls"] == 3 and ocr_calls == [([190, 140, 330, 270], (0,), 3.0)]
    zoom_result = reqs[1][1]["messages"][-1]["content"][0]
    assert zoom_result["type"] == "tool_result" and zoom_result["content"][1]["type"] == "image"
    p = reqs[0][1]
    assert "thinking" not in p and "tool_choice" not in p
    assert p["output_config"] == {"effort": "medium"} and p["cache_control"] == {"type": "ephemeral"}
    assert p["system"][0]["cache_control"] == {"type": "ephemeral"}
    first = p["messages"][0]["content"]
    assert first[1]["type"] == "image" and first[1]["cache_control"] == {"type": "ephemeral"}
    assert 'finding_id="LBL-PS11"' in first[-1]["text"] and "PS1l" in first[-1]["text"]
    # strict + append-only conversation: the assistant turn is echoed back unchanged
    assert reqs[1][1]["messages"][1]["role"] == "assistant" and reqs[2][1]["messages"][:3] == reqs[1][1]["messages"]


def test_parallel_tool_calls_answered_in_one_user_message():
    res, reqs = run([FINDINGS[0]], script=[
        fake_message([tool_use_block("zoom", {"region_xyxy": [190, 140, 330, 270], "scale": 2}, id="t1"),
                      tool_use_block("ocr_region", {"region_xyxy": [190, 140, 330, 270], "rotations": [0, 90]},
                                     id="t2"),
                      tool_use_block("project_tag", {"tag": "PS99"}, id="t3")]),
        decide("LBL-PS11", "CONFIRMED_FAULT", 0.9, reason="label reads PS1I")])
    last = reqs[1][1]["messages"][-1]
    assert last["role"] == "user" and [c["tool_use_id"] for c in last["content"]] == ["t1", "t2", "t3"]
    assert last["content"][2]["is_error"] is True and "is_error" not in last["content"][0]
    assert res["decisions"]["LBL-PS11"]["verdict"] == "CONFIRMED_FAULT"


def test_invalid_record_decision_is_retried_once_then_accepted():
    bad = fake_message([tool_use_block("record_decision", {
        "finding_id": "LBL-PS11", "verdict": "CONFIRMED_FAULT", "confidence": 1.7, "reason": "x",
        "evidence_boxes": [[200, 150, 320, 260]], "rephoto_hint": None})])
    res, reqs = run([FINDINGS[0]], script=[bad, decide("LBL-PS11", "CONFIRMED_FAULT", 0.88)])
    err = reqs[1][1]["messages"][-1]["content"][0]
    assert err["is_error"] is True and "confidence" in err["content"]
    d = res["decisions"]["LBL-PS11"]
    assert (d["verdict"], d["source"], d["calls"]) == ("CONFIRMED_FAULT", "api", 2)


def test_invalid_record_decision_twice_is_unclear():
    no_box = decide("LBL-PS11", "CONFIRMED_OK", 0.9, boxes=[])
    res, _ = run([FINDINGS[0]], script=[no_box, decide("LBL-PS11", "UNCLEAR", 0.3, hint=None), decide("LBL-PS11")])
    d = res["decisions"]["LBL-PS11"]
    assert (d["verdict"], d["source"], d["calls"]) == ("UNCLEAR", "invalid", 2)
    assert "rephoto_hint" in d["reason"] and d["rephoto_hint"] == FINDINGS[0]["hint"]


def test_invented_finding_id_is_rejected(monkeypatch):
    monkeypatch.setenv("EAGLE_AGENT_CACHE", "0")
    res, reqs = run([FINDINGS[0]], script=[decide("LBL-PS77"), decide("LBL-PS11")])
    assert "never invent" in reqs[1][1]["messages"][-1]["content"][0]["content"]
    assert res["decisions"]["LBL-PS11"]["source"] == "api"
    res, reqs = run([FINDINGS[0], FINDINGS[1]], ctx=make_ctx(FINDINGS), handler=by_finding({
        "LBL-PS11": [decide("MISS-CB13"), decide("LBL-PS11")], "MISS-CB13": [decide("MISS-CB13")]}))
    assert set(res["decisions"]) == {"LBL-PS11", "MISS-CB13"} and res["calls"] == 3


def test_no_tool_call_reprompts_once_then_unclear():
    res, reqs = run([FINDINGS[0]], script=[fake_message([text_block("It looks fine to me.")]),
                                           fake_message([text_block("Still fine.")])])
    d = res["decisions"]["LBL-PS11"]
    assert (d["verdict"], d["source"], res["calls"]) == ("UNCLEAR", "no_decision", 2)
    nudge = reqs[1][1]["messages"][-1]
    assert nudge["role"] == "user" and "record_decision" in nudge["content"][0]["text"]


def test_refusal_is_unclear_and_not_cached(tmp_path):
    res, _ = run([FINDINGS[0]], script=[refusal_message("cyber", "declined")])
    d = res["decisions"]["LBL-PS11"]
    assert (d["verdict"], d["source"]) == ("UNCLEAR", "refusal") and "cyber" in d["reason"]
    assert not list((tmp_path / "agent_cache").rglob("*.json"))


def test_tool_turn_limit(monkeypatch):
    monkeypatch.setenv("EAGLE_AGENT_MAX_TURNS", "2")

    def zoom(params):
        return fake_message([tool_use_block("zoom", {"region_xyxy": [190, 140, 330, 270], "scale": 2})])
    res, reqs = run([FINDINGS[0]], script=[zoom, zoom, zoom])
    assert res["decisions"]["LBL-PS11"]["source"] == "turn_limit" and len(reqs) == 3
    assert reqs[2][1]["messages"][-1]["content"][-1]["text"] == prompts.LAST_TURN


def test_api_error_becomes_unclear():
    res, _ = run([FINDINGS[0]], script=[RuntimeError(f"boom {FAKE_KEY}")])
    d = res["decisions"]["LBL-PS11"]
    assert (d["verdict"], d["source"]) == ("UNCLEAR", "error") and FAKE_KEY not in d["reason"]
    assert res["errors"] and FAKE_KEY not in res["errors"][0]


# ------------------------------------------------------------------ budget, overview, cache, escalation
def test_budget_exhaustion(monkeypatch):
    monkeypatch.setenv("EAGLE_AGENT_MAX_CALLS", "2")
    monkeypatch.setenv("EAGLE_AGENT_OVERVIEW", "0")
    monkeypatch.setenv("EAGLE_AGENT_PARALLEL", "1")
    res, reqs = run(FINDINGS, handler=by_finding({k: [decide(k)] for k in BOX}))
    src = {k: d["source"] for k, d in res["decisions"].items()}
    assert src == {"LBL-PS11": "api", "MISS-CB13": "api", "LBL-PS12": "budget"}   # strong first, uncertain last
    assert res["decisions"]["LBL-PS12"]["reason"] == "agent budget exhausted" and res["calls"] == len(reqs) == 2


def test_overview_shares_cached_prefix(tmp_path):
    usage = {"cache_read_input_tokens": 3000, "cache_creation_input_tokens": 0, "input_tokens": 400}
    scripts = {"overview": [fake_message([text_block("Front upper shelf; glare on the right.")],
                                         usage={"cache_creation_input_tokens": 3000})]}
    scripts.update({k: [fake_message(decide(k).content, usage=usage)] for k in BOX})
    events = []
    res, reqs = run(FINDINGS, handler=by_finding(scripts), run_dir=tmp_path, on_event=events.append)
    assert fid_of(reqs[0][1]) == "overview" and len(reqs) == 4 and res["calls"] == 4
    assert res["overview"].startswith("Front upper shelf")
    prefix = reqs[0][1]["messages"][0]["content"][:2]
    for _, p in reqs[1:]:
        assert p["messages"][0]["content"][:2] == prefix and p["tools"] == reqs[0][1]["tools"]
        assert p["system"] == reqs[0][1]["system"]
        assert "Overview notes" in p["messages"][0]["content"][-1]["text"]
    assert prefix[1]["cache_control"] == {"type": "ephemeral"} and "LBL-PS11" in prefix[0]["text"]
    assert res["usage"]["cache_read"] == 9000 and res["usage"]["cache_write"] == 3000
    lines = [json.loads(x) for x in (tmp_path / verifier.TRANSCRIPT).read_text(encoding="utf-8").splitlines()]
    assert sum(1 for e in lines if e["event"] == "response" and e["usage"]["cache_read"] == 3000) == 3
    assert sorted(e["finding_id"] for e in events) == sorted(BOX) and events[-1]["done"] == 3


def test_cache_hit_on_second_run_makes_no_call():
    handler = by_finding({k: [decide(k, "CONFIRMED_FAULT", 0.9, reason=f"{k} is wrong")] for k in BOX})
    first, _ = run(FINDINGS, handler=handler)
    assert all(d["source"] == "api" for d in first["decisions"].values())
    second, reqs = run(FINDINGS, script=[])              # an empty script raises if the client is called
    assert reqs == [] and second["calls"] == 0 and second["cost_usd"] == 0
    for k, d in second["decisions"].items():
        assert d["cached"] is True and d["source"] == "cache" and d["reason"] == f"{k} is wrong"
    moved = [dict(f, found="PS1?") if f["id"] == "LBL-PS11" else f for f in FINDINGS]    # changed question -> miss
    third, reqs = run(moved, handler=handler)
    assert [fid_of(p) for _, p in reqs] == ["LBL-PS11"]


def test_escalation_to_main_model_on_strong_unclear(monkeypatch):
    monkeypatch.setenv("EAGLE_AGENT_MODEL", "claude-fable-5-1")

    def handler(params):
        if params["model"] == "claude-opus-5-5":
            return decide("LBL-PS11", "UNCLEAR", 0.4, boxes=[], hint="closer", reason="too small to read")
        assert params["output_config"] == {"effort": "high"}
        assert "faster first pass" in params["messages"][0]["content"][-1]["text"]
        return decide("LBL-PS11", "CONFIRMED_FAULT", 0.92, reason="reads PS1I")
    res, reqs = run([FINDINGS[0]], handler=handler)
    d = res["decisions"]["LBL-PS11"]
    assert [p["model"] for _, p in reqs] == ["claude-opus-5-5", "claude-fable-5-1"]
    assert (d["verdict"], d["model"], d["calls"]) == ("CONFIRMED_FAULT", "claude-fable-5-1", 2)
    assert d["escalated_from"]["verdict"] == "UNCLEAR"
    assert res["cost_usd"] == pytest.approx(acfg.cost_usd({"input": 1200, "output": 150}, "claude-opus-5-5")
                                            + acfg.cost_usd({"input": 1200, "output": 150}, "claude-fable-5-1"))


def test_escalation_never_takes_a_call_another_finding_needs(monkeypatch):
    monkeypatch.setenv("EAGLE_AGENT_MODEL", "claude-fable-5-1")
    monkeypatch.setenv("EAGLE_AGENT_MAX_CALLS", "2")
    monkeypatch.setenv("EAGLE_AGENT_PARALLEL", "1")
    unclear_ps11 = decide("LBL-PS11", "UNCLEAR", 0.3, boxes=[], hint="closer", reason="glare")
    res, reqs = run(FINDINGS[:2], handler=by_finding({"LBL-PS11": [unclear_ps11], "MISS-CB13": [decide("MISS-CB13")]}))
    d = res["decisions"]
    assert [p["model"] for _, p in reqs] == ["claude-opus-5-5", "claude-opus-5-5"]
    assert d["LBL-PS11"]["verdict"] == "UNCLEAR" and d["LBL-PS11"]["escalation"] == "agent budget exhausted"
    assert d["MISS-CB13"]["source"] == "api"


def test_auto_model_resolution():
    b = ScriptedBackend(models=["claude-haiku-5-5", "claude-opus-5-5", "claude-fable-5-1"])
    assert verifier.resolve_models(b) == ("claude-fable-5-1", "claude-opus-5-5")
    assert verifier.resolve_models(ScriptedBackend(models=["claude-opus-5-5"]))[0] == "claude-opus-5-5"
    assert verifier.resolve_models(ScriptedBackend(models=RuntimeError("401")))[0] == "claude-opus-5-5"
    b.client._models_ret = ["claude-opus-5-5"]           # listed once, then cached
    assert verifier.resolve_models(b)[0] == "claude-fable-5-1"


# ------------------------------------------------------------------ transcript, backends, status
def test_transcript_redacts_keys_and_hashes_images(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    leaky = [dict(FINDINGS[0], evidence=[f"operator pasted {FAKE_KEY} here", "token sk-ant-api03-xxxx-other"])]
    res, reqs = run(leaky, run_dir=tmp_path, script=[
        fake_message([tool_use_block("zoom", {"region_xyxy": [190, 140, 330, 270], "scale": 2})]),
        decide("LBL-PS11", "CONFIRMED_FAULT", 0.9, reason=f"I saw {FAKE_KEY} on the label")])
    text = (tmp_path / verifier.TRANSCRIPT).read_text(encoding="utf-8")
    assert "sk-ant-api03-xxxx" not in text and FAKE_KEY not in text and "[REDACTED]" in text
    assert '"data"' not in text and '"sha256"' in text and "image/jpeg" not in text
    first_req = next(json.loads(x) for x in text.splitlines() if json.loads(x)["event"] == "request")
    image = first_req["messages"][0]["content"][1]
    assert image["type"] == "image" and image["size"] == [1200, 900] and len(image["sha256"]) == 64
    assert "sk-ant-api03-xxxx" not in json.dumps(res)
    assert "sk-ant-api03-xxxx" not in json.dumps(reqs[0][1]["messages"][0]["content"][-1])   # not sent either
    events = [json.loads(x)["event"] for x in text.splitlines()]
    assert events[0] == "start" and events[-1] == "done" and events.count("request") == 2


def test_replay_backend_with_fixture(monkeypatch):
    res = verifier.verify(FINDINGS, make_ctx(), backend=ReplayBackend(FIXTURE))
    d = res["decisions"]
    assert res["calls"] == 0 and res["backend"] == "replay"
    assert (d["LBL-PS11"]["verdict"], d["LBL-PS11"]["source"], d["LBL-PS11"]["model"]) == (
        "CONFIRMED_FAULT", "replay", "claude-opus-5-5")
    assert d["MISS-CB13"]["verdict"] == "UNCLEAR" and "crop changed" in d["MISS-CB13"]["reason"]
    assert d["LBL-PS12"]["verdict"] == "UNCLEAR" and d["LBL-PS12"]["source"] == "replay-miss"
    monkeypatch.setenv("EAGLE_AGENT_REPLAY", str(FIXTURE))       # same through the environment
    assert verifier.status()["backend"] == "replay"
    assert verifier.verify(FINDINGS, make_ctx())["decisions"]["LBL-PS11"]["verdict"] == "CONFIRMED_FAULT"


def test_recording_wrapper_builds_a_replay_file(monkeypatch, tmp_path):
    rec_path = tmp_path / "recorded.json"
    handler = by_finding({k: [decide(k, "CONFIRMED_FAULT" if k == "LBL-PS11" else "CONFIRMED_OK", 0.9)] for k in BOX})
    b = RecordingWrapper(ScriptedBackend(handler=handler), rec_path)
    first = verifier.verify(FINDINGS, make_ctx(), backend=b)
    data = json.loads(rec_path.read_text(encoding="utf-8"))
    assert data["schema"] == backends.REPLAY_SCHEMA and set(data["decisions"]) == {f"{PHOTO_SHA}|{k}" for k in BOX}
    assert all(e["crop_sha"] for e in data["decisions"].values())
    monkeypatch.setenv("EAGLE_AGENT_CACHE", "0")
    again = verifier.verify(FINDINGS, make_ctx(), backend=ReplayBackend(rec_path))
    assert {k: d["verdict"] for k, d in again["decisions"].items()} == \
        {k: d["verdict"] for k, d in first["decisions"].items()}
    assert all(d["source"] == "replay" for d in again["decisions"].values())


def test_fallbacks_opt_in(monkeypatch):
    msg = fake_message([text_block("ok")])
    fc = FakeClient(script=[msg, msg, msg])
    b = AnthropicBackend(client=fc, fallbacks=True)
    b.create({"model": "claude-opus-5-5", "max_tokens": 10, "messages": []})
    b.create({"model": "claude-fable-5-1", "max_tokens": 10, "messages": []})
    b.create({"model": "claude-haiku-5-5", "max_tokens": 10, "messages": []})
    assert [e for e, _ in fc.requests] == ["beta", "beta", "messages"]
    assert fc.requests[0][1]["betas"] == [acfg.FALLBACK_BETA] and fc.requests[0][1]["fallbacks"] == "default"
    monkeypatch.setenv("EAGLE_AGENT_FALLBACKS", "0")
    fc2 = FakeClient(script=[msg])
    AnthropicBackend(client=fc2).create({"model": "claude-opus-5-5", "max_tokens": 10, "messages": []})
    assert fc2.requests[0][0] == "messages"

    sent = []                                              # an SDK whose beta create has no `fallbacks` kwarg

    def old_create(*, model, max_tokens, messages, betas=None, extra_body=None):
        sent.append(extra_body)
        return msg
    old = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=old_create)), messages=None)
    with pytest.raises(RuntimeError, match="External AI APIs are disabled"):
        AnthropicBackend(client=old, fallbacks=True)
    assert sent == []                                      # arbitrary clients cannot escape the offline-only gate

    rejected = Exception("fallbacks: not supported for this organization")
    rejected.status_code = 400
    fc3 = FakeClient(script=[rejected, msg, msg])
    b3 = AnthropicBackend(client=fc3, fallbacks=True)
    b3.create({"model": "claude-opus-5-5", "max_tokens": 10, "messages": []})
    b3.create({"model": "claude-opus-5-5", "max_tokens": 10, "messages": []})
    assert [e for e, _ in fc3.requests] == ["beta", "messages", "messages"]


def test_hosted_client_construction_is_disabled_even_with_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setenv("EAGLE_AGENT_BACKEND", "anthropic")
    monkeypatch.setenv("EAGLE_AGENT_ENABLED", "1")
    assert backends.get_backend()[0] is None
    with pytest.raises(RuntimeError, match="External AI APIs are disabled"):
        AnthropicBackend()


def test_injected_network_backend_is_rejected_before_a_call():
    class NetworkBackend:
        name, kind = "hosted", "llm"

        def create(self, params):
            pytest.fail("an external inference call was attempted")

    res = verifier.verify(FINDINGS, make_ctx(), backend=NetworkBackend())
    assert not res["enabled"] and res["calls"] == 0 and not res["decisions"]
    assert drawing_extract.extract_drawing_tags(Image.new("RGB", (10, 10)), 1, backend=NetworkBackend()) == []


def test_status_with_and_without_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.invalid")      # not a credential
    st = verifier.status()
    assert st["enabled"] is False and st["backend"] is None and "external AI APIs are disabled" in st["reason"]
    assert set(st) >= {"enabled", "backend", "model", "fast_model", "reason"}
    assert verifier.verify(FINDINGS, make_ctx())["enabled"] is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    st = verifier.status()
    assert not st["enabled"] and st["backend"] is None
    assert FAKE_KEY not in json.dumps(st)
    monkeypatch.setenv("EAGLE_AGENT_ENABLED", "0")
    assert verifier.status()["enabled"] is False
    monkeypatch.delenv("EAGLE_AGENT_ENABLED")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("EAGLE_AGENT_BACKEND", "replay")
    monkeypatch.setenv("EAGLE_AGENT_REPLAY", str(tmp_path / "missing.json"))
    assert verifier.status()["enabled"] is False
    monkeypatch.setenv("EAGLE_AGENT_BACKEND", "mock")
    assert verifier.status()["backend"] == "mock"
    res = verifier.verify(FINDINGS, make_ctx())
    assert {d["verdict"] for d in res["decisions"].values()} == {"UNCLEAR"} and res["cost_usd"] == 0
    assert {d["source"] for d in res["decisions"].values()} == {"mock"}
    assert not list(Path(os.environ["EAGLE_AGENT_CACHE_DIR"]).rglob("*.json"))      # mock answers never cached
    monkeypatch.setenv("EAGLE_AGENT_BACKEND", "bogus")
    assert "unknown" in verifier.status()["reason"]


def test_cost_table():
    assert acfg.cost_usd({"input": 1_000_000, "output": 1_000_000}, "claude-opus-5-5") == pytest.approx(24.0)
    assert acfg.cost_usd({"cache_read": 1_000_000, "cache_write": 1_000_000}, "claude-fable-5-1") == \
        pytest.approx(12.75)
    assert acfg.cost_usd({"input": 1_000_000}, "some-future-model") == pytest.approx(10.0)


# ------------------------------------------------------------------ drawing extraction
def test_drawing_extract_disabled_without_key(monkeypatch):
    page = Image.new("RGB", (800, 600), "white")
    assert drawing_extract.extract_drawing_tags(page, 5, ["PS11"]) == []
    monkeypatch.setenv("EAGLE_AGENT_BACKEND", "mock")
    assert drawing_extract.extract_drawing_tags(page, 5) == []
    assert drawing_extract.extract_drawing_tags(page, 5, backend=ReplayBackend(FIXTURE)) == []


def test_drawing_extract_structured_output():
    answer = json.dumps({"tags": [
        {"tag": "PS11", "bbox_norm": [0.10, 0.20, 0.20, 0.25], "view": "Front", "confidence": 0.9},
        {"tag": "ps 12", "bbox_norm": [0.30, 0.20, 0.40, 0.25], "view": None, "confidence": 0.7},
        {"tag": "SEE NOTE 3", "bbox_norm": [0.5, 0.5, 0.6, 0.6], "view": None, "confidence": 0.9},
        {"tag": "PS11", "bbox_norm": [0.1, 0.2, 0.0, 0.25], "view": None, "confidence": 0.9}], "page_notes": "GA"})
    b = ScriptedBackend(handler=lambda p: fake_message([text_block(answer)]))
    page = Image.new("RGB", (2400, 1200), "white")
    tags = drawing_extract.extract_drawing_tags(page, 5, ["PS11", "CB13"], backend=b)
    reqs = b.client.requests
    assert len(reqs) == 2                                    # 2 x 1 tiles for a 2400 px wide page
    for _, p in reqs:
        assert p["output_config"]["format"]["type"] == "json_schema" and "tools" not in p
        assert p["messages"][0]["content"][0]["type"] == "image" and "CB13" in p["messages"][0]["content"][1]["text"]
    assert {t["tag"] for t in tags} == {"PS11", "PS12"}     # prose and the malformed box are dropped
    assert all(t["source"] == "vlm" and 0 <= min(t["bbox_norm"]) <= max(t["bbox_norm"]) <= 1 for t in tags)
    ps11 = [t for t in tags if t["tag"] == "PS11"]
    assert len(ps11) == 2 and ps11[0]["view"] == "front" and ps11[0]["in_vocabulary"] is True
    tile_w = 2400 / (2 - 0.08) / 2400                       # tile 1 starts at x 0: its box maps onto the page
    assert sorted(t["bbox_norm"][0] for t in ps11)[0] == pytest.approx(0.1 * tile_w, abs=1e-3)
    assert [t for t in tags if t["tag"] == "PS12"][0]["in_vocabulary"] is False


def test_drawing_extract_from_pdf_path_and_clip(tmp_path):
    """The call kb.drawing_kb makes: extract_drawing_tags(pdf_path, page_no, clip) -> boxes also in PDF points."""
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "ga.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=842, height=595)
        page.insert_text((150, 150), "PS11", fontsize=6)
        doc.save(str(pdf))
    answer = json.dumps({"tags": [{"tag": "PS11", "bbox_norm": [0.25, 0.5, 0.5, 0.75], "view": None,
                                   "confidence": 0.8}], "page_notes": ""})
    b = ScriptedBackend(handler=lambda p: fake_message([text_block(answer)]))
    tags = drawing_extract.extract_drawing_tags(str(pdf), 1, [100, 100, 300, 200], backend=b)
    assert len(b.client.requests) == 1 and tags[0]["tag"] == "PS11"
    assert tags[0]["bbox"] == [150.0, 150.0, 200.0, 175.0] and tags[0]["in_vocabulary"] is None
    assert drawing_extract.extract_drawing_tags(str(pdf), 1, [100, 100, 300, 200]) == []     # no key: off, no render
