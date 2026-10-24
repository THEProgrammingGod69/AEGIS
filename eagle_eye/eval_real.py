"""Phase 8 - evaluation of the real-cabinet engine on real photos (hand-made ground truth) and forged variants.

Real photos (data/emerson/ground_truth.json):
    verified     visible labels whose item ended PASS (the engine read and placed them)
    false FAIL   FAIL on an item that is not a listed drawing deviation (must be 0)
    deviations   real drawing-vs-cabinet differences the engine flagged (FAIL or REVIEW)
    REVIEW rate  REVIEW / items judged in view
Forged photos (data/emerson/forged/answer_key.json, made by forge_real.py):
    caught       planted faults whose expected item ended FAIL or REVIEW
    false FAIL   FAIL on any other item that is not a drawing deviation

    python eval_real.py [--agent off|env] [--strong-alone] [--forged] [--out DIR]

``--strong-alone`` evaluates the on-prem mode (EAGLE_FAIL_WITHOUT_AGENT=1: strong deterministic candidates FAIL
without the agent). Results go to out/real_eval/ (git-ignored).
"""
import argparse
import json
import os
import time
from pathlib import Path

import config

REAL = config.BASE.parent / "data" / "emerson"


def _flagged(r):
    return r["result"] in ("FAIL", "REVIEW")


def _fault_outcome(items):
    """Distinguish a confirmed defect, a referral and an incorrect clearance.

    Out-of-view, absent and entirely suppressed checks are unassessed, never successful detections.
    This is an evaluation classification, not a cabinet shipping approval.
    """
    states = {r["result"] for r in items}
    if "FAIL" in states:
        return "confirmed"
    if "REVIEW" in states:
        return "review"
    if "PASS" in states and not states.intersection({"NOT_IN_VIEW", "SKIP"}):
        return "incorrect_pass"
    return "unassessed"


def _targets(items, tag):
    """Items about an exact annotated target; text suffixes are not component identity."""
    return [r for r in items if r["target"] == tag or r["id"] in (f"MISS-{tag}", f"LBL-{tag}", f"UNK-{tag}")]


def score_real(items, gt):
    devs = {d["target"] for d in gt.get("deviations", [])}
    visible, occluded = set(gt.get("visible", [])), set(gt.get("occluded", []))
    by_id = {r["id"]: r for r in items}
    # Presence alone does not verify that a label was read correctly.
    verified = sorted(t for t in visible if by_id.get(f"LBL-{t}", {}).get("result") == "PASS")
    missed = sorted(visible - set(verified))
    false_fail = [r["id"] for r in items if r["result"] == "FAIL"
                  and not any(_targets([r], d) for d in devs)]
    dev_flagged = sorted(d for d in devs if any(_flagged(r) for r in _targets(items, d)))
    outcomes = {d: _fault_outcome(_targets(items, d)) for d in devs}
    judged = [r for r in items if r["result"] not in ("NOT_IN_VIEW", "SKIP")]
    reviews = [r["id"] for r in items if r["result"] == "REVIEW"]
    occluded_fail = [r["id"] for r in items if r["result"] == "FAIL" and r["target"] in occluded]
    return {"visible": len(visible), "verified": verified, "missed": missed, "false_fail": false_fail,
            "occluded_fail": occluded_fail, "deviations": sorted(devs), "deviations_flagged": dev_flagged,
            "deviations_confirmed": sorted(d for d, v in outcomes.items() if v == "confirmed"),
            "deviations_review": sorted(d for d, v in outcomes.items() if v == "review"),
            "deviations_incorrect_pass": sorted(d for d, v in outcomes.items() if v == "incorrect_pass"),
            "deviations_unassessed": sorted(d for d, v in outcomes.items() if v == "unassessed"),
            "judged": len(judged), "reviews": reviews,
            "review_rate": round(len(reviews) / len(judged), 3) if judged else 0.0,
            "not_in_view": sum(r["result"] == "NOT_IN_VIEW" for r in items)}


def score_forged(items, fault, base_gt):
    devs = {d["target"] for d in (base_gt or {}).get("deviations", [])}
    by_id = {r["id"]: r for r in items}
    caught = any(_flagged(by_id[e]) for e in fault["expect"] if e in by_id)
    outcome = _fault_outcome([by_id[e] for e in fault["expect"] if e in by_id])
    exp = set(fault["expect"]) | {f"MISS-{t}" for t in fault["tags"]} | {f"LBL-{t}" for t in fault["tags"]}
    false_fail = [r["id"] for r in items if r["result"] == "FAIL" and r["id"] not in exp
                  and not any(_targets([r], d) for d in devs)]
    return {"caught": caught, "outcome": outcome, "confirmed": outcome == "confirmed",
            "referred": outcome == "review", "incorrect_pass": outcome == "incorrect_pass",
            "unassessed": outcome == "unassessed", "false_fail": false_fail,
            "results": {e: by_id[e]["result"] for e in fault["expect"] if e in by_id}}


def run(paths, pdf, agent):
    import pipeline
    out = []
    for p in paths:
        t = time.perf_counter()
        [(rep, _ctx)] = pipeline.inspect_real([str(p)], str(pdf), agent=agent, names=[Path(p).name])
        out.append((Path(p).name, rep, round(time.perf_counter() - t, 1)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate the real-cabinet engine")
    ap.add_argument("--data", default=str(REAL))
    ap.add_argument("--agent", choices=("off", "env"), default="off",
                    help="off: deterministic engine only; env: the agent as configured in the environment")
    ap.add_argument("--strong-alone", action="store_true", help="EAGLE_FAIL_WITHOUT_AGENT=1 (on-prem mode)")
    ap.add_argument("--forged", action="store_true", help="also score data/emerson/forged/ (python forge_real.py)")
    ap.add_argument("--out", default=str(config.OUT / "real_eval"))
    a = ap.parse_args(argv)
    if a.strong_alone:
        os.environ["EAGLE_FAIL_WITHOUT_AGENT"] = "1"
    data = Path(a.data)
    gt = json.loads((data / "ground_truth.json").read_text(encoding="utf-8"))
    pdf = data / gt["drawing"]
    agent = False if a.agent == "off" else None
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, summary = [], {"schema": "eagle-eye-real-evaluation/2", "engine_version": config.VERSION,
                         "mode": f"agent={a.agent}" + (" strong-alone" if a.strong_alone else ""), "photos": {}}
    cabinets = set()
    for name, rep, sec in run([data / n for n in gt["photos"]], pdf, agent):
        if rep.get("ga", {}).get("cabinet"):
            cabinets.add(rep["ga"]["cabinet"])
        s = score_real(rep["results"], gt["photos"][name])
        s.update(seconds=sec, counts=rep["counts"], coverage=rep["coverage"], views=rep["views"],
                 localised=rep["registration"]["localised"])
        summary["photos"][name] = s
        rows.append(dict(photo=name, items=[{k: r[k] for k in ("id", "result", "found", "evidence", "rule")}
                                            for r in rep["results"]]))
        print(f"{name}: {len(s['verified'])}/{s['visible']} visible verified · false FAIL {len(s['false_fail'])} · "
              f"deviations {len(s['deviations_flagged'])}/{len(s['deviations'])} · REVIEW {len(s['reviews'])} "
              f"({s['review_rate']:.0%} of {s['judged']} judged) · {s['not_in_view']} not in view · {sec}s")
        if s["missed"]:
            print(f"    not verified: {', '.join(s['missed'])}")
        if s["false_fail"]:
            print(f"    FALSE FAIL: {', '.join(s['false_fail'])}")
        if s["reviews"]:
            print(f"    REVIEW: {', '.join(s['reviews'])}")
    summary["cabinets"] = len(cabinets) if cabinets else None
    P = summary["photos"].values()
    summary["total"] = {
        "visible": sum(p["visible"] for p in P), "verified": sum(len(p["verified"]) for p in P),
        "false_fail": sum(len(p["false_fail"]) for p in P),
        "deviations": sum(len(p["deviations"]) for p in P),
        "deviations_flagged": sum(len(p["deviations_flagged"]) for p in P),
        "deviations_confirmed": sum(len(p["deviations_confirmed"]) for p in P),
        "deviations_review": sum(len(p["deviations_review"]) for p in P),
        "deviations_incorrect_pass": sum(len(p["deviations_incorrect_pass"]) for p in P),
        "deviations_unassessed": sum(len(p["deviations_unassessed"]) for p in P),
        "reviews": sum(len(p["reviews"]) for p in P), "judged": sum(p["judged"] for p in P),
        "seconds": round(sum(p["seconds"] for p in P), 1)}
    tt = summary["total"]
    tt["review_rate"] = round(tt["reviews"] / tt["judged"], 3) if tt["judged"] else 0.0
    tt["confirmed_recall"] = tt["deviations_confirmed"] / tt["deviations"] if tt["deviations"] else None
    print(f"TOTAL real photos: {tt['verified']}/{tt['visible']} visible labels verified · {tt['false_fail']} false FAIL · "
          f"{tt['deviations_flagged']}/{tt['deviations']} deviations flagged · REVIEW rate {tt['review_rate']:.1%} · "
          f"{tt['seconds']} s")
    print(f"Strict outcomes: {tt['deviations_confirmed']} confirmed, {tt['deviations_review']} to REVIEW, "
          f"{tt['deviations_incorrect_pass']} incorrectly passed, {tt['deviations_unassessed']} unassessed")

    forged_dir = data / "forged"
    if a.forged and (forged_dir / "answer_key.json").exists():
        key = json.loads((forged_dir / "answer_key.json").read_text(encoding="utf-8"))
        fs = {}
        for name, rep, sec in run([forged_dir / n for n in key["variants"]], pdf, agent):
            fault = key["variants"][name]
            s = score_forged(rep["results"], fault, gt["photos"].get(fault["source"]))
            s.update(seconds=sec, fault=fault["text"])
            fs[name] = s
            print(f"{name}: {'CAUGHT' if s['caught'] else 'missed'} ({fault['text']}) {s['results']} · "
                  f"false FAIL {len(s['false_fail'])}")
        summary["forged"] = {"variants": fs, "planted": len(fs), "caught": sum(s["caught"] for s in fs.values()),
                             "false_fail": sum(len(s["false_fail"]) for s in fs.values()),
                             **{key: sum(s[key] for s in fs.values())
                                for key in ("confirmed", "referred", "incorrect_pass", "unassessed")}}
        print(f"TOTAL forged: {summary['forged']['caught']}/{summary['forged']['planted']} planted faults caught · "
              f"{summary['forged']['false_fail']} false FAIL")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out_dir / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"written {out_dir / 'summary.json'}")
    return summary


if __name__ == "__main__":
    main()
