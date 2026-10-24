"""Showcase cases for the History page: saved inspections that show what the engine does, on clean cabinets and on
cabinets with planted anomalies, each with what was planted, what the engine should conclude and what to look at.

    python showcase.py              # adds the cases to the run store (out/runs/), where History shows them
    python showcase.py --demo-only  # the generated demo cabinet only
    POST /api/showcase              # the same from the console (History -> Load showcase cases)

Demo cabinet (EE-DEMO-01): generated photos with their answer key (sample_photos/, Fault Forge), always available.
Real cabinet (13GE03331): renders of Emerson's GA drawing made by render_real.py, with faults planted by forge_real.py,
in data/emerson_render/ (never committed: the drawing set is for the hackathon only). The renders are drawings with
camera effects, not photographs, and the wire patches pasted into one of them are synthetic; every case says so.

Every case checks its own outcome after it ran (``expect``) and reports a mismatch instead of hiding it.
"""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import config
import service

RENDERS = config.BASE.parent / "data" / "emerson_render"
LABEL = "Showcase · {n:02d} · {title}"


def _case(n, key, title, story, look, planted=(), kind="demo", source=""):
    return dict(case=key, n=n, title=title, story=story, look=look, planted=list(planted), kind=kind, source=source)


def _results(meta):
    return {r["id"]: r for r in service.get_report(meta["id"])["results"]}


def _check(meta, expect):
    """Mismatches between a run and its case's expectations (empty when the engine did what the case shows)."""
    res, c, bad = _results(meta), meta["counts"], []
    for iid, ok in (expect.get("items") or {}).items():
        got = (res.get(iid) or {}).get("result")
        if got not in ok:
            bad.append(f"{iid}: {got} (expected {'/'.join(ok)})")
    for key, (lo, hi) in (expect.get("counts") or {}).items():
        if not lo <= c.get(key, 0) <= hi:
            bad.append(f"{key} count {c.get(key, 0)} (expected {lo}-{hi})")
    planted = set(expect.get("planted_items") or ())
    if expect.get("no_false_fail", True):
        extra = [i for i, r in res.items() if r["result"] == "FAIL" and i not in planted and i not in (expect.get("items") or {})]
        if extra:
            bad.append(f"unexpected FAIL: {', '.join(extra)}")
    for fn in expect.get("checks") or ():
        msg = fn(meta, res)
        if msg:
            bad.append(msg)
    return bad


# ------------------------------------------------------------------ demo cabinet (generated, with answer key)
def demo_cases():
    s = {x["id"]: x for x in service.samples()}
    return [
        (_case(1, "demo-clean", "Clean cabinet, every check passes",
               "A generated EE-DEMO-01 cabinet built exactly to its drawing.",
               "The green verdict, 41 PASS with proof crops, and the calibrated photo confidence."),
         dict(sample="02", expect=dict(counts={"FAIL": (0, 0), "REVIEW": (0, 0)}))),
        (_case(2, "demo-four-faults", "Emerson's example: the four faults of the problem statement",
               "The four faults Emerson named, planted in one cabinet.",
               "Four FAILs with expected-vs-found crops; LBL-PS12 is SKIP because its part is missing (one root cause, "
               "reported once).", planted=s["01"]["fault_text"]),
         dict(sample="01", expect=dict(items={"GA-PS12": ["FAIL"], "ORD-RAIL-1": ["FAIL"], "LBL-1CBP03": ["FAIL"],
                                               "FER-X3:3": ["FAIL"], "LBL-PS12": ["SKIP"]}))),
        (_case(3, "demo-ferrule-colour", "Wrong wire ferrule and wrong wire colour",
               "A sleeve printed for another wire, and a black wire where the wire list says blue.",
               "FER-X3:5 and COL-X3:7 FAIL; the colour proof shows the measured swatch after white balance.",
               planted=s["03"]["fault_text"]),
         dict(sample="03", expect=dict(items={"FER-X3:5": ["FAIL"], "COL-X3:7": ["FAIL"]}))),
        (_case(4, "demo-label-breaker", "Mislabelled power supply and a missing breaker",
               "PS11 carries a PS17 label, and breaker CB42's slot on the rail is empty.",
               "LBL-PS11 and GA-CB42 FAIL; LBL-CB42 is SKIP (its part is missing).", planted=s["04"]["fault_text"]),
         dict(sample="04", expect=dict(items={"LBL-PS11": ["FAIL"], "GA-CB42": ["FAIL"], "LBL-CB42": ["SKIP"]}))),
        (_case(5, "demo-recheck", "Re-check after the fix: three closed, one still open",
               "The cabinet of case 2 re-photographed after the technician fixed three of the four faults.",
               "The re-check chain v1 -> v2 in History, CLOSED vs OPEN per issue, and the before/after slider.",
               planted=s["05"]["fault_text"] or ["X3:3 ferrule still missing"]),
         dict(sample="05", parent="demo-four-faults",
              expect=dict(items={"FER-X3:3": ["FAIL"]}, counts={"FAIL": (1, 1)},
                          checks=[lambda m, r: None if (m.get("recheck") or {}).get("CLOSED", 0) >= 3 else
                                  f"re-check closed {(m.get('recheck') or {}).get('CLOSED', 0)} issues (expected 3)"]))),
        (_case(6, "demo-bad-photo", "Bad photo: glare, blur and a colour cast",
               "A cabinet with planted faults photographed with a harsh camera (Fault Forge, strength 1.45).",
               "Zones the photo cannot prove go to REVIEW with a re-photo hint; nothing is FAILed on a guess (no false "
               "FAIL)."),
         dict(forge=dict(seed=302, strength=1.45), expect=dict(counts={"REVIEW": (1, 99)}, forge_clean=True))),
        (_case(7, "demo-hidden-faults", "Hidden faults: three planted at random",
               "Fault Forge planted three faults the engine was not told about; the answer key is attached.",
               "Every planted fault caught, no false alarm; the History card lists what was planted."),
         dict(forge=dict(seed=4242, k=3, strength=1.0), expect=dict(forge_all=True))),
    ]


# ------------------------------------------------------------------ real cabinet (renders of the GA drawing)
def _paste_wires(rgb):
    """Two synthetic wire patches (a ferrule on its wire) inside the front view's drawn area: a brown wire on an AC
    ferrule (allowed by the drawing's legend) and a green-and-yellow wire on another AC ferrule (reserved for earth)."""
    import cv2
    out = rgb.copy()
    for (x, y), (code, text) in (((150, 1520), ("BN", "CB12-2/PS12-L")), ((290, 2700), ("GN/YE", "CB13-2/PS13-L"))):
        h, w = 200, 520
        img = np.full((h, w, 3), 168.0)
        cy, wire = h // 2, 56
        band = np.zeros((wire, w, 3))
        if code == "GN/YE":
            band[: int(0.4 * wire)], band[int(0.4 * wire):] = (240, 208, 30), (24, 138, 62)
        else:
            band[:] = (115, 68, 38)
        shade = (0.78 + 0.22 * np.sqrt(np.clip(1 - np.linspace(-1, 1, wire) ** 2, 0, 1)))[:, None, None]
        img[cy - wire // 2: cy + wire // 2] = band * shade
        font, scale = cv2.FONT_HERSHEY_SIMPLEX, 0.95
        (tw, th), base = cv2.getTextSize(text, font, scale, 2)
        tx = w // 2 - tw // 2
        img[cy - 36: cy + 36, tx - 24: tx + tw + 24] = (245, 245, 240)
        u8 = np.clip(img, 0, 255).astype(np.uint8)
        cv2.putText(u8, text, (tx, cy + th // 2), font, scale, (20, 20, 20), 2, cv2.LINE_AA)
        out[y:y + h, x:x + w] = cv2.GaussianBlur(u8, (3, 3), 0.7)
    return out


def real_cases():
    if not (RENDERS / "render_info.json").exists():
        return []
    key = json.loads((RENDERS / "forged" / "answer_key.json").read_text(encoding="utf-8")) \
        if (RENDERS / "forged" / "answer_key.json").exists() else {"variants": {}}
    v = key.get("variants") or {}
    note = "Render of Emerson's GA drawing with camera effects (no cabinet photos were provided), not a photograph."
    cases = [
        (_case(8, "real-clean", "Real cabinet 13GE03331, front view: every label verified",
               "The front view of Emerson's cabinet straight on. " + note,
               "Every device label read and placed on the GA drawing; Drawing and Anchors layers line up.",
               kind="real", source="front.jpg"),
         dict(image="front.jpg", expect=dict(counts={"FAIL": (0, 0)}))),
    ]
    for n, file, title, look in (
            (9, "front__wrong2.jpg", "Real cabinet: a device carries the wrong label",
             "The label check FAILs with the label as read; the unknown tag is reported once."),
            (10, "rear__swap3.jpg", "Real cabinet: two devices swapped",
             "The order check names the swapped pair; both labels are read where the other one belongs."),
            (11, "right__missing1.jpg", "Real cabinet: a label removed",
             "Absence alone is never a FAIL (a hidden label and a missing part look the same): REVIEW with a "
             "re-photo hint.")):
        if file not in v:
            continue
        f = v[file]
        expect = dict(planted_items=f["expect"])
        if f["type"] in ("wrong", "swap"):
            expect["checks"] = [lambda m, r, ids=tuple(f["expect"]): None if any((r.get(i) or {}).get("result") == "FAIL"
                                                                               for i in ids) else
                                f"no FAIL on {', '.join(ids)}"]
        else:
            expect["checks"] = [lambda m, r, ids=tuple(f["expect"]): None if any((r.get(i) or {}).get("result") in
                                                                               ("FAIL", "REVIEW") for i in ids) else
                                f"{', '.join(ids)} not flagged"]
        cases.append((_case(n, f"real-{f['type']}", title, f["text"].capitalize() + ". " + note, look,
                            planted=[f["text"]], kind="real", source=file),
                      dict(image=f"forged/{file}", expect=expect)))
    cases += [
        (_case(12, "real-angle", "Real cabinet photographed 35 degrees from the left",
               "The front view seen by a camera turned 35 degrees. " + note,
               "The camera angle chip, the drawing laid on through the perspective, and the Straightened view.",
               kind="real", source="front.jpg turned 35 degrees"),
         dict(image="front.jpg", turn=-35, expect=dict(counts={"FAIL": (0, 0)}, checks=[
             lambda m, r: None if 28 <= ((service.run_payload(m["id"])["registration"].get("angle") or {}).get("tilt")
                                          or 0) <= 42 else "camera angle not measured near 35 degrees"]))),
        (_case(13, "real-small-labels", "Real cabinet from further away: small labels",
               "The right view at 60 % size: letters about 7 px high. " + note,
               "Small labels the first read missed are verified by the drawing-guided magnified re-read (Registration "
               "tab); labels too small even then are REVIEW or NOT_IN_VIEW, never guessed.",
               kind="real", source="right.jpg at 60 %"),
         dict(image="right.jpg", scale=0.6, expect=dict(counts={"FAIL": (0, 0), "PASS": (40, 999)}))),
        (_case(14, "real-wire-colour", "Real cabinet: green-and-yellow wire on an AC circuit",
               "Two synthetic wire patches pasted into the front view: a brown wire on ferrule CB12-2/PS12-L and a "
               "green-and-yellow wire on CB13-2/PS13-L, both AC mains wires in the drawing's schematics. " + note,
               "The Wire colour rule card (the drawing's own legend), COL-CB12-2/PS12-L PASS, and "
               "COL-CB13-2/PS13-L in REVIEW: green-and-yellow is reserved for protective earth.",
               planted=["green-and-yellow wire on AC ferrule CB13-2/PS13-L (synthetic patch)"], kind="real",
               source="front.jpg + synthetic wire patches"),
         dict(image="front.jpg", wires=True, expect=dict(items={"COL-CB12-2/PS12-L": ["PASS"],
                                                                "COL-CB13-2/PS13-L": ["REVIEW"]},
                                                         counts={"FAIL": (0, 0)}))),
    ]
    return cases


# ------------------------------------------------------------------ building
def _real_image(spec, tmp):
    """The case's image file: a render, a forged render, or one made from a render (turned, scaled, wires pasted)."""
    src = RENDERS / spec["image"]
    if not (spec.get("turn") or spec.get("scale") or spec.get("wires")):
        return src
    import cv2
    rgb = np.asarray(Image.open(src).convert("RGB"))
    if spec.get("wires"):
        rgb = _paste_wires(rgb)
    if spec.get("scale"):
        rgb = cv2.resize(rgb, None, fx=spec["scale"], fy=spec["scale"], interpolation=cv2.INTER_AREA)
    if spec.get("turn"):
        import eval_angle
        rgb, _ = eval_angle.turn(rgb, spec["turn"])
    # lossless: JPEG would smear letters of a few pixels and change what can be read
    out = Path(tmp) / f"{spec['image'].replace('/', '_')}_{spec.get('turn', 0)}_{spec.get('scale', 1)}_{bool(spec.get('wires'))}.png"
    Image.fromarray(rgb).save(out)
    return out


def build(real=True, on_event=None, on_case=None):
    """Run every case; returns [{"case", "run", "label", "ok", "problems"}]. Real-cabinet cases need data/emerson_render."""
    emit = on_event or (lambda ev: None)
    cases = demo_cases() + (real_cases() if real else [])
    done, report = {}, []
    tmp = Path(tempfile.mkdtemp(prefix="ee_showcase_"))
    try:
        for case, spec in cases:
            label = LABEL.format(n=case["n"], title=case["title"])
            emit(dict(stage="showcase", status="start", case=case["case"], index=len(report) + 1, count=len(cases), t=0))
            if "sample" in spec:
                s = next(x for x in service.samples() if x["id"] == spec["sample"])
                meta = service.run_inspection(service.sample_path(spec["sample"]), label=label, source="sample",
                                              photo_name=s["file"], parent=done.get(spec.get("parent")),
                                              on_event=on_event, showcase=case)
            elif "forge" in spec:
                f = spec["forge"]
                meta = service.run_forge(k=f.get("k"), strength=f["strength"], seed=f["seed"], on_event=on_event,
                                         showcase=case)
                meta = _relabel(meta, label)
            else:
                pdf = RENDERS / json.loads((RENDERS / "render_info.json").read_text(encoding="utf-8")).get(
                    "drawing", "Sanitized_Cabinet_Drawing.pdf")
                meta = service.run_inspection(_real_image(spec, tmp), ga=pdf, label=label, source="upload",
                                              photo_name=case["source"], engine="real", on_event=on_event,
                                              showcase=case)
            done[case["case"]] = meta["id"]
            exp = dict(spec.get("expect") or {})
            fs = meta.get("forge") or {}
            if fs:                                    # the planted faults' own items may FAIL
                exp["planted_items"] = [p["item"] for p in fs["score"]["planted"]]
            problems = _check(meta, exp)
            if exp.get("forge_clean") and fs.get("score", {}).get("false_alarms"):
                problems.append(f"false alarms: {fs['score']['false_alarms']}")
            if exp.get("forge_all") and fs.get("score", {}).get("caught") != fs.get("score", {}).get("n_planted"):
                problems.append(f"caught {fs['score']['caught']} of {fs['score']['n_planted']} planted faults")
            row = dict(case=case["case"], run=meta["id"], label=label, ok=not problems, problems=problems,
                       counts=meta["counts"])
            report.append(row)
            if on_case:
                on_case(row)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def _relabel(meta, label):
    """Fault Forge runs are labelled by their seed: a showcase run keeps the case title, and lists the faults the
    forge planted (its answer key) as the case's planted anomalies."""
    planted = [p["text"] for p in ((meta.get("forge") or {}).get("score") or {}).get("planted") or []]
    meta = dict(meta, label=label, showcase=dict(meta["showcase"], planted=planted or meta["showcase"]["planted"]))
    service.write_json(service.run_dir(meta["id"]) / "meta.json", meta)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add the showcase cases to the run store (History)")
    ap.add_argument("--demo-only", action="store_true", help="skip the real-cabinet cases")
    a = ap.parse_args(argv)
    if not a.demo_only and not real_cases():
        print(f"no renders in {RENDERS}: real-cabinet cases skipped (python render_real.py, python forge_real.py)")
    show = lambda r: print(f"{'ok ' if r['ok'] else 'BAD'} {r['label']:<78} {r['counts']}" +  # noqa: E731
                           ("".join(f"\n      ! {p}" for p in r["problems"])), flush=True)
    rows = build(real=not a.demo_only, on_case=show)
    bad = [r for r in rows if not r["ok"]]
    print(f"\n{len(rows) - len(bad)} of {len(rows)} cases behaved as expected" + (f"; check {len(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
