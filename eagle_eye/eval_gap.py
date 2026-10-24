"""Fault Forge, synthetic vs real: one scorer for both kinds of photo, so the two can be compared.

    synthetic   generated cabinets with planted faults (render.py), inspected by the demo-cabinet engine; read from
                out/forge/results.json (written by ``python eval_forge.py 50 200``)
    real        photos of Emerson's cabinet with faults planted by forge_real.py (data/emerson/forged/), inspected by
                the real-cabinet engine (deterministic, no AI verifier unless ``--agent env``)

Both sides are scored the same way. A planted fault is FAIL when one of its expected items ends FAIL, REVIEW when one
ends REVIEW and none FAIL, otherwise missed. A false FAIL is a FAIL on any other item (on real photos, one that is not a
listed drawing deviation). Faults are grouped into the categories both forges plant (missing, wrong label, swap);
ferrule and wire-colour faults are planted in generated cabinets only so far.

    python eval_gap.py [--no-real] [--agent off|env] [--data DIR] [--out DIR]

Writes out/real_eval/gap.json (git-ignored: derived from Emerson's photos). GET /api/forge/gap serves it, or the
synthetic side alone when no real evaluation has been run on this machine.
"""
import argparse
import datetime
import json
import time
from pathlib import Path

import config

REAL = config.BASE.parent / "data" / "emerson"
SYNTH_RESULTS = config.OUT / "forge" / "results.json"
GAP_FILES = (config.DATA / "real_eval" / "gap.json", config.OUT / "real_eval" / "gap.json")
SCHEMA = "eagle-eye-gap/1"

CATEGORIES = [("missing", "Missing part or label"), ("wrong_label", "Wrong label"), ("swap", "Swapped devices"),
              ("ferrule", "Wire ferrule"), ("colour", "Wire colour")]
SYNTH_CATEGORY = {"missing_component": "missing", "missing_label": "missing", "wrong_label": "wrong_label",
                  "swap_breakers": "swap", "missing_ferrule": "ferrule", "wrong_ferrule": "ferrule",
                  "wrong_colour": "colour"}
REAL_CATEGORY = {"missing": "missing", "wrong": "wrong_label", "swap": "swap"}
OUTCOMES = ("FAIL", "REVIEW", "missed")
RATES = ("fail_rate", "flag_rate", "false_fail_rate", "review_rate", "not_in_view_rate")
NO_REAL = ("No real-photo evaluation on this engine yet. Put Emerson's drawing set and photos in data/emerson/, then run "
           "python forge_real.py and python eval_gap.py.")


def outcome(results):
    """FAIL | REVIEW | missed for one planted fault, from the results of its expected items."""
    results = set(results)
    return "FAIL" if "FAIL" in results else "REVIEW" if "REVIEW" in results else "missed"


def _ratio(a, b):
    return round(a / b, 4) if b else 0.0


def summarize(rows):
    """One side's summary from per-photo rows {"faults": [{"category", "outcome"}], "false_fail", "reviews",
    "judged" (correct items judged), "not_in_view", "items", "seconds"}."""
    cats = {c: {"planted": 0, "FAIL": 0, "REVIEW": 0, "missed": 0} for c, _ in CATEGORIES}
    for r in rows:
        for f in r["faults"]:
            c = cats.setdefault(f["category"], {"planted": 0, "FAIL": 0, "REVIEW": 0, "missed": 0})
            c["planted"] += 1
            c[f["outcome"]] += 1
    for c in cats.values():
        c["fail_rate"] = _ratio(c["FAIL"], c["planted"])
        c["flag_rate"] = _ratio(c["FAIL"] + c["REVIEW"], c["planted"])
    planted = sum(c["planted"] for c in cats.values())
    tot = {k: sum(c[k] for c in cats.values()) for k in OUTCOMES}
    judged = sum(r["judged"] for r in rows)
    false_fail = sum(r["false_fail"] for r in rows)
    secs = [r["seconds"] for r in rows if r.get("seconds")]
    return {"photos": len(rows), "planted": planted, **tot,
            "fail_rate": _ratio(tot["FAIL"], planted), "flag_rate": _ratio(tot["FAIL"] + tot["REVIEW"], planted),
            "false_fail": false_fail, "false_fail_rate": _ratio(false_fail, judged),
            "review_rate": _ratio(sum(r["reviews"] for r in rows), judged),
            "not_in_view_rate": _ratio(sum(r["not_in_view"] for r in rows), sum(r["items"] for r in rows)),
            "judged": judged, "sec_per_photo": round(sum(secs) / len(secs), 2) if secs else None, "categories": cats}


def synthetic_rows(path=SYNTH_RESULTS):
    """Per-cabinet rows of the saved Fault Forge self-test (eval_forge.py results.json)."""
    from render import expected_item
    out = []
    for r in json.loads(Path(path).read_text(encoding="utf-8")):
        faults = [{"category": SYNTH_CATEGORY.get(f["type"], f["type"]), "type": f["type"],
                   "outcome": outcome([r["found"].get(expected_item(f))])} for f in r["faults"]]
        out.append({"photo": f"cabinet #{r['i']}", "faults": faults, "false_fail": len(r["false_alarms"]),
                    "reviews": len(r["reviews"]), "judged": r["n_items"] - r["n_skip"] - len(r["caught"]),
                    "not_in_view": 0, "items": r["n_items"], "seconds": r.get("sec")})
    return out


def real_rows(data=REAL, agent="off", on_photo=None):
    """Per-photo rows of the real-cabinet engine on the forged photos (forge_real.py); None when there are none."""
    data = Path(data)
    key_file = data / "forged" / "answer_key.json"
    if not key_file.exists():
        return None
    import pipeline
    key = json.loads(key_file.read_text(encoding="utf-8"))
    gt_file = data / "ground_truth.json"
    gt = json.loads(gt_file.read_text(encoding="utf-8")) if gt_file.exists() else {}
    pdf = data / key["drawing"]
    out = []
    for name, fault in key["variants"].items():
        t0 = time.perf_counter()
        [(rep, _ctx)] = pipeline.inspect_real([str(key_file.parent / name)], str(pdf),
                                              agent=False if agent == "off" else None, names=[name])
        devs = {d["target"] for d in ((gt.get("photos") or {}).get(fault.get("source")) or {}).get("deviations", [])}
        items = rep["results"]
        by_id = {r["id"]: r for r in items}
        expect = set(fault["expect"]) | {f"MISS-{t}" for t in fault["tags"]} | {f"LBL-{t}" for t in fault["tags"]}
        other = [r for r in items if r["id"] not in expect and r["target"] not in devs
                 and not any(r["id"].endswith(d) for d in devs)]
        row = {"photo": name, "source": fault.get("source"),
               "faults": [{"category": REAL_CATEGORY.get(fault["type"], fault["type"]), "type": fault["type"],
                           "text": fault.get("text"),
                           "outcome": outcome(by_id[e]["result"] for e in fault["expect"] if e in by_id)}],
               "false_fail": sum(r["result"] == "FAIL" for r in other),
               "reviews": sum(r["result"] == "REVIEW" for r in other),
               "judged": sum(r["result"] not in ("NOT_IN_VIEW", "SKIP") for r in other),
               "not_in_view": sum(r["result"] == "NOT_IN_VIEW" for r in items), "items": len(items),
               "seconds": round(time.perf_counter() - t0, 1)}
        out.append(row)
        if on_photo:
            on_photo(row)
    return out


def build(real=None, real_reason=None, agent="off", synth_path=SYNTH_RESULTS):
    """The comparison report (what gap.json holds and the console shows)."""
    syn_rows = synthetic_rows(synth_path) if Path(synth_path).exists() else None
    syn = summarize(syn_rows) if syn_rows else None
    rea = summarize(real) if real else None
    if syn:
        ids = [int(r["photo"].split("#")[1]) for r in syn_rows]
        syn.update(engine="demo-cabinet engine", source=f"generated cabinets #{min(ids)}-#{max(ids)} (Fault Forge "
                   f"self-test)", selection="faults planted anywhere on the cabinet")
    if rea:
        rea.update(engine="real-cabinet engine", agent=agent, source="photos of Emerson's cabinet 13GE03331, faults "
                   "planted by forge_real.py", selection="faults planted only at labels the engine read with certainty")
    return {"schema": SCHEMA, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "engine": config.VERSION, "synthetic": syn, "real": rea,
            "real_reason": None if rea else (real_reason or NO_REAL),
            "gap": {k: round(rea[k] - syn[k], 4) for k in RATES} if syn and rea else None,
            "categories": [{"id": c, "label": label, "synthetic": syn["categories"].get(c) if syn else None,
                            "real": rea["categories"].get(c) if rea else None} for c, label in CATEGORIES],
            "real_rows": [{"photo": r["photo"], "faults": r["faults"], "false_fail": r["false_fail"]}
                          for r in real] if real else []}


def load():
    """Latest report for the console: the saved one (eval_gap.py), else the synthetic side alone."""
    for p in GAP_FILES:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return build()


def table(rep):
    """Plain-text comparison for the terminal."""
    s, r = rep["synthetic"], rep["real"]

    def cell(side, key, pct=True):
        if not side:
            return "-"
        v = side[key]
        return "-" if v is None else f"{v * 100:.1f}%" if pct else str(v)

    def split(c):
        return f"{c['FAIL']}/{c['REVIEW']}/{c['missed']} of {c['planted']}" if c and c["planted"] else "not planted"

    lines = ["Fault Forge: synthetic vs real", f"{'':26}{'synthetic':>20}{'real':>20}",
             f"{'photos':26}{cell(s, 'photos', False):>20}{cell(r, 'photos', False):>20}",
             f"{'planted faults':26}{cell(s, 'planted', False):>20}{cell(r, 'planted', False):>20}"]
    for key, label in (("fail_rate", "caught as FAIL"), ("flag_rate", "flagged (FAIL or REVIEW)"),
                       ("false_fail_rate", "false FAIL rate"), ("review_rate", "REVIEW rate"),
                       ("not_in_view_rate", "not in view")):
        lines.append(f"{label:26}{cell(s, key):>20}{cell(r, key):>20}")
    lines.append(f"{'seconds per photo':26}{cell(s, 'sec_per_photo', False):>20}{cell(r, 'sec_per_photo', False):>20}")
    lines.append("by fault type (FAIL/REVIEW/missed)")
    for c in rep["categories"]:
        lines.append(f"  {c['label']:24}{split(c['synthetic']):>20}{split(c['real']):>20}")
    if not r:
        lines.append(rep["real_reason"])
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fault Forge: synthetic vs real evaluation")
    ap.add_argument("--data", default=str(REAL), help="folder with the drawing set, photos and forged/ (forge_real.py)")
    ap.add_argument("--agent", choices=("off", "env"), default="off",
                    help="off: deterministic engine only; env: the AI verifier as configured in the environment")
    ap.add_argument("--no-real", action="store_true", help="synthetic side only")
    ap.add_argument("--out", default=str(config.OUT / "real_eval"))
    a = ap.parse_args(argv)
    real, reason = None, None
    if not a.no_real:
        def show(row):
            f = row["faults"][0]
            print(f"{row['photo']}: {f['outcome']:<6} {f.get('text') or f['type']} · false FAIL {row['false_fail']} · "
                  f"{row['seconds']} s", flush=True)
        real = real_rows(a.data, a.agent, on_photo=show)
        if real is None:
            reason = f"No forged photos in {Path(a.data) / 'forged'}: run python forge_real.py first."
    rep = build(real, reason, a.agent)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "gap.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(table(rep))
    print(f"written {out / 'gap.json'}")
    return rep


if __name__ == "__main__":
    main()
