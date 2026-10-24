"""Record real engine runs into a static bundle for the hosted showcase (web build in "static" mode).

    python export_static.py          # writes web/static-public/demo/, then: cd web && npm run build:static

Every inspection in the bundle is a genuine run of this engine: the five sample photos, re-checks between them,
and a pool of Fault Forge cabinets. The hosted page replays them (pipeline timings included); inspecting a new
photo still needs the live engine (python server.py).
"""
import hashlib
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

from PIL import Image

import config
import service
from inspector import CHECKS, ORDER, tesseract_info

OUT = config.BASE / "web" / "static-public" / "demo"
RECHECKS = {"01": ["01", "02", "03", "04", "05"], "02": ["02", "05"], "03": ["02", "05"], "04": ["02", "05"], "05": ["02", "05"]}
FORGE_POOL = [(k, seed) for k in range(5) for seed in (101 + 17 * k, 233 + 31 * k)]
# harsh camera (strength 1.45): the engine sends unreadable zones to REVIEW instead of guessing (Review station demo)
REVIEW_POOL = [302, 305, 322]


def jpg(src, dst, size, q):
    im = Image.open(src).convert("RGB")
    im.thumbnail((size, size * 2), Image.LANCZOS)
    im.save(dst, quality=q, optimize=True, progressive=True)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    for d in ("img", "runs", "inputs", "samples"):
        (OUT / d).mkdir(parents=True)
    tmp_runs = Path(tempfile.mkdtemp(prefix="ee_static_"))
    config.RUNS = tmp_runs                      # keep the real run store untouched
    runs, events, base, recheck, forge = {}, {}, {}, {}, []
    images = {}

    def record(kind, fn):
        ev = []
        meta = fn(ev.append)
        events[meta["id"]] = ev
        runs[meta["id"]] = meta
        print(f"{kind:<10} {meta['id']}  {meta['label']:<44} {meta['counts']}", flush=True)
        return meta

    for s in service.samples():
        base[s["id"]] = record("inspect", lambda e, s=s: service.run_inspection(
            service.sample_path(s["id"]), label=f"Sample {s['id']} · {s['title']}", source="sample",
            photo_name=s["file"], on_event=e))["id"]
    for parent, kids in RECHECKS.items():
        for kid in kids:
            s = next(x for x in service.samples() if x["id"] == kid)
            m = record("recheck", lambda e, s=s, parent=parent: service.run_inspection(
                service.sample_path(s["id"]), parent=base[parent], label=f"Re-check · Sample {s['id']} · {s['title']}",
                source="sample", photo_name=s["file"], on_event=e))
            recheck.setdefault(base[parent], {})[kid] = m["id"]
    v2 = recheck[base["01"]]["05"]
    s02 = next(x for x in service.samples() if x["id"] == "02")
    v3 = record("recheck", lambda e: service.run_inspection(service.sample_path("02"), parent=v2,
                label=f"Re-check · Sample 02 · {s02['title']}", source="sample", photo_name=s02["file"], on_event=e))
    recheck.setdefault(v2, {})["02"] = v3["id"]
    rng = random.Random(7)
    for k, seed in FORGE_POOL:
        m = record("forge", lambda e, k=k, seed=seed: service.run_forge(k=k, seed=seed, strength=round(rng.uniform(0.9, 1.3), 2), on_event=e))
        forge.append(m["id"])
    review = []
    for seed in REVIEW_POOL:
        m = record("forge", lambda e, seed=seed: service.run_forge(seed=seed, strength=1.45, on_event=e))
        forge.append(m["id"])
        review.append(m["id"])

    # files: photos/rectified de-duplicated by content, marked/pdf/xlsx/json per run
    files = {}
    for rid, meta in runs.items():
        d = config.RUNS / rid
        f = {}
        for key, size, q in (("photo", 1700, 82), ("rectified", 1200, 80)):
            src = d / (meta["photo"] if key == "photo" else service.FILES["rectified"])
            h = hashlib.sha1(src.read_bytes()).hexdigest()[:14]
            name = f"img/{key}_{h}.jpg"
            if name not in images:
                jpg(src, OUT / name, size, q)
                images[name] = True
            f[key] = name
        rd = OUT / "runs" / rid
        rd.mkdir()
        jpg(d / service.FILES["marked"], rd / "marked.jpg", 1400, 80)
        shutil.copyfile(d / service.FILES["pdf"], rd / "report.pdf")
        shutil.copyfile(d / service.FILES["checklist"], rd / "checklist.xlsx")
        shutil.copyfile(d / service.FILES["json"], rd / "report.json")
        f.update(marked=f"runs/{rid}/marked.jpg", pdf=f"runs/{rid}/report.pdf", checklist=f"runs/{rid}/checklist.xlsx",
                 json=f"runs/{rid}/report.json", overlay="img/overlay.png")
        (rd / "payload.json").write_text(json.dumps(service.run_payload(rid), separators=(",", ":"), default=str), encoding="utf-8")
        files[rid] = f

    any_run = config.RUNS / next(iter(runs))
    shutil.copyfile(any_run / service.FILES["overlay"], OUT / "img" / "overlay.png")
    png, scale = service.ga_raster(config.DEMO_GA, dpi=200)
    gw, gh = Image.open(png).size
    Image.open(png).convert("RGB").save(OUT / "img" / "ga.jpg", quality=90)
    prev, _ = service.ga_raster(config.DEMO_GA, dpi=110)
    shutil.copyfile(prev, OUT / "img" / "ga_preview.png")
    for key, p in service.default_inputs().items():
        shutil.copyfile(p, OUT / "inputs" / p.name)
    for smp in service.samples():                # full resolution, for the Robustness Lab
        shutil.copyfile(service.sample_path(smp["id"]), OUT / "samples" / smp["file"])

    t = tesseract_info()
    index = dict(
        version=config.VERSION,
        health=dict(ok=True, version=config.VERSION, tesseract=dict(ok=True, cmd="recorded", version=t.get("version") or "tesseract",
                                                                   backend=t.get("backend")),
                    workers=config.WORKERS, cpu=os.cpu_count(), checks=list(CHECKS), runs=len(runs)),
        checks=service.checks_info(),
        samples=[dict(s, image=files[base[s["id"]]]["photo"]) for s in service.samples()],
        inputs={k: dict(name=p.name, size=p.stat().st_size, href=f"inputs/{p.name}") for k, p in service.default_inputs().items()},
        selftest=service.selftest(),
        ga=dict(src="img/ga.jpg", w=gw, h=gh, **scale),
        runs={rid: dict(meta=runs[rid], files=files[rid], events=events[rid]) for rid in runs},
        base=base, recheck=recheck, forge=forge,
        history=[review[0], base["03"], base["04"], forge[3], review[2], forge[7], base["01"], v2, v3["id"]],
        enabled=list(ORDER),
    )
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":"), default=str), encoding="utf-8")
    shutil.rmtree(tmp_runs, ignore_errors=True)
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"\n{len(runs)} recorded runs, {len(images)} images, {total / 2**20:.1f} MB -> {OUT}")


if __name__ == "__main__":
    os.chdir(config.BASE)
    main()
