"""Confidence calibration from Fault Forge runs: when the engine says 90 %, is it right about 90 % of the time?

Every judged item of a Fault Forge image has a known truth: it is faulty when a planted fault makes it so, otherwise
correct. The engine's raw item score (``conf``) is a heuristic that means something different per check and engine
(label-read agreement, part occupancy, OCR confidence, fixed values for some candidates), so this module measures it
against that truth and maps it to an honest probability, separately per engine and verdict:

    PASS    P(the item really is correct)
    FAIL    P(the item really is faulty)
    REVIEW  P(the item really is faulty): the fault likelihood behind a referral (the engine did not decide)

The map is histogram binning on the raw score with Laplace's rule, (right + 1) / (items + 2), so a bin with few items
never claims certainty, made monotonic (pool-adjacent-violators). It is fitted on even-numbered images and scored on odd ones (reliability
curve and expected calibration error, ECE, raw vs calibrated), then refitted on all of them. NOT_IN_VIEW and SKIP items
are not judged and get no confidence.

    python calibration.py [--cabinets 100] [--start 300] [--real DIR] [--reuse]

Data: generated cabinets (demo-cabinet engine) and, when ``--real`` holds forge_real.py output, forged images of a real
cabinet (real-cabinet engine). Writes out/forge/calibration.json and web/src/data/calibration.json (bins and counts
only, committed). ``apply(report)`` adds ``item["confidence"]`` and ``report["confidence"]`` (the per-photo summary).
"""
import argparse
import datetime
import json
import shutil
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import assembly
import config

SCHEMA = "eagle-eye-calibration/1"
CAL_FILE = config.OUT / "forge" / "calibration.json"
WEB_FILE = config.BASE / "web" / "src" / "data" / "calibration.json"
REAL = config.BASE.parent / "data" / "emerson_render"
JUDGED = ("PASS", "FAIL", "REVIEW")
EDGES = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0001]     # raw-score bins (most items score near 1)
PSEUDO = 2.0                                                  # Laplace's rule: (right + 1) / (items + 2)
RECORDS = config.DATA / "cache" / "calibration_records.json"   # judged items of the last collection (--reuse)
ENGINES = {"demo": "Demo-cabinet engine on generated cabinets (synthetic Fault Forge)",
           "real": "Real-cabinet engine on forged images of a real cabinet"}


# what a check measures: the score of a text read and the score of a colour measurement are calibrated separately
MEASURE = {"COLOUR": "colour"}


def measure(check):
    return MEASURE.get(check, "text")


# ------------------------------------------------------------------ data
def _record(engine, image, item, fault):
    return {"engine": engine, "image": image, "id": item["id"], "result": item["result"],
            "raw": min(1.0, max(0.0, float(item.get("conf") or 0.0))), "fault": bool(fault)}


def collect_synthetic(n=100, start=300, on_image=None):
    """Records of every judged item of ``n`` generated cabinets (same generator and seeds scheme as eval_forge.py)."""
    import numpy as np
    from inspector import inspect
    from render import expected_item, random_faults, render
    tmp = Path(tempfile.mkdtemp(prefix="ee-cal-"))
    recs = []
    try:
        for i in range(start, start + n):
            rng = np.random.default_rng(1000 + i)
            faults = random_faults(rng) if i % 5 else []           # every 5th cabinet is fault-free
            photo, _ = render(faults, seed=5000 + i, strength=float(rng.uniform(0.8, 1.4)))
            path = tmp / f"cab_{i}.jpg"
            photo.save(path, quality=90)
            rep, _ = inspect(str(path), str(config.DEMO_GA), str(config.DEMO_WIRES))
            bad = {expected_item(f) for f in faults}
            recs += [_record("demo", i, r, r["id"] in bad) for r in rep["results"] if r["result"] in JUDGED]
            if on_image:
                on_image(f"cabinet #{i}", len(faults))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return recs


def _real_truth(fault):
    """(faulty item ids, ambiguous item ids) of one planted fault of forge_real.py."""
    tags = fault["tags"]
    if fault["type"] == "missing":                   # labels painted out: no label, nothing readable
        bad = {f"MISS-{tags[0]}", f"LBL-{tags[0]}"}
    elif fault["type"] == "wrong":                   # device present, label reprinted: the label is wrong
        bad = {f"LBL-{tags[0]}", f"UNK-{fault.get('wrong')}"}
    else:                                            # swap: the group's order and both labels are wrong
        bad = {f"ORD-{fault.get('group')}"} | {f"LBL-{t}" for t in tags}
    return bad, (set(fault.get("expect") or []) | {f"MISS-{t}" for t in tags}) - bad


def collect_real(data=REAL, on_image=None):
    """Records of the real-cabinet engine on forge_real.py output (clean images + forged variants); [] when absent."""
    data = Path(data)
    key_file = data / "forged" / "answer_key.json"
    if not key_file.exists():
        return []
    import pipeline
    key = json.loads(key_file.read_text(encoding="utf-8"))
    pdf = data / key["drawing"]
    clean = sorted({v["source"] for v in key["variants"].values()})
    jobs = [(data / name, set(), set()) for name in clean if (data / name).exists()]
    jobs += [(key_file.parent / name, *_real_truth(fault)) for name, fault in key["variants"].items()]
    recs = []
    for k, (path, bad, skip) in enumerate(jobs):
        [(rep, _ctx)] = pipeline.inspect_real([str(path)], str(pdf), agent=False, names=[path.name])
        recs += [_record("real", k, r, r["id"] in bad) for r in rep["results"]
                 if r["result"] in JUDGED and r["id"] not in skip]
        if on_image:
            on_image(path.name, len(bad))
    return recs


# ------------------------------------------------------------------ fit
def _correct(rec):
    """The truth the confidence of a verdict is about: correct for PASS, faulty for FAIL and REVIEW."""
    return (not rec["fault"]) if rec["result"] == "PASS" else rec["fault"]


def _bin(raw):
    for lo, hi in zip(EDGES, EDGES[1:]):
        if lo <= raw < hi:
            return lo, hi
    return EDGES[-2], EDGES[-1]


def _pav(bins):
    """Pool adjacent violators: probabilities non-decreasing in the raw score, weighted by bin size."""
    blocks = [[b["p"], b["n"] + PSEUDO, [b]] for b in bins]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            w = blocks[i][1] + blocks[i + 1][1]
            blocks[i] = [(blocks[i][0] * blocks[i][1] + blocks[i + 1][0] * blocks[i + 1][1]) / w, w,
                         blocks[i][2] + blocks[i + 1][2]]
            del blocks[i + 1]
            i = max(0, i - 1)
        else:
            i += 1
    for p, _w, members in blocks:
        for b in members:
            b["p"] = round(p, 4)
    return bins


def fit(recs):
    """{verdict: [bin {lo, hi, n, k, p}]} for one engine's records (only bins that hold items)."""
    maps = {}
    for verdict in JUDGED:
        rs = [r for r in recs if r["result"] == verdict]
        if not rs:
            continue
        cells = {}
        for r in rs:
            c = cells.setdefault(_bin(r["raw"]), [0, 0])
            c[0] += 1
            c[1] += _correct(r)
        bins = [{"lo": lo, "hi": min(hi, 1.0), "n": n, "k": k,
                 "p": (k + PSEUDO / 2) / (n + PSEUDO)} for (lo, hi), (n, k) in sorted(cells.items())]
        maps[verdict] = _pav(bins)
    return maps


def lookup(bins, raw):
    """Calibrated probability of a raw score from one verdict's bins (nearest bin when the score falls in a gap)."""
    if not bins:
        return None
    raw = min(1.0, max(0.0, float(raw or 0.0)))
    for b in bins:
        if b["lo"] <= raw < b["hi"] or (raw >= 1.0 and b["hi"] >= 1.0):
            return b["p"]
    return min(bins, key=lambda b: min(abs(raw - b["lo"]), abs(raw - b["hi"])))["p"]


def reliability(points):
    """Reliability curve [{lo, hi, n, stated, observed}] and ECE of (stated confidence, correct) pairs."""
    cells = {}
    for stated, ok in points:
        c = cells.setdefault(_bin(stated), [0, 0.0, 0])
        c[0] += 1
        c[1] += stated
        c[2] += ok
    curve = [{"lo": lo, "hi": min(hi, 1.0), "n": n, "stated": round(s / n, 4), "observed": round(k / n, 4)}
             for (lo, hi), (n, s, k) in sorted(cells.items())]
    total = sum(c["n"] for c in curve)
    ece = sum(c["n"] / total * abs(c["observed"] - c["stated"]) for c in curve) if total else None
    return curve, (round(ece, 4) if ece is not None else None)


def evaluate(recs):
    """Fit on even images, score PASS/FAIL verdicts of odd images: raw score vs calibrated confidence."""
    train = [r for r in recs if r["image"] % 2 == 0]
    test = [r for r in recs if r["image"] % 2 == 1 and r["result"] in ("PASS", "FAIL")]
    maps = fit(train)
    raw = [(r["raw"], _correct(r)) for r in test]
    cal = [(lookup(maps.get(r["result"]), r["raw"]), _correct(r)) for r in test]
    cal = [(p, ok) for p, ok in cal if p is not None]
    curve_raw, ece_raw = reliability(raw)
    curve_cal, ece_cal = reliability(cal)
    return {"items": len(test), "accuracy": round(sum(ok for _p, ok in raw) / len(raw), 4) if raw else None,
            "ece_raw": ece_raw, "ece_cal": ece_cal, "raw": curve_raw, "cal": curve_cal}


def build(recs_by_engine):
    out = {"schema": SCHEMA, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "engine_version": config.VERSION,
           "method": "histogram binning of the raw item score per engine and verdict with Laplace's rule "
                     "(right + 1) / (items + 2), monotonic (pool-adjacent-violators); fitted on even-numbered images, "
                     "scored on odd ones, then refitted on all",
           "engines": {}}
    for eng, recs in recs_by_engine.items():
        if not recs:
            continue
        reviews = [r for r in recs if r["result"] == "REVIEW"]
        out["engines"][eng] = {
            "label": ENGINES.get(eng, eng), "images": len({r["image"] for r in recs}), "items": len(recs),
            "checks": sorted({assembly.check_of(r["id"]) for r in recs}),
            "measures": sorted({measure(assembly.check_of(r["id"])) for r in recs}),
            "counts": {v: sum(r["result"] == v for r in recs) for v in JUDGED},
            "maps": fit(recs), "heldout": evaluate(recs),
            "review": {"n": len(reviews), "fault_rate": round(sum(r["fault"] for r in reviews) / len(reviews), 4)
                       if reviews else None}}
    return out


# ------------------------------------------------------------------ apply
@lru_cache(maxsize=4)
def _load(path, mtime):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if data.get("schema") == SCHEMA else None
    except (OSError, ValueError):
        return None


def load():
    """The committed calibration (out/forge/calibration.json), or None."""
    try:
        return _load(str(CAL_FILE), CAL_FILE.stat().st_mtime)
    except OSError:
        return None


def summary(items):
    """Per-photo confidence: mean calibrated confidence of its PASS/FAIL verdicts, the expected number of wrong ones
    and the least certain items."""
    dec = [r for r in items if r["result"] in ("PASS", "FAIL") and r.get("confidence") is not None]
    if not dec:
        return None
    low = sorted(dec, key=lambda r: r["confidence"])[:3]
    return {"score": round(sum(r["confidence"] for r in dec) / len(dec), 4), "decided": len(dec),
            "expected_errors": round(sum(1 - r["confidence"] for r in dec), 2),
            "review": sum(r["result"] == "REVIEW" for r in items),
            "lowest": [{"id": r["id"], "result": r["result"], "confidence": r["confidence"]} for r in low]}


def apply(rep, cal=None):
    """Add the calibrated confidence to every judged item and the per-photo summary to the report (in place)."""
    cal = cal or load()
    eng = "real" if rep.get("engine_kind") == "real" else "demo"
    data = ((cal or {}).get("engines") or {}).get(eng) or {}
    maps, measures = data.get("maps"), set(data.get("measures") or ())
    if not maps:
        return rep
    for it in rep.get("results") or []:
        # a kind of measurement the Forge runs never produced (wire colours on the real cabinet) has no calibration
        known = not measures or measure(it.get("check") or assembly.check_of(it["id"])) in measures
        p = lookup(maps.get(it["result"]), it.get("conf")) if it["result"] in JUDGED and known else None
        it["confidence"] = round(p, 4) if p is not None else None
    rep["confidence"] = summary(rep.get("results") or [])
    return rep


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Calibrate the engine's item confidence on Fault Forge runs")
    ap.add_argument("--cabinets", type=int, default=100, help="generated cabinets (demo-cabinet engine)")
    ap.add_argument("--start", type=int, default=300, help="first seed (the self-test uses 200-249)")
    ap.add_argument("--real", default=str(REAL), help="forge_real.py output for the real-cabinet engine")
    ap.add_argument("--reuse", action="store_true", help="refit on the items of the last collection (no engine runs)")
    a = ap.parse_args(argv)
    t = time.perf_counter()
    if a.reuse and RECORDS.exists():
        recs = json.loads(RECORDS.read_text(encoding="utf-8"))
        demo, real = recs["demo"], recs["real"]
        print(f"reusing {len(demo)} + {len(real)} judged items from {RECORDS}")
    else:
        show = lambda name, k: print(f"  {name}: {k} planted fault(s)", flush=True)  # noqa: E731
        print(f"synthetic: {a.cabinets} generated cabinets from seed {a.start}")
        demo = collect_synthetic(a.cabinets, a.start, on_image=show if a.cabinets <= 20 else None)
        print(f"real: forged images in {a.real}")
        real = collect_real(a.real, on_image=show)
        RECORDS.parent.mkdir(parents=True, exist_ok=True)
        RECORDS.write_text(json.dumps({"demo": demo, "real": real}), encoding="utf-8")
    cal = build({"demo": demo, "real": real})
    for path in (CAL_FILE, WEB_FILE):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cal, indent=1), encoding="utf-8")
    for eng, e in cal["engines"].items():
        h = e["heldout"]
        print(f"{eng}: {e['images']} images, {e['items']} judged items {e['counts']}; held-out accuracy "
              f"{h['accuracy']}, ECE raw {h['ece_raw']} -> calibrated {h['ece_cal']}; REVIEW fault rate "
              f"{e['review']['fault_rate']}")
        for v, bins in e["maps"].items():
            print(f"   {v}: " + "  ".join(f"[{b['lo']:.2f},{b['hi']:.2f}) n={b['n']} p={b['p']:.3f}" for b in bins))
    print(f"written {CAL_FILE} and {WEB_FILE} in {time.perf_counter() - t:.0f} s")
    return cal


if __name__ == "__main__":
    main()
