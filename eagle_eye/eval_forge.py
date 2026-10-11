"""FAULT FORGE self-test: random cabinets, random planted faults, random camera conditions."""
import json, os, sys, numpy as np
from multiprocessing import Pool
from render import render, random_faults
from inspector import inspect
GA, WL = "inputs/GA_EE-DEMO-01.pdf", "inputs/WireList_EE-DEMO-01.xlsx"
os.makedirs("out/forge", exist_ok=True)

def expected_items(f):
    t = f["type"]
    if t == "missing_component": return f"GA-{f['tag']}"
    if t == "swap_breakers": return "ORD-RAIL-1"
    if t in ("missing_label", "wrong_label"): return f"LBL-{f['tag']}"
    if t in ("missing_ferrule", "wrong_ferrule"): return f"FER-X3:{f['n']}"
    if t == "wrong_colour": return f"COL-X3:{f['n']}"

def one(i):
    rng = np.random.default_rng(1000 + i)
    faults = random_faults(rng) if i % 5 else []          # every 5th cabinet is fault-free
    strength = float(rng.uniform(0.8, 1.4))
    p, _ = render(faults, seed=5000 + i, strength=strength)
    path = f"out/forge/cab_{i:03d}.jpg"; p.save(path, quality=90)
    rep, _ = inspect(path, GA, WL)
    res = {r["id"]: r["result"] for r in rep["results"]}
    exp = {expected_items(f): f["type"] for f in faults}
    caught = {k: res.get(k) == "FAIL" for k in exp}
    fa = [k for k, v in res.items() if v == "FAIL" and k not in exp]
    rv = [k for k, v in res.items() if v == "REVIEW" and k not in exp]
    return dict(i=i, strength=strength, faults=faults, caught=caught, false_alarms=fa, reviews=rv,
                n_items=len(res), n_skip=sum(v == "SKIP" for v in res.values()), anchors=rep["registration"]["anchors"],
                found={k: res.get(k) for k in exp})

if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    S = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    with Pool(2) as pool:
        out = []
        for r in pool.imap_unordered(one, range(S, S + N)):
            out.append(r); print(r["i"], "faults", len(r["faults"]), "caught", sum(r["caught"].values()), "FA", r["false_alarms"], "RV", r["reviews"], flush=True)
    json.dump(out, open("out/forge/results.json", "w"), indent=1)
    nf = sum(len(r["caught"]) for r in out); nc = sum(sum(r["caught"].values()) for r in out)
    correct_items = sum(r["n_items"] - r["n_skip"] - len(r["caught"]) for r in out)
    fa = sum(len(r["false_alarms"]) for r in out); rv = sum(len(r["reviews"]) for r in out)
    by = {}
    for r in out:
        for f in r["faults"]:
            k = f["type"]; e = by.setdefault(k, [0, 0]); e[1] += 1
            from eval_forge import expected_items as ei
            e[0] += r["caught"][ei(f)]
    summary = dict(cabinets=N, planted=nf, caught=nc, recall=nc / max(nf, 1), correct_items=correct_items,
                   false_alarms=fa, false_alarm_rate=fa / correct_items, reviews=rv, review_rate=rv / correct_items,
                   per_type=by, clean_cabinets_zero_fail=sum(1 for r in out if not r["faults"] and not r["false_alarms"]),
                   clean_cabinets=sum(1 for r in out if not r["faults"]))
    json.dump(summary, open("out/forge/summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))
