"""FAULT FORGE self-test: random cabinets, random planted faults, random camera conditions."""
import json, os, sys, time, numpy as np
from multiprocessing import Pool
from render import render, random_faults, expected_item as expected_items
from inspector import inspect
import config
GA, WL = str(config.DEMO_GA), str(config.DEMO_WIRES)
FORGE = config.OUT / "forge"; FORGE.mkdir(parents=True, exist_ok=True)

def one(i):
    rng = np.random.default_rng(1000 + i)
    faults = random_faults(rng) if i % 5 else []          # every 5th cabinet is fault-free
    strength = float(rng.uniform(0.8, 1.4))
    p, _ = render(faults, seed=5000 + i, strength=strength)
    path = str(FORGE / f"cab_{i:03d}.jpg"); p.save(path, quality=90)
    t = time.perf_counter()
    rep, _ = inspect(path, GA, WL)
    sec = time.perf_counter() - t
    res = {r["id"]: r["result"] for r in rep["results"]}
    exp = {expected_items(f): f["type"] for f in faults}
    caught = {k: res.get(k) == "FAIL" for k in exp}
    fa = [k for k, v in res.items() if v == "FAIL" and k not in exp]
    rv = [k for k, v in res.items() if v == "REVIEW" and k not in exp]
    return dict(i=i, engine_version=config.VERSION, strength=strength, faults=faults, caught=caught, false_alarms=fa, reviews=rv,
                n_items=len(res), n_skip=sum(v == "SKIP" for v in res.values()), anchors=rep["registration"]["anchors"],
                found={k: res.get(k) for k in exp}, sec=round(sec, 2))

def summarize(out):
    nf = sum(len(r["caught"]) for r in out); nc = sum(sum(r["caught"].values()) for r in out)
    correct_items = sum(r["n_items"] - r["n_skip"] - len(r["caught"]) for r in out)
    fa = sum(len(r["false_alarms"]) for r in out); rv = sum(len(r["reviews"]) for r in out)
    by = {}
    for r in out:
        for f in r["faults"]:
            e = by.setdefault(f["type"], [0, 0]); e[1] += 1
            e[0] += r["caught"][expected_items(f)]
    secs = [r["sec"] for r in out if r.get("sec")]
    outcomes = [value for row in out for value in row.get("found", {}).values()]
    version = config.VERSION if out and all(r.get("engine_version") == config.VERSION for r in out) else None
    return dict(engine_version=version, confirmed=sum(v == "FAIL" for v in outcomes),
                referred=sum(v == "REVIEW" for v in outcomes), incorrect_pass=sum(v == "PASS" for v in outcomes),
                unassessed=sum(v not in ("FAIL", "REVIEW", "PASS") for v in outcomes),
                cabinets=len(out), planted=nf, caught=nc, recall=nc / max(nf, 1), correct_items=correct_items,
                false_alarms=fa, false_alarm_rate=fa / max(correct_items, 1), reviews=rv, review_rate=rv / max(correct_items, 1),
                per_type=by, clean_cabinets_zero_fail=sum(1 for r in out if not r["faults"] and not r["false_alarms"]),
                clean_cabinets=sum(1 for r in out if not r["faults"]),
                sec_per_cabinet=round(sum(secs) / len(secs), 2) if secs else None, cpu_cores=os.cpu_count())

if __name__ == "__main__":
    if sys.argv[1:] == ["--summarize"]:          # recompute summary.json from a saved results.json
        out = json.load(open(FORGE / "results.json"))
    else:
        N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
        S = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        # inspect() already spreads OCR over every core, so one cabinet at a time is the fastest setting
        with Pool(int(os.environ.get("FORGE_PROCS", 1))) as pool:
            out = []
            for r in pool.imap_unordered(one, range(S, S + N)):
                out.append(r); print(r["i"], "faults", len(r["faults"]), "caught", sum(r["caught"].values()), "FA", r["false_alarms"], "RV", r["reviews"], flush=True)
        out.sort(key=lambda r: r["i"])
        json.dump(out, open(FORGE / "results.json", "w"), indent=1)
    summary = summarize(out)
    json.dump(summary, open(FORGE / "summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))
