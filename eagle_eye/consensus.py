"""Phase 6 - consensus: candidate findings + agent decisions -> PASS / FAIL / REVIEW / NOT_IN_VIEW / SKIP (spec section 8).

A FAIL needs two independent signals that agree: the deterministic candidate (OCR + geometry) and the Claude agent's
CONFIRMED_FAULT. Anything the two do not agree on, or that the agent could not settle, is REVIEW with a precise re-photo
hint. With the agent off, ``EAGLE_FAIL_WITHOUT_AGENT=1`` (on-prem, no-cloud mode) lets a *strong* candidate FAIL.

    decide(findings, decisions, agent_on) -> report items (legacy-compatible, spec section 9)
    merge_photos(reports, kb) -> cabinet summary across photos
"""
import os

from kb.tags import tag_sort_key

RESULTS = ("PASS", "FAIL", "REVIEW", "SKIP", "NOT_IN_VIEW")
WEAK_FAIL_CONF = 0.85


def fail_without_agent():
    return (os.environ.get("EAGLE_FAIL_WITHOUT_AGENT") or "0").strip().lower() in ("1", "true", "yes", "on")


def _xywh(b):
    if not b:
        return [0.0, 0.0, 0.0, 0.0]
    return [round(b[0], 1), round(b[1], 1), round(max(0.0, b[2] - b[0]), 1), round(max(0.0, b[3] - b[1]), 1)]


def _agent_view(d):
    if not d:
        return None
    return {"decision": d.get("verdict"), "confidence": d.get("confidence"), "reason": d.get("reason"),
            "model": d.get("model"), "cached": bool(d.get("cached")), "source": d.get("source"),
            "evidence_boxes": d.get("evidence_boxes") or [], "rephoto_hint": d.get("rephoto_hint"),
            "crops": [{k: c.get(k) for k in ("kind", "box", "tag", "sha", "size")} for c in d.get("crops") or []]}


def _one(f, d, agent_on, strong_alone):
    """(result, found, extra evidence, verified_by) of one finding that is not root-cause suppressed."""
    st, strength = f["status"], f.get("strength")
    verdict = (d or {}).get("verdict")
    conf = float((d or {}).get("confidence") or 0)
    geo = ["OCR", "geometry"] if f.get("view") else ["OCR"]
    if st == "OK":
        return "PASS", f["found"], [], geo
    if st in ("NOT_IN_VIEW", "SKIP"):
        return st, f["found"], [], []
    reason = f"Claude: {d.get('reason')}" if d and d.get("reason") else None
    if st == "CANDIDATE_FAULT":
        if verdict == "CONFIRMED_FAULT" and (strength == "strong" or conf >= WEAK_FAIL_CONF):
            return "FAIL", f["found"], [reason], geo + ["Claude"]
        if verdict == "CONFIRMED_FAULT":
            return "REVIEW", f"Unverified: {f['found']}", [reason, f"agent confidence {conf:.2f} < {WEAK_FAIL_CONF} on "
                                                                   f"weak evidence"], geo + ["Claude"]
        if verdict == "CONFIRMED_OK":
            return "PASS", f["expected"], [reason, "agent overturned the automated candidate"], ["Claude"]
        if not agent_on and strong_alone and strength == "strong":
            return "FAIL", f["found"], ["deterministic-only mode (EAGLE_FAIL_WITHOUT_AGENT): strong evidence"], geo
        why = reason or ("agent off: a second, independent signal is needed for FAIL" if not agent_on
                         else "agent could not settle it")
        return "REVIEW", f"Unverified: {f['found']}", [why], geo + (["Claude"] if d else [])
    # UNCERTAIN
    if verdict == "CONFIRMED_OK":
        return "PASS", f["expected"], [reason, "read by the agent"], ["Claude"]
    return "REVIEW", f"Unclear: {f['found']}", [reason or "not readable with certainty"], geo


def decide(findings, decisions=None, agent_on=False, strong_alone=None):
    """Final report items of one photo (order of ``findings`` kept).

    ``decisions`` = {finding_id: agent decision}. Root-cause SKIPs follow their cause: when the agent clears a
    missing-part candidate, the label item it suppressed becomes PASS (the agent read the label) and a suppressed
    ferrule falls back to its own result.
    """
    decisions = decisions or {}
    strong_alone = fail_without_agent() if strong_alone is None else strong_alone
    by_id = {f["id"]: f for f in findings}
    first = {}
    for f in findings:
        if f["status"] != "SKIP" or not f.get("root_cause"):
            first[f["id"]] = _one(f, decisions.get(f["id"]), agent_on, strong_alone)
    items = []
    for f in findings:
        d = decisions.get(f["id"])
        ev = list(f.get("evidence") or [])
        if f["id"] in first:
            result, found, extra, verified = first[f["id"]]
        else:
            rc = f.get("root_cause")
            rc_res = first.get(rc, ("SKIP",))[0] if rc in by_id else "SKIP"
            if rc_res == "PASS" and f["check"] == "LABEL" and rc.startswith("MISS-"):
                result, found, extra, verified = "PASS", f["expected"], [f"{rc} cleared by the agent: label read"], ["Claude"]
            elif rc_res == "PASS" and f.get("own_status"):
                own = dict(f, status=f["own_status"], strength=f.get("own_strength"))
                result, found, extra, verified = _one(own, None, agent_on, strong_alone)
            else:
                result, found, extra, verified = "SKIP", f["found"], [], []
        ev += [e for e in extra if e]
        item = {"id": f["id"], "check": f["check"], "target": f["target"], "expected": f["expected"],
                "found": found, "result": result, "box": _xywh(f.get("box")),
                "conf": round(float((d or {}).get("confidence") or f.get("conf") or 0.0), 2), "evidence": ev,
                "view": f.get("view"), "drawing": f.get("drawing"), "hint": f.get("hint") if result == "REVIEW" else None,
                "rule": f.get("rule"), "reads": f.get("reads") or [], "strength": f.get("strength"),
                "root_cause": f.get("root_cause") if result == "SKIP" else None, "candidate": f["status"],
                "agent": _agent_view(d), "verified_by": verified}
        if result == "REVIEW" and d and d.get("rephoto_hint"):
            item["hint"] = d["rephoto_hint"]
        for k in ("swaps", "found_box"):
            if f.get(k):
                item[k] = f[k] if k != "found_box" else _xywh(f[k])
        items.append(item)
    return items


def counts(items):
    return {k: sum(r["result"] == k for r in items) for k in RESULTS}


def coverage(items, kb):
    """Verified label-expected tags / tags on the GA views (per view too)."""
    total = {v: {r["tag"] for r in rec.get("tags", []) if r.get("label_expected", True)}
             for v, rec in (kb.get("views") or {}).items()}
    in_view, verified = set(), set()
    for r in items:
        if r["check"] not in ("MISSING", "LABEL"):
            continue
        if r["result"] != "NOT_IN_VIEW":
            in_view.add(r["target"])
        if r["check"] == "MISSING" and r["result"] in ("PASS", "FAIL"):
            verified.add(r["target"])
    all_tags = set().union(*total.values()) if total else set()
    return {"in_view": len(in_view & all_tags), "verified": len(verified & all_tags), "total": len(all_tags),
            "ratio": round(len(verified & all_tags) / len(all_tags), 3) if all_tags else 0.0,
            "by_view": {v: {"verified": len(verified & t), "total": len(t)} for v, t in sorted(total.items())}}


_RANK = {"FAIL": 4, "PASS": 3, "REVIEW": 2, "SKIP": 1, "NOT_IN_VIEW": 0}


def merge_photos(reports, kb=None):
    """Cabinet summary over several photos: per item, the best evidence wins; FAIL on one photo and PASS on another
    is a disagreement -> REVIEW (unless the agent confirmed the FAIL and nothing confirmed the PASS)."""
    per = {}
    for k, rep in enumerate(reports):
        for r in rep.get("results") or []:
            per.setdefault(r["id"], []).append((k, r))
    items = []
    for iid, rs in per.items():
        res = {r["result"] for _k, r in rs}
        if "FAIL" in res and "PASS" in res:
            fail_agent = any(r["result"] == "FAIL" and "Claude" in (r.get("verified_by") or []) for _k, r in rs)
            pass_agent = any(r["result"] == "PASS" and "Claude" in (r.get("verified_by") or []) for _k, r in rs)
            pick = max(rs, key=lambda kr: _RANK[kr[1]["result"]])
            final = "FAIL" if fail_agent and not pass_agent else "REVIEW"
            note = "photos disagree (FAIL on one, PASS on another)"
        else:
            pick = max(rs, key=lambda kr: (_RANK[kr[1]["result"]], kr[1].get("conf") or 0))
            final, note = pick[1]["result"], None
        r = pick[1]
        items.append({"id": iid, "check": r["check"], "target": r["target"], "result": final, "found": r["found"],
                      "photo": pick[0], "photos": [k for k, _ in rs], "note": note,
                      "per_photo": {str(k): x["result"] for k, x in rs}})
    items.sort(key=lambda it: (it["check"], tag_sort_key(str(it["target"]))))
    out = {"photos": len(reports), "items": items, "counts": {k: sum(i["result"] == k for i in items) for k in RESULTS}}
    if kb is not None:
        out["coverage"] = coverage([dict(i, check=i["check"]) for i in items], kb)
    return out
