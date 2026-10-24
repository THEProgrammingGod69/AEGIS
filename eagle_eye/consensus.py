"""Evidence-based local consensus: PASS / FAIL / REVIEW / NOT_IN_VIEW / SKIP.

Strong positive OCR + registered geometry can establish a mismatch. Absence never does: a hidden label and a missing
part look alike. Optional local replay/mock decisions are annotations, never authority to turn weak evidence into
PASS or FAIL. Repeated crops/rotations of one OCR model are corroborating reads, not independent models.

    decide(findings, decisions, agent_on) -> report items (legacy-compatible, spec section 9)
    merge_photos(reports, kb) -> cabinet summary across photos
"""
import os

from kb.tags import tag_sort_key

RESULTS = ("PASS", "FAIL", "REVIEW", "SKIP", "NOT_IN_VIEW")
# checks whose strong candidates are positive reads (two agreeing OCR passes + geometry): they may FAIL without the
# agent. MISSING is evidence of absence and is deliberately not here (on Emerson's photos every deterministic MISSING
# "fault" was a label hidden by cables).
STRONG_ALONE_CHECKS = ("LABEL", "UNKNOWN_LABEL", "ORDER")


def fail_without_agent():
    return (os.environ.get("EAGLE_FAIL_WITHOUT_AGENT") or "1").strip().lower() in ("1", "true", "yes", "on")


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
    geo = ["OCR", "geometry"] if f.get("view") else ["OCR"]
    if st == "OK":
        return "PASS", f["found"], [], geo
    if st in ("NOT_IN_VIEW", "SKIP"):
        return st, f["found"], [], []
    reason = f"Replay/test verifier: {d.get('reason')}" if d and d.get("reason") else None
    if st == "CANDIDATE_FAULT":
        if verdict == "CONFIRMED_OK":
            return "REVIEW", f"Unverified: {f['found']}", [reason, "verifier disagrees with the local evidence; "
                                                         "a model answer alone cannot verify this check"], []
        if strong_alone and strength == "strong" and f.get("check") in STRONG_ALONE_CHECKS:
            return "FAIL", f["found"], ["repeated literal OCR reads and registered geometry establish this mismatch"], geo + ["2nd OCR pass"]
        why = reason or (("nothing readable where the drawing places it: a hidden label and a missing part look "
                          "the same, so a person checks" if f.get("check") == "MISSING" else
                          "the evidence is not strong enough for FAIL on its own") if not agent_on
                         else "agent could not settle it")
        return "REVIEW", f"Unverified: {f['found']}", [why], []
    # UNCERTAIN
    return "REVIEW", f"Unclear: {f['found']}", [reason or "not readable with certainty"], geo


def decide(findings, decisions=None, agent_on=False, strong_alone=None, registration=None):
    """Final report items of one photo (order of ``findings`` kept).

    ``decisions`` = optional replay/test annotations. No generated answer or confidence establishes a verification.
    When registration is supplied, every conclusive result requires a valid fit of that finding's own drawing view.
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
            if rc_res == "PASS" and f.get("own_status"):
                own = dict(f, status=f["own_status"], strength=f.get("own_strength"))
                result, found, extra, verified = _one(own, None, agent_on, strong_alone)
            else:
                result, found, extra, verified = "SKIP", f["found"], [], []
        ev += [e for e in extra if e]
        if result in ("PASS", "FAIL") and registration is not None:
            valid = registration.get("valid", registration.get("localised", False))
            views = {fit["view"] for fit in registration.get("fits") or []}
            if not valid or not f.get("view") or f["view"] not in views:
                result, verified = "REVIEW", []
                found = f"Unverified: {f['found']}"
                ev.append("No reliable registration for this drawing view; the reading does not verify its "
                          "correspondence to the expected component")
        item = {"id": f["id"], "check": f["check"], "target": f["target"], "expected": f["expected"],
                "found": found, "result": result, "box": _xywh(f.get("box")),
                "conf": round(float(f.get("conf") or 0.0), 2), "evidence": ev,
                "view": f.get("view"), "drawing": f.get("drawing"), "hint": f.get("hint") if result == "REVIEW" else None,
                "rule": f.get("rule"), "reads": f.get("reads") or [], "strength": f.get("strength"),
                "root_cause": f.get("root_cause") if result == "SKIP" else None, "candidate": f["status"],
                "agent": _agent_view(d), "verified_by": verified}
        if result == "REVIEW" and d and d.get("rephoto_hint"):
            item["hint"] = d["rephoto_hint"]
        if result == "REVIEW" and not item["hint"]:
            item["hint"] = "Use the matching cabinet drawing and capture a sharp photo with surrounding labels visible"
        for k in ("swaps", "found_box"):
            if f.get(k):
                item[k] = f[k] if k != "found_box" else _xywh(f[k])
        for k in ("swatch", "colour", "allowed", "wire_class", "rule_source"):       # wire colour by circuit class
            if f.get(k) is not None:
                item[k] = f[k]
        items.append(item)
    return items


def counts(items):
    return {k: sum(r["result"] == k for r in items) for k in RESULTS}


def conclusive_evidence_issue(item, registration, require_registration=True):
    """Why a stored conclusive result cannot establish current inspection evidence, else ``None``.

    This is also used when historical reports are read. A valid fit for one wall cannot verify a different wall, and
    historical model-only decisions or vocabulary guesses must not re-enter cabinet approval through photo merging.
    The input objects are never modified. ``require_registration=False`` supports generic legacy summary fixtures.
    """
    if item.get("result") not in ("PASS", "FAIL"):
        return None
    rule = item.get("rule") or ""
    if rule.endswith(".read_view_not_placed") or rule == "LABEL.read_not_anchored":
        return "This device was read without verifying its drawing position"
    if rule in ("LABEL.partial_support", "MISSING.partial", "ORDER.ambiguous"):
        return "A partial or ambiguous observation does not verify this check"
    sources = {str(s).strip().lower() for s in item.get("verified_by") or []}
    local = {"ocr", "geometry"} <= sources
    model = bool(sources & {"claude", "agent", "llm", "vlm", "replay", "mock"})
    if model and not local:
        return "A model-only verdict does not establish local visual verification"
    if item.get("result") == "FAIL" and item.get("candidate") == "CANDIDATE_FAULT" and (
            item.get("check") == "MISSING" or (model and item.get("strength") != "strong")):
        return "Absence or weak candidate evidence cannot be confirmed by a model's confidence"
    reg = registration or {}
    if reg.get("valid") is False or reg.get("localised") is False:
        return "No reliable registration was recorded for this photograph"
    if not require_registration:
        return None
    if not (reg.get("valid") is True or reg.get("localised") is True):
        return "No reliable registration was recorded for this photograph"
    views = {f.get("view") for f in reg.get("fits") or [] if f.get("view")}
    views = views or set(reg.get("views") or [])
    if not item.get("view") or item["view"] not in views:
        return "This finding's drawing view was not placed in this photograph"
    if not local:
        return "The report does not record both local OCR and geometry for this finding"
    return None


def coverage(items, kb):
    """Coverage of exact device-label checks plus cabinet approval eligibility.

    Presence alone does not verify a tag: a different or unreadable label can be attached to a present part. Every
    expected tag must have an assessed LABEL check, and every required emitted check must be resolved. A root-cause
    SKIP is resolved only if its parent check was conclusively assessed; unsupported checks never imply approval.
    """
    total = {v: {r["tag"] for r in rec.get("tags", []) if r.get("label_expected", True)}
             for v, rec in (kb.get("views") or {}).items()}
    by_id = {r["id"]: r for r in items}

    def assessed(r):
        seen = set()
        while r["result"] == "SKIP" and r.get("root_cause") in by_id:
            if r["id"] in seen:
                return False
            seen.add(r["id"])
            r = by_id[r["root_cause"]]
        return r["result"] in ("PASS", "FAIL")

    presence = {r["target"] for r in items if r["check"] == "MISSING" and assessed(r)}
    in_view, verified = set(), set()
    for r in items:
        if r["check"] not in ("MISSING", "LABEL"):
            continue
        if r["result"] != "NOT_IN_VIEW":
            in_view.add(r["target"])
        if r["check"] == "LABEL" and r["result"] in ("PASS", "FAIL") and r["target"] in presence:
            verified.add(r["target"])
    all_tags = set().union(*total.values()) if total else set()
    unresolved = [r for r in items if not assessed(r)]
    complete = bool(all_tags) and verified >= all_tags and not unresolved
    return {"in_view": len(in_view & all_tags), "verified": len(verified & all_tags), "total": len(all_tags),
            "ratio": round(len(verified & all_tags) / len(all_tags), 3) if all_tags else 0.0,
            "complete": complete, "approval_allowed": complete and not any(r["result"] == "FAIL" for r in items),
            "unresolved": len(unresolved), "not_in_view": len(all_tags - in_view),
            "scope": "drawing device labels and emitted inspection checks",
            "by_view": {v: {"verified": len(verified & t), "total": len(t)} for v, t in sorted(total.items())}}


_RANK = {"FAIL": 4, "PASS": 3, "REVIEW": 2, "SKIP": 1, "NOT_IN_VIEW": 0}


def merge_photos(reports, kb=None):
    """Combine observed checks across photos; contradictory PASS/FAIL evidence always requires REVIEW."""
    per = {}
    for k, rep in enumerate(reports):
        for r in rep.get("results") or []:
            reg = rep.get("registration") or {}
            real = rep.get("engine_kind") == "real" or "localised" in reg
            issue = conclusive_evidence_issue(r, reg, require_registration=real)
            if issue:
                r = dict(r, result="REVIEW", verified_by=[], found=f"Unverified: {r.get('found', '')}",
                         evidence=list(r.get("evidence") or []) + [issue], guarded=True,
                         hint="Re-check the matching drawing view using complete local evidence")
            per.setdefault(r["id"], []).append((k, r))
    items = []
    for iid, rs in per.items():
        res = {r["result"] for _k, r in rs}
        if "FAIL" in res and "PASS" in res:
            pick = max(rs, key=lambda kr: _RANK[kr[1]["result"]])
            final = "REVIEW"
            note = "photos disagree (FAIL on one, PASS on another)"
        else:
            pick = max(rs, key=lambda kr: (_RANK[kr[1]["result"]], kr[1].get("conf") or 0))
            final, note = pick[1]["result"], None
        r = pick[1]
        items.append({**r, "id": iid, "check": r["check"], "target": r["target"], "result": final, "found": r["found"],
                      "photo": pick[0], "photos": [k for k, _ in rs], "note": note,
                      "per_photo": {str(k): x["result"] for k, x in rs}})
    items.sort(key=lambda it: (it["check"], tag_sort_key(str(it["target"]))))
    out = {"photos": len(reports), "items": items, "counts": {k: sum(i["result"] == k for i in items) for k in RESULTS}}
    if kb is not None:
        out["coverage"] = coverage([dict(i, check=i["check"]) for i in items], kb)
    return out
