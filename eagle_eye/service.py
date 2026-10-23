"""Inspection service shared by the web console (server.py) and the Streamlit app.

A *run* is one inspection of one photo, stored in ``out/runs/<run_id>/``:

    photo.jpg             the photo exactly as inspected
    report.json           every checklist item: expected, found, result, evidence, box (mm)
    marked.jpg            photo with every issue boxed and numbered
    rectified.jpg         photo warped onto the drawing (4 px/mm), pixel-aligned with the GA
    ga_overlay.png        GA linework, transparent, aligned with rectified.jpg
    QC_Checklist_FILLED.xlsx, EAGLE_EYE_QC_Report.pdf
    crops/                expected-vs-found proof images, made on demand
    meta.json             summary used by history lists

A re-check run points at its parent; the chain (v1 -> v2 -> v3) is the issue history.
"""
import datetime
import hashlib
import json
import random
import re
import shutil
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import config
import pdf_report
import report as rp
from inspector import CHECKS, ORDER, InspectionError, counts, inspect
from render import describe_fault, expected_item, random_faults, render

FILES = dict(marked="marked.jpg", rectified="rectified.jpg", overlay="ga_overlay.png", json="report.json",
             checklist="QC_Checklist_FILLED.xlsx", pdf="EAGLE_EYE_QC_Report.pdf")
CACHE = config.DATA / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$")


# ------------------------------------------------------------------ helpers
def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def new_id():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def run_dir(rid):
    if not _ID.match(str(rid)):
        raise KeyError(rid)
    d = config.RUNS / rid
    if not d.exists():
        raise KeyError(rid)
    return d


def _sha(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:16]


def _safe(item_id):
    return re.sub(r"[^A-Za-z0-9]+", "_", item_id)


def write_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def prepare_photo(src, dst_dir):
    """Copy the photo into the run; apply EXIF rotation and bring huge phone photos to the tuned size."""
    src = Path(src)
    try:
        im = Image.open(src)
        im.load()
    except Exception as e:  # noqa: BLE001
        raise InspectionError("Could not read the cabinet photo. Upload a JPG or PNG image.") from e
    orient = im.getexif().get(0x0112, 1)
    big = max(im.size) > 3400
    if orient == 1 and not big and im.format in ("JPEG", "PNG"):
        dst = Path(dst_dir) / ("photo.png" if im.format == "PNG" else "photo.jpg")
        shutil.copyfile(src, dst)
        return dst
    im = ImageOps.exif_transpose(im).convert("RGB")
    if big:
        im.thumbnail((2900, 2900), Image.LANCZOS)
    dst = Path(dst_dir) / "photo.jpg"
    im.save(dst, quality=95)
    return dst


def ga_raster(ga_pdf, dpi=200):
    """Raster of the GA drawing for proof crops, cached by file content."""
    key = _sha(ga_pdf)
    png, js = CACHE / f"ga_{key}_{dpi}.png", CACHE / f"ga_{key}_{dpi}.json"
    if not (png.exists() and js.exists()):
        s = rp.ga_png(str(ga_pdf), str(png), dpi=dpi)
        write_json(js, s)
    return png, read_json(js)


def thumbnail(path, width):
    """Cached JPEG thumbnail of any image (history cards, sample gallery)."""
    path = Path(path)
    width = int(max(64, min(1600, width)))
    key = hashlib.sha1(f"{path.resolve()}|{path.stat().st_mtime_ns}|{width}".encode()).hexdigest()[:20]
    out = CACHE / "thumbs" / f"{key}.jpg"
    if not out.exists():
        out.parent.mkdir(exist_ok=True)
        im = Image.open(path).convert("RGB")
        im.thumbnail((width, width * 4), Image.LANCZOS)
        im.save(out, quality=84)
    return out


def verdict(c, n_items, warnings=None):
    weak = next((w for w in warnings or [] if w["code"] == "weak_registration"), None)
    if weak:
        return dict(label="REVIEW", headline="REVIEW · photo does not match the drawing",
                    detail="Too few labels and ferrules could be matched to the GA drawing, so EAGLE EYE refuses to call "
                           "anything FAIL. Check the photo shows this cabinet's whole backplate, then re-photo.")
    if c["FAIL"]:
        return dict(label="HOLD", headline=f"HOLD · {c['FAIL']} fault{'s' if c['FAIL'] != 1 else ''} to fix before shipping",
                    detail="Every FAIL is boxed on the photo with expected-vs-found proof."
                           + (f" {c['REVIEW']} zone(s) also need a re-photo." if c["REVIEW"] else ""))
    if c["REVIEW"]:
        return dict(label="REVIEW", headline=f"REVIEW · re-photo {c['REVIEW']} zone{'s' if c['REVIEW'] != 1 else ''}",
                    detail="No confirmed faults. Some items could not be read clearly, so EAGLE EYE asks for a better photo "
                           "instead of guessing.")
    return dict(label="PASS", headline="PASS · ready to ship",
                detail=f"All {n_items - c['SKIP']} items the drawing expects were verified on the photo.")


# ------------------------------------------------------------------ inputs
def default_inputs():
    return dict(ga=config.DEMO_GA, wires=config.DEMO_WIRES, checklist=config.DEMO_CHECKLIST)


def input_path(rid, meta, key):
    """Where a run's input file lives now (robust to the project folder being moved or copied)."""
    ref = meta["inputs"][key]
    if ref["demo"]:
        return default_inputs()[key]
    return run_dir(rid) / "inputs" / Path(ref["path"]).name


def resolve_inputs(d, ga=None, wires=None, checklist=None, names=None):
    """Use uploaded files when given (copied into the run), otherwise the demo inputs."""
    names = names or {}
    out = {}
    (d / "inputs").mkdir(exist_ok=True)
    for key, given, default in (("ga", ga, config.DEMO_GA), ("wires", wires, config.DEMO_WIRES),
                                ("checklist", checklist, config.DEMO_CHECKLIST)):
        if given:
            name = names.get(key) or Path(given).name
            dst = d / "inputs" / (key + Path(name).suffix.lower())
            shutil.copyfile(given, dst)
            out[key] = dict(path=str(dst), name=name, demo=False)
        else:
            out[key] = dict(path=str(default), name=default.name, demo=True)
    return out


# ------------------------------------------------------------------ the pipeline
def run_inspection(photo, ga=None, wires=None, checklist=None, enabled=None, parent=None, label=None,
                   source="upload", photo_name=None, input_names=None, forge=None, on_event=None,
                   parent_data=None, reports=True):
    """Inspect one photo end to end and store every artefact. Returns the run's meta dict.

    ``parent`` re-checks a stored run; ``parent_data=(meta, report)`` re-checks a run held by the caller
    (the stateless cloud API, where the browser keeps the history). ``reports=False`` skips the Excel and
    PDF so a caller can return results first and call ``build_reports`` afterwards.
    """
    emit = on_event or (lambda ev: None)
    rid = new_id(); d = config.RUNS / rid; d.mkdir(parents=True)
    try:
        return _run(rid, d, photo, ga, wires, checklist, enabled, parent, label, source, photo_name,
                    input_names, forge, emit, parent_data, reports)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise


def _run(rid, d, photo, ga, wires, checklist, enabled, parent, label, source, photo_name, input_names, forge, emit,
         parent_data=None, reports=True):
    enabled = [c for c in (enabled or ORDER) if c in CHECKS] or list(ORDER)
    prev_meta = prev_rep = None
    if parent_data:
        prev_meta, prev_rep = parent_data
        parent = prev_meta.get("id") or parent
    elif parent:
        prev_meta = get_meta(parent)
        prev_rep = read_json(run_dir(parent) / FILES["json"])
        if not (ga or wires or checklist):     # a re-check reuses the drawing set of the run it re-checks
            ga, wires, checklist = (None if prev_meta["inputs"][k]["demo"] else input_path(parent, prev_meta, k)
                                    for k in ("ga", "wires", "checklist"))
            input_names = {k: prev_meta["inputs"][k]["name"] for k in ("ga", "wires", "checklist")}
    inputs = resolve_inputs(d, ga, wires, checklist, input_names)
    photo_path = prepare_photo(photo, d)

    rep, ctx = inspect(str(photo_path), inputs["ga"]["path"], inputs["wires"]["path"], enabled=enabled, on_event=emit)
    if rep.get("orientation"):            # keep the stored photo in the orientation the engine used
        Image.fromarray(ctx.photo).save(photo_path, quality=95)
    rep["photo"] = photo_path.name

    t = datetime.datetime.now(); emit(dict(stage="report", status="start", t=rep["timing"]["total"]))
    if prev_rep:
        rp.recheck(prev_rep, rep)
        status_key = "recheck"
    else:
        rp.numbered(rep["results"])
        status_key = "result"
    Image.fromarray(ctx.rect).save(d / FILES["rectified"], quality=88)
    rp.markup(str(photo_path), rep, str(d / FILES["marked"]), status_key=status_key)
    rp.ga_overlay(inputs["ga"]["path"], rep["ga"]["size"], str(d / FILES["overlay"]))
    c = rep["counts"]
    created = now()
    version = (prev_meta.get("version", 1) + 1) if prev_meta else 1
    meta = dict(id=rid, created=created, label=label or (f"Re-check v{version}" if prev_meta else "Inspection"),
                source=source, photo_name=photo_name or Path(photo).name, photo=photo_path.name, inputs=inputs,
                enabled=enabled, cabinet=rep["ga"]["cabinet"], counts=c, items=len(rep["results"]),
                verdict=verdict(c, len(rep["results"]), rep.get("warnings")), timing=rep["timing"], warnings=rep.get("warnings", []),
                registration={k: rep["registration"][k] for k in ("anchors", "inliers", "outliers", "refined", "targets")},
                issues=[dict(id=r["id"], result=r["result"], found=r["found"], marker=r.get("marker"),
                             recheck=r.get("recheck")) for r in rep["results"] if r.get("marker")],
                parent=parent, root=(prev_meta.get("root") or parent) if prev_meta else rid, version=version,
                recheck=rep.get("recheck"), engine=config.VERSION)
    if forge:
        forge["score"] = score_forge(rep, forge["faults"])
        meta["forge"] = forge
    write_json(d / FILES["json"], rep)
    if reports:
        _reports(rid, rep, meta)
    meta["timing"] = dict(rep["timing"], report=round((datetime.datetime.now() - t).total_seconds(), 3))
    write_json(d / "meta.json", meta)
    emit(dict(stage="report", status="done", t=rep["timing"]["total"] + meta["timing"]["report"],
              files=list(FILES.values())))
    if prev_meta:
        emit(dict(stage="recheck", status="done", t=rep["timing"]["total"] + meta["timing"]["report"], **rep["recheck"]))
    return meta


def _reports(rid, rep, meta):
    d = run_dir(rid)
    rp.fill_checklist(meta["inputs"]["checklist"]["path"], rep, str(d / FILES["checklist"]), meta=meta)
    pdf_report.build_pdf(str(d / FILES["pdf"]), rep, meta, str(d / FILES["marked"]),
                         lambda r: (item_crop(rid, r["id"], "expected", rep=rep, meta=meta),
                                    item_crop(rid, r["id"], "found", rep=rep, meta=meta)))


def build_reports(rid):
    """PDF report + filled Excel checklist for a run stored with ``reports=False``."""
    meta, rep = get_meta(rid), get_report(rid)
    _reports(rid, rep, meta)
    return artefact(rid, "pdf"), artefact(rid, "checklist")


def save_review(rid, item_id, decision, note="", by="Inspector"):
    """Record a human decision on an item (REVIEW items mostly): the audit trail keeps who, what and when."""
    if decision not in ("PASS", "FAIL", "CLEAR"):
        raise ValueError("decision must be PASS, FAIL or CLEAR")
    d = run_dir(rid)
    meta = get_meta(rid)
    rep = get_report(rid)
    if not any(r["id"] == item_id for r in rep["results"]):
        raise KeyError(item_id)
    reviews = meta.setdefault("reviews", {})
    if decision == "CLEAR":
        reviews.pop(item_id, None)
    else:
        reviews[item_id] = dict(decision=decision, note=str(note)[:500], by=str(by)[:80], at=now())
    write_json(d / "meta.json", meta)
    return meta


# ------------------------------------------------------------------ reading runs
def get_meta(rid):
    return read_json(run_dir(rid) / "meta.json")


def get_report(rid):
    return read_json(run_dir(rid) / FILES["json"])


def list_runs(limit=200):
    metas = []
    for p in config.RUNS.glob("*/meta.json"):
        try:
            metas.append(read_json(p))
        except (OSError, ValueError):
            continue
    metas.sort(key=lambda m: m["id"], reverse=True)
    return metas[:limit]


def chain(rid):
    """The run's re-check chain, oldest first (v1 -> v2 -> ...), including later re-checks of it."""
    meta = get_meta(rid)
    root = meta.get("root") or rid
    runs = [m for m in list_runs(10_000) if (m.get("root") or m["id"]) == root]
    return sorted(runs, key=lambda m: (m.get("version", 1), m["id"]))


def run_payload(rid):
    """Everything the UI needs to draw a run: meta, results with photo-space quads, drawing layout."""
    meta, rep = get_meta(rid), get_report(rid)
    H = rep["H"]
    q = lambda box: np.round(rp.to_photo(box, H), 1).tolist()
    for r in rep["results"]:
        r["quad"] = q(r["box"])
    layout = [dict(tag=d["tag"], kind=d["type"], box=d["box"], quad=q(d["box"]), label_box=d["label_box"])
              for d in rep["ga"]["devices"]]
    layout += [dict(tag=t["tag"], kind="terminal", box=t["box"], quad=q(t["box"])) for t in rep["ga"]["terminals"]]
    Wmm, Hmm = rep["ga"]["size"]
    return dict(meta=meta, results=rep["results"], layout=layout, registration=rep["registration"],
                photo_size=rep.get("photo_size"), size_mm=[Wmm, Hmm], backplate_quad=q((0, 0, Wmm, Hmm)),
                rails=rep["ga"]["rails"], wires=rep.get("wires", []), timing=rep.get("timing"),
                files={k: v for k, v in FILES.items()})


def artefact(rid, name):
    d = run_dir(rid)
    if name in ("photo", "photo.jpg", "photo.png"):
        return d / get_meta(rid)["photo"]
    fname = FILES.get(name, name)
    if fname not in FILES.values():
        raise KeyError(name)
    p = d / fname
    if not p.exists():
        raise KeyError(name)
    return p


def item_crop(rid, item_id, kind, rep=None, meta=None):
    """Proof image for one item: 'expected' (GA crop), 'found' (photo crop) or 'aligned' (rectified crop)."""
    d = run_dir(rid)
    if kind not in ("expected", "found", "aligned"):
        raise KeyError(kind)
    out = d / "crops" / f"{_safe(item_id)}_{kind}.{'png' if kind == 'expected' else 'jpg'}"
    if out.exists():
        return out
    rep = rep or get_report(rid); meta = meta or get_meta(rid)
    r = next((x for x in rep["results"] if x["id"] == item_id), None)
    if r is None:
        raise KeyError(item_id)
    out.parent.mkdir(exist_ok=True)
    color = rp.COL.get(r.get("recheck") or r["result"], rp.COL["FAIL"])
    if kind == "expected":
        png, s = ga_raster(input_path(rid, meta, "ga"))
        rp.expected_crop(Image.open(png), s, r["box"]).save(out)
    elif kind == "found":
        rp.found_crop(Image.open(d / meta["photo"]), rep["H"], r["box"], color).save(out, quality=90)
    else:
        rp.aligned_crop(Image.open(d / FILES["rectified"]), r["box"], color).save(out, quality=90)
    return out


def delete_runs():
    n = 0
    for p in config.RUNS.iterdir():
        if p.is_dir() and _ID.match(p.name):
            shutil.rmtree(p, ignore_errors=True); n += 1
    return n


# ------------------------------------------------------------------ samples
def samples():
    mf = config.SAMPLES / "manifest.json"
    items = read_json(mf) if mf.exists() else []
    return [dict(s, id=s["file"].split("_")[0], fault_text=[describe_fault(f) for f in s.get("faults", [])])
            for s in items if (config.SAMPLES / s["file"]).exists()]


def sample_path(name):
    for s in samples():
        if name in (s["file"], s["id"]):
            return config.SAMPLES / s["file"]
    raise KeyError(name)


# ------------------------------------------------------------------ Fault Forge
def forge_photo(dst, k=None, strength=1.0, seed=None, faults=None):
    """Render a never-seen cabinet with hidden planted faults. Returns (path, faults, seed)."""
    seed = int(seed) if seed is not None else random.randrange(10_000, 99_999)
    rng = np.random.default_rng(seed)
    faults = faults if faults is not None else random_faults(rng, None if k is None else int(k))
    photo, _ = render(faults, seed=seed, strength=float(strength))
    photo.save(dst, quality=90)
    return Path(dst), faults, seed


def score_forge(rep, faults):
    res = {r["id"]: r for r in rep["results"]}
    planted = []
    for f in faults:
        item = expected_item(f); r = res.get(item)
        planted.append(dict(fault=f, text=describe_fault(f), item=item, caught=bool(r and r["result"] == "FAIL"),
                            result=r["result"] if r else None, found=r["found"] if r else None))
    exp = {p["item"] for p in planted}
    fa = [r["id"] for r in rep["results"] if r["result"] == "FAIL" and r["id"] not in exp]
    rv = [r["id"] for r in rep["results"] if r["result"] == "REVIEW" and r["id"] not in exp]
    skip = sum(r["result"] == "SKIP" for r in rep["results"])
    return dict(planted=planted, caught=sum(p["caught"] for p in planted), n_planted=len(planted),
                false_alarms=fa, reviews=rv, correct_items=len(rep["results"]) - skip - len(planted))


def run_forge(k=None, strength=1.0, seed=None, faults=None, on_event=None, **kw):
    tmp = CACHE / f"forge_{uuid.uuid4().hex[:8]}.jpg"
    try:
        path, faults, seed = forge_photo(tmp, k=k, strength=strength, seed=seed, faults=faults)
        if on_event:
            on_event(dict(stage="forge", status="done", seed=seed, planted=len(faults)))
        return run_inspection(path, label=f"Fault Forge #{seed}", source="forge", photo_name=f"forge_{seed}.jpg",
                              forge=dict(seed=seed, strength=round(float(strength), 2), faults=faults), on_event=on_event,
                              **kw)
    finally:
        tmp.unlink(missing_ok=True)


def forge_live():
    """Running score over every Fault Forge cabinet inspected on this machine."""
    runs = [m for m in list_runs(10_000) if m.get("forge", {}).get("score")]
    sc = [m["forge"]["score"] for m in runs]
    return dict(cabinets=len(runs), planted=sum(s["n_planted"] for s in sc), caught=sum(s["caught"] for s in sc),
                false_alarms=sum(len(s["false_alarms"]) for s in sc), reviews=sum(len(s["reviews"]) for s in sc),
                correct_items=sum(s["correct_items"] for s in sc),
                runs=[dict(id=m["id"], seed=m["forge"]["seed"], created=m["created"], planted=m["forge"]["score"]["n_planted"],
                           caught=m["forge"]["score"]["caught"], false_alarms=len(m["forge"]["score"]["false_alarms"]),
                           reviews=len(m["forge"]["score"]["reviews"])) for m in runs[:40]])


def selftest():
    """Saved results of the offline Fault Forge self-test (python eval_forge.py 50 200)."""
    d = config.OUT / "forge"
    summary = read_json(d / "summary.json") if (d / "summary.json").exists() else None
    rows = []
    if (d / "results.json").exists():
        for r in read_json(d / "results.json"):
            rows.append(dict(i=r["i"], strength=round(r["strength"], 2), planted=len(r["faults"]),
                             caught=sum(r["caught"].values()), false_alarms=len(r["false_alarms"]),
                             reviews=len(r["reviews"]), anchors=r.get("anchors"), sec=r.get("sec"),
                             faults=[describe_fault(f) for f in r["faults"]]))
        rows.sort(key=lambda r: r["i"])
    return dict(summary=summary, cabinets=rows)


def checks_info():
    return [dict(name=n, title=getattr(c, "title", n), question=getattr(c, "question", ""),
                 doc=(c.__doc__ or "").strip(), builtin=n in ORDER) for n, c in CHECKS.items()]
