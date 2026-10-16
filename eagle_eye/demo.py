"""End-to-end demo: inspect -> report -> technician fixes -> re-photo -> re-check."""
import json, os
import config
from render import render
from inspector import inspect
from report import *

os.chdir(config.BASE)
IN = "inputs"; OUT = "out/demo"; os.makedirs(OUT, exist_ok=True)
if os.path.exists(f"{OUT}/history.json"):
    os.remove(f"{OUT}/history.json")                      # each demo run starts a fresh issue history
GA, WL, CL = f"{IN}/GA_EE-DEMO-01.pdf", f"{IN}/WireList_EE-DEMO-01.xlsx", f"{IN}/QC_Checklist_EE-DEMO-01.xlsx"

faults = [dict(type="missing_component", tag="PS12"), dict(type="swap_breakers", a="CB43", b="CB44"),
          dict(type="missing_label", tag="1CBP03"), dict(type="missing_ferrule", n=3)]
p, _ = render(faults, seed=7); p.save(f"{OUT}/photo_v1.jpg", quality=92)
rep, _ = inspect(f"{OUT}/photo_v1.jpg", GA, WL); numbered(rep["results"])
json.dump(rep, open(f"{OUT}/report_v1.json", "w"), indent=1, default=str)
markup(f"{OUT}/photo_v1.jpg", rep, f"{OUT}/marked_v1.jpg")
gs = ga_png(GA, f"{OUT}/ga.png")
for r in rep["results"]:
    if "marker" in r:
        snippet(f"{OUT}/photo_v1.jpg", rep, r, f"{OUT}/ga.png", gs, f"{OUT}/snip_{r['marker']}.png")
fill_checklist(CL, rep, f"{OUT}/QC_Checklist_FILLED_v1.xlsx")
history_append(f"{OUT}/history.json", rep, "v1 initial QC")

# technician fixes everything except the ferrule (to show an item staying OPEN), new photo from a new angle
p2, _ = render([dict(type="missing_ferrule", n=3)], seed=21); p2.save(f"{OUT}/photo_v2.jpg", quality=92)
rep2, _ = inspect(f"{OUT}/photo_v2.jpg", GA, WL); recheck(rep, rep2)
json.dump(rep2, open(f"{OUT}/report_v2.json", "w"), indent=1, default=str)
markup(f"{OUT}/photo_v2.jpg", rep2, f"{OUT}/marked_v2.jpg", status_key="recheck")
fill_checklist(CL, rep2, f"{OUT}/QC_Checklist_FILLED_v2.xlsx")
history_append(f"{OUT}/history.json", rep2, "v2 re-check after fix")

# all fixed
p3, _ = render([], seed=33); p3.save(f"{OUT}/photo_v3.jpg", quality=92)
rep3, _ = inspect(f"{OUT}/photo_v3.jpg", GA, WL); recheck(rep2, rep3)
json.dump(rep3, open(f"{OUT}/report_v3.json", "w"), indent=1, default=str)
history_append(f"{OUT}/history.json", rep3, "v3 re-check, all closed")

for tag, rr in (("v1", rep), ("v2", rep2), ("v3", rep3)):
    print(tag, {k: sum(r["result"] == k for r in rr["results"]) for k in ("PASS", "FAIL", "REVIEW", "SKIP")},
          [(r["id"], r["found"], r.get("recheck")) for r in rr["results"] if r["result"] != "PASS" or r.get("recheck")])
