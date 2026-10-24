"""Phase 7 - the real-cabinet pipeline (spec section 10): drawing -> OCR -> registration -> checks -> agent -> consensus.

    inspect_real(photos, ga_pdf, ...) -> [(report, ctx), ...]     one report per photo, plus pipeline.session(...)

Stage events (``on_event``) use the console's stage names so the live pipeline view works for both engines:
``parse`` (drawing knowledge base), ``ocr``, ``register``, ``check`` (per check), ``agent``, ``consensus``; the service
adds ``report``. Every event carries ``t`` (seconds since the start) and ``engine: "real"``.

The report is legacy-compatible (spec section 9): items carry ``box`` = [x, y, w, h] in photo pixels and the report
``H = diag(R, R, 1)``, so ``report.to_photo(box, H)`` returns the box corners unchanged and every renderer works.
"""
import time
from pathlib import Path

import config
import consensus
from checks import ORDER as CHECK_ORDER
from checks import Context, run_checks
from inspector import R, InspectionError
from kb import drawing_kb
from kb.tags import tag_sort_key
from vision import ocr
from vision.preprocess import load_photo
from vision.register import register

LEGACY_TO_REAL = {"GA": ["MISSING"], "ORDER": ["ORDER"], "LABEL": ["LABEL", "UNKNOWN_LABEL"], "FERRULE": ["FERRULE"],
                  "COLOUR": ["COLOUR"]}


def real_enabled(enabled):
    """Check names for the real engine; the console's legacy names (GA, LABEL ...) are mapped onto them."""
    if not enabled:
        return list(CHECK_ORDER)
    out = []
    for e in enabled:
        for n in LEGACY_TO_REAL.get(e, [e]):
            if n not in out:
                out.append(n)
    return [c for c in CHECK_ORDER if c in out] + [c for c in out if c not in CHECK_ORDER]


def _agent_status(agent):
    if agent is False:
        return {"enabled": False, "backend": None, "reason": "switched off for this run"}
    try:
        from agent import status
        st = status()
    except Exception as e:  # noqa: BLE001 - the deterministic engine never depends on the agent
        return {"enabled": False, "backend": None, "reason": f"agent unavailable: {type(e).__name__}: {e}"}
    if agent not in (None, True):
        st = dict(st, enabled=True, backend=getattr(agent, "name", "custom"), reason="backend supplied by the caller")
    return st


def _devices(reg, ctx):
    """Expected items in view as legacy 'devices' (photo-px boxes) for the drawing layer of the console."""
    out = []
    for tag in sorted(reg["in_view"], key=tag_sort_key):
        b = ctx.label_box(tag)
        if not b:
            continue
        xywh = [round(b[0], 1), round(b[1], 1), round(b[2] - b[0], 1), round(b[3] - b[1], 1)]
        out.append({"tag": tag, "type": (ctx.tag_rec(tag) or {}).get("family") or "device", "box": xywh,
                    "label_box": xywh})
    return out


def _registration(reg, ctx):
    outl = [o["tag"] for f in reg["fits"] for o in f["outliers"]]
    pts = []
    for f in reg["fits"]:
        s = max(f["scale_px_per_pt"], 1e-6)
        for a in f["inliers"]:
            pts.append({"tag": a["tag"], "kind": "label", "inlier": True, "found_px": a["photo"],
                        "expected_px": [round(v, 1) for v in _project(f, a["drawing"])], "found_mm": a["drawing"],
                        "expected_mm": a["drawing"], "residual_mm": round(a["residual_px"] / s, 2)})
        for o in f["outliers"]:
            pts.append({"tag": o["tag"], "kind": "label", "inlier": False, "found_px": o["photo"],
                        "expected_px": o["predicted"], "found_mm": o["drawing"], "expected_mm": o["drawing"],
                        "residual_mm": round(o["residual_px"] / s, 2)})
    for fr in ctx.ferrules:
        pts.append({"tag": fr["norm"], "kind": "ferrule", "inlier": None, "found_px": [round(v, 1) for v in fr["center"]],
                    "expected_px": [round(v, 1) for v in fr["center"]], "found_mm": [0, 0], "expected_mm": [0, 0],
                    "residual_mm": 0})
    fits = [{k: f[k] for k in ("view", "page", "model", "H", "scale_px_per_pt", "rms_px", "tol_px", "inliers",
                               "outliers", "coverage_photo", "coverage_drawing")} for f in reg["fits"]]
    targets = sum(1 for t in reg["in_view"] if ctx.label_expected(t))
    primary = reg["fits"][0]["coverage_photo"] if reg["fits"] else []
    return {"anchors": reg["anchors"], "inliers": reg["inliers"], "outliers": sorted(set(outl), key=tag_sort_key),
            "refined": any(f["model"] == "homography" for f in reg["fits"]), "targets": targets,
            "localised": reg["localised"], "hint": reg["hint"], "views": [f["view"] for f in reg["fits"]],
            "candidates": reg["candidates"], "fits": fits, "quad": primary, "anchor_points": pts,
            "not_in_view": len(reg["not_in_view"])}


def _project(fit, xy):
    from vision.register import project
    return project(fit, xy)


def _warnings(reg, photo, agent_st, items, kb):
    w = []
    if not reg["localised"]:
        w.append({"code": "weak_registration",
                  "message": (reg["hint"] or "The photo could not be placed on the drawing.") +
                             " Positions were not judged, so nothing can FAIL on position or absence."})
    q = photo.get("quality") or {}
    if q.get("issues") and q.get("score", 1) < 0.55:
        w.append({"code": "photo_quality", "message": "Photo quality: " + "; ".join(q["issues"]) +
                  ". Unreadable labels are NOT_IN_VIEW or REVIEW, never FAIL."})
    if not agent_st.get("enabled") and any(r["result"] == "REVIEW" and r.get("candidate") == "CANDIDATE_FAULT"
                                           for r in items):
        w.append({"code": "agent_off", "message": "Claude verifier is off (" + str(agent_st.get("reason")) + "): "
                  "a candidate fault needs a second, independent signal to become FAIL, so it stays REVIEW."})
    return w


def inspect_real(photos, ga_pdf, wires=None, checklist=None, enabled=None, on_event=None, agent=None, run_dir=None,
                 ocr_mode=None, names=None):
    """Inspect one or more photos of a real cabinet against its drawing set -> [(report, ctx)].

    ``photos``: paths, raw bytes or ``load_photo`` dicts. ``agent``: None = from the environment, False = off, or a
    backend object (tests, replay). ``run_dir``: where the agent transcript goes. ``names``: display names of the photos.
    """
    t0 = time.perf_counter()
    emit = on_event or (lambda ev: None)
    clock = lambda: round(time.perf_counter() - t0, 3)  # noqa: E731

    def stage(name, status, **kw):
        emit(dict(stage=name, status=status, t=clock(), engine="real", **kw))

    photos = list(photos if isinstance(photos, (list, tuple)) else [photos])
    if not photos:
        raise InspectionError("No photo to inspect.")
    stage("parse", "start")
    try:
        kb = drawing_kb.build_kb(str(ga_pdf))
    except Exception as e:  # noqa: BLE001 - surfaced to the user as an input problem
        raise InspectionError(f"Could not read the drawing set ({type(e).__name__}). Upload the vector PDF exported "
                              f"from CAD.") from e
    if not kb.get("views"):
        raise InspectionError("No general-arrangement view with device tags was found in this drawing set, so there is "
                              "nothing to check the photo against. Upload the cabinet's GA drawing (vector PDF).")
    n_tags = sum(len(v["tags"]) for v in kb["views"].values())
    t_parse = clock()
    stage("parse", "done", cabinet=kb["cabinet"], views=list(kb["views"]), devices=n_tags, terminals=0,
          rails=len(kb.get("groups") or []), wires=len(kb.get("connections") or []),
          vocabulary=len(kb.get("vocabulary") or []), kb_cache=kb["stats"].get("cache"))
    checks_on = real_enabled(enabled)
    agent_st = _agent_status(agent)
    out = []
    for k, src in enumerate(photos):
        tp = time.perf_counter()
        try:
            photo = src if isinstance(src, dict) else load_photo(src)
        except Exception as e:  # noqa: BLE001
            raise InspectionError("Could not read the cabinet photo. Upload a JPG or PNG image.") from e
        if names and k < len(names) and names[k]:
            photo["name"] = names[k]
        multi = {"photo": k + 1, "photos": len(photos)} if len(photos) > 1 else {}
        stage("ocr", "start", **multi)
        info = {}
        tokens = ocr.read_photo(photo, mode=ocr_mode, info=info)
        t_ocr = round(time.perf_counter() - tp, 3)
        stage("ocr", "done", tokens=len(tokens), seconds=info.get("seconds"), cached=bool(info.get("cached")),
              ocr_engine=ocr.ENGINE, **multi)

        t = time.perf_counter()
        stage("register", "start", **multi)
        reg = register(tokens, kb, photo)
        ctx = Context(kb, str(ga_pdf), photo, tokens, reg, wires=wires, checklist=checklist,
                      workers=max(1, min(8, ocr.WORKERS)))
        t_reg = round(time.perf_counter() - t, 3)
        stage("register", "done", anchors=reg["anchors"], inliers=reg["inliers"],
              outliers=sorted({o["tag"] for f in reg["fits"] for o in f["outliers"]}, key=tag_sort_key),
              refined=any(f["model"] == "homography" for f in reg["fits"]), rotated=0, localised=reg["localised"],
              views=[f["view"] for f in reg["fits"]], in_view=len(reg["in_view"]), hint=reg["hint"], **multi)

        findings, t_checks = run_checks(ctx, checks_on, on_event=lambda ev: emit(dict(ev, engine="real", **multi)),
                                        clock=clock)
        t = time.perf_counter()
        cands = [f for f in findings if f["status"] in ("CANDIDATE_FAULT", "UNCERTAIN")]
        stage("agent", "start", candidates=len(cands), enabled=bool(agent_st.get("enabled")),
              backend=agent_st.get("backend"), **multi)
        agent_out = {"enabled": False, "decisions": {}, "calls": 0, "cost_usd": 0.0,
                     "summary": f"agent off: {agent_st.get('reason')}", "backend": None, "model": None}
        if cands and agent is not False and agent_st.get("enabled"):
            from agent import SimpleContext, verify
            actx = SimpleContext(photo, kb, str(ga_pdf), findings, reg, ocr_region=ctx.ocr_region)

            def agent_event(ev):
                emit(dict(stage="agent", status="progress", t=clock(), engine="real", **{k: v for k, v in ev.items()
                                                                                       if k not in ("stage", "status", "t")}))
            agent_out = verify(findings, actx, run_dir=run_dir, on_event=agent_event,
                               backend=None if agent in (None, True) else agent)
        elif not cands:
            agent_out["summary"] = "no candidate findings to verify"
            agent_out["enabled"] = bool(agent_st.get("enabled"))
        agent_on = bool(agent_out.get("enabled"))
        t_agent = round(time.perf_counter() - t, 3)
        stage("agent", "done", calls=agent_out.get("calls", 0), cost_usd=agent_out.get("cost_usd", 0.0),
              summary=agent_out.get("summary"), enabled=agent_on, backend=agent_out.get("backend"),
              model=agent_out.get("model"), **multi)

        items = consensus.decide(findings, agent_out.get("decisions") or {}, agent_on)
        c = consensus.counts(items)
        stage("consensus", "done", counts=c, root_cause_skips=c["SKIP"], **multi)
        W, H = photo["size"]
        rep = {
            "engine_kind": "real", "engine": config.VERSION, "photo": photo.get("name") or f"photo_{k + 1}",
            "results": items, "counts": c, "registration": _registration(reg, ctx),
            "H": [[R, 0, 0], [0, R, 0], [0, 0, 1]], "photo_size": [W, H], "rect_px_per_mm": R, "rectified": False,
            "ga": {"cabinet": kb["cabinet"], "size": [W, H], "devices": _devices(reg, ctx), "terminals": [],
                   "rails": []},
            "wires": [], "enabled": checks_on,
            "timing": {"parse": t_parse if k == 0 else 0.0, "ocr": t_ocr, "register": t_reg, "checks": t_checks,
                       "agent": t_agent, "total": round(time.perf_counter() - tp + (t_parse if k == 0 else 0), 3)},
            "orientation": 0, "warnings": _warnings(reg, photo, agent_st, items, kb),
            "coverage": consensus.coverage(items, kb), "views": [f["view"] for f in reg["fits"]],
            "kb": {"cabinet": kb["cabinet"], "sha": kb["pdf_sha256"], "version": kb["kb_version"],
                   "name": kb.get("pdf_name"), "views": list(kb["views"]), "tags": n_tags},
            "agent": {k2: agent_out.get(k2) for k2 in ("enabled", "backend", "model", "fast_model", "calls", "cost_usd",
                                                       "summary", "overview")} | {"reason": agent_st.get("reason")},
            "ocr": {"engine": ocr.ENGINE, "tokens": len(tokens), "seconds": info.get("seconds"),
                    "cached": bool(info.get("cached")), "mode": info.get("mode") or ocr.MODE},
            "quality": photo.get("quality"),
            "photo_meta": {"sha": photo["sha"], "size": [W, H], "exif_orientation": photo.get("exif_orientation"),
                           "name": photo.get("name")},
            "notes": [n for n in (ctx.facts.get("colour_note"),) if n],
        }
        out.append((rep, ctx))
    return out


def session(reports, kb_or_pdf):
    """Cabinet-level summary over several photos (coverage across photos, per-item best evidence)."""
    kb = kb_or_pdf if isinstance(kb_or_pdf, dict) else drawing_kb.build_kb(str(kb_or_pdf))
    return consensus.merge_photos(reports, kb)


def is_real_drawing(pdf):
    return bool(pdf) and Path(pdf).suffix.lower() == ".pdf" and drawing_kb.is_real_drawing(str(pdf))
