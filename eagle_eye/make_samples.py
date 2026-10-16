"""Build the five demo photos in sample_photos/ plus ANSWER_KEY.txt and manifest.json.

Each photo is rendered by Fault Forge with known planted faults and a fixed camera seed, then inspected
once so the manifest records the outcome the jury should see.   python make_samples.py
"""
import json
import os

import config
from inspector import counts, inspect
from render import render
from spec import wire_list

SAMPLES = [
    dict(file="01_emerson_example_4_faults.jpg", seed=7,
         title="Emerson's example", subtitle="The 4 faults from the problem statement",
         faults=[dict(type="missing_component", tag="PS12"), dict(type="swap_breakers", a="CB43", b="CB44"),
                 dict(type="missing_label", tag="1CBP03"), dict(type="missing_ferrule", n=3)],
         expect="4 FAIL, 1 SKIP, 36 PASS: PS12 missing, CB43 ↔ CB44 swapped, 1CBP03 no label, X3:3 no ferrule"),
    dict(file="02_clean_cabinet_no_faults.jpg", seed=33,
         title="Clean cabinet", subtitle="Built exactly to the drawing",
         faults=[], expect="All 41 PASS, no false alarms"),
    dict(file="03_wrong_ferrule_and_colour.jpg", seed=58,
         title="Ferrule + colour", subtitle="Wrong sleeve and wrong wire colour",
         faults=[dict(type="wrong_ferrule", n=5, text=wire_list()[5]["ferrule"]),
                 dict(type="wrong_colour", n=7, colour="BK")],
         expect="X3:5 wrong ferrule (reads X3-6/PS11-), X3:7 black wire instead of blue"),
    dict(file="04_wrong_label_and_missing_breaker.jpg", seed=91,
         title="Label + missing breaker", subtitle="Mislabelled PSU and an empty rail slot",
         faults=[dict(type="wrong_label", tag="PS11", text="PS17"), dict(type="missing_component", tag="CB42")],
         expect="PS11 label reads PS17; CB42 missing (its label check is skipped)"),
    dict(file="05_after_fix_one_left_open.jpg", seed=21,
         title="After the fix", subtitle="Re-photo of #01 with one fault left",
         faults=[dict(type="missing_ferrule", n=3)],
         expect="Re-check of #01: 3 CLOSED, 1 OPEN (X3:3 ferrule still missing)"),
]


def main():
    config.SAMPLES.mkdir(exist_ok=True)
    manifest, key = [], ["EAGLE EYE sample photos: planted faults (answer key)", "=" * 52, ""]
    for s in SAMPLES:
        path = config.SAMPLES / s["file"]
        photo, _ = render(s["faults"], seed=s["seed"])
        photo.save(path, quality=92)
        rep, _ = inspect(str(path), config.DEMO_GA, config.DEMO_WIRES)
        c = counts(rep["results"])
        issues = [dict(id=r["id"], result=r["result"], found=r["found"]) for r in rep["results"] if r["result"] != "PASS"]
        manifest.append(dict(file=s["file"], title=s["title"], subtitle=s["subtitle"], seed=s["seed"],
                             faults=s["faults"], expect=s["expect"], counts=c, issues=issues))
        key += [s["file"], f"  planted : {json.dumps(s['faults']) if s['faults'] else 'none'}",
                f"  expect  : {s['expect']}", f"  engine  : {c}"] + [f"            {i['result']:<6} {i['id']:<12} {i['found']}" for i in issues] + [""]
        print(s["file"], c, [(i["id"], i["found"]) for i in issues], flush=True)
    json.dump(manifest, open(config.SAMPLES / "manifest.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    (config.SAMPLES / "ANSWER_KEY.txt").write_text("\n".join(key), encoding="utf-8")


if __name__ == "__main__":
    os.chdir(config.BASE)
    main()
