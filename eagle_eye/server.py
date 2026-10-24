"""EAGLE EYE console: FastAPI backend + the web UI in web/dist.

    python server.py                  # opens http://127.0.0.1:8000
    python server.py --port 9000 --host 0.0.0.0 --no-browser

Inspections run one at a time on a background worker; the UI follows them live through /api/jobs/{id}.

/api/v2 is the stateless cloud API used by the hosted console: one request inspects and streams the result back
(NDJSON), nothing is kept on the server, so any container instance can serve any request. Photos are metadata-first:
the client sends fingerprints (SHA-256) before files, the engine reads a photo once and returns metadata (results,
boxes, reads, small proof crops), never the photo itself.
"""
import argparse
import base64
import io
import json
import os
import queue
import shutil
import threading
import time
import traceback
import uuid
import webbrowser
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

import config
import service
from inspector import InspectionError, tesseract_info

UPLOADS = service.CACHE / "uploads"


def _mb(name, default):
    try:
        return max(1, int(float(os.environ.get(name) or default))) * 1024 * 1024
    except ValueError:
        return default * 1024 * 1024


MAX_PHOTO = _mb("EAGLE_MAX_PHOTO_MB", 25)
MAX_PDF = _mb("EAGLE_MAX_PDF_MB", 30)
MAX_UPLOAD = max(MAX_PHOTO, MAX_PDF)
RATE = max(0, int(os.environ.get("EAGLE_RATE_PER_MIN") or 6))
REAL_DATA = Path(os.environ.get("EAGLE_EYE_REAL_DATA") or config.BASE.parent / "data" / "emerson")
# Hosted preset: the drawing set + photos live in the engine's PRIVATE Vercel Blob store under this prefix (never in
# git, never at a public URL); they are mirrored into the container's /tmp on first use.
PRESET_BLOB = (os.environ.get("EAGLE_PRESET_BLOB") or "").strip()
ADMIN_TOKEN = (os.environ.get("EAGLE_ADMIN_TOKEN") or "").strip()
CLOUD = os.environ.get("EAGLE_EYE_CLOUD") == "1"          # hosted engine container: stateless API only
CONSOLE_URL = os.environ.get("EAGLE_EYE_CONSOLE", "https://aegis-eagle-eye.vercel.app")
STARTED = time.time()
KINDS = {"photo": (".jpg", ".jpeg", ".png"), "ga": (".pdf",), "wires": (".xlsx",), "checklist": (".xlsx",)}


# ------------------------------------------------------------------ background jobs
class Jobs:
    """FIFO worker: one inspection at a time (each already uses every core for OCR)."""

    def __init__(self):
        self.jobs, self.order = {}, []
        self.lock = threading.Lock()
        self.q = queue.Queue()
        threading.Thread(target=self._work, name="ee-jobs", daemon=True).start()

    def submit(self, kind, fn, cleanup=None, **info):
        jid = uuid.uuid4().hex[:12]
        job = dict(id=jid, kind=kind, status="queued", events=[], runs=[], run_id=None, error=None,
                   created=time.time(), started=None, finished=None, **info)
        with self.lock:
            self.jobs[jid] = job; self.order.append(jid)
            for old in self.order[:-200]:
                self.jobs.pop(old, None)
            self.order = self.order[-200:]
        self.q.put((jid, fn, cleanup))
        return self.view(jid)

    def view(self, jid, since=0):
        with self.lock:
            job = self.jobs.get(jid)
            if not job:
                return None
            ahead = sum(1 for j in self.jobs.values() if j["status"] in ("queued", "running") and j["created"] < job["created"])
            out = {k: v for k, v in job.items() if k != "events"}
            out["events"] = job["events"][since:]
            out["n_events"] = len(job["events"])
            out["queue_position"] = ahead if job["status"] == "queued" else 0
            out["elapsed"] = round((job["finished"] or time.time()) - (job["started"] or time.time()), 2) if job["started"] else 0
        return out

    def _event(self, jid, ev):
        with self.lock:
            self.jobs[jid]["events"].append(ev)

    def _work(self):
        while True:
            jid, fn, cleanup = self.q.get()
            with self.lock:
                job = self.jobs.get(jid)
                if job is None:
                    continue
                job["status"], job["started"] = "running", time.time()
            try:
                runs = fn(lambda ev: self._event(jid, ev), job)
                with self.lock:
                    job["runs"] = [m["id"] for m in runs]
                    job["run_id"] = job["runs"][-1] if job["runs"] else None
                    job["status"] = "done"
            except InspectionError as e:
                with self.lock:
                    job["status"], job["error"] = "error", str(e)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                with self.lock:
                    job["status"], job["error"] = "error", f"Unexpected error: {e}"
            finally:
                with self.lock:
                    job["finished"] = time.time()
                if cleanup:
                    cleanup()


JOBS = Jobs()
app = FastAPI(title="EAGLE EYE", version=config.VERSION,
              description="Drawing-first control-cabinet QC: photo + GA drawing + wire list -> filled QC checklist with proof.")
try:                                    # never gzip the NDJSON stream: compression would hold back progress lines
    from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES
    app.add_middleware(GZipMiddleware, minimum_size=2048,
                       exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + ("application/x-ndjson",))
except ImportError:                     # older Starlette: progress lines may arrive in bursts
    app.add_middleware(GZipMiddleware, minimum_size=2048)
# The cloud API is cookie-free; EAGLE_CORS_ORIGINS limits which consoles may call it (default: any origin).
_ORIGINS = [o.strip() for o in (os.environ.get("EAGLE_CORS_ORIGINS") or "*").split(",") if o.strip()]
if _ORIGINS != ["*"]:
    _ORIGINS += ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"]
app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_methods=["GET", "POST", "OPTIONS"],
                   allow_headers=["*"], max_age=86400)


@app.middleware("http")
async def _oidc_token(request, call_next):
    """Vercel passes a short-lived OIDC token with each request; the private Blob store is read with it."""
    tok = request.headers.get("x-vercel-oidc-token")
    if tok:
        import blobstore
        blobstore.remember_oidc(tok)
    return await call_next(request)


def _err(status, msg):
    raise HTTPException(status_code=status, detail=msg)


async def _save_upload(up: Optional[UploadFile], kind, folder: Path):
    if up is None or not up.filename:
        return None, None
    ext = Path(up.filename).suffix.lower()
    if ext not in KINDS[kind]:
        _err(400, f"{kind}: expected {' / '.join(KINDS[kind])}, got '{up.filename}'")
    data = await up.read()
    limit = MAX_PDF if kind == "ga" else MAX_PHOTO if kind == "photo" else MAX_UPLOAD
    if len(data) > limit:
        _err(413, f"{up.filename} is larger than {limit // 2**20} MB")
    if not data:
        _err(400, f"{up.filename} is empty")
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{kind}{ext}"
    p.write_bytes(data)
    return p, Path(up.filename).name


def _photo_source(sample, photo_path, photo_name):
    if photo_path:
        return photo_path, photo_name, "upload", f"Upload · {photo_name}"
    if sample:
        try:
            p = service.sample_path(sample)
        except KeyError:
            _err(404, f"Unknown sample '{sample}'")
        s = next(x for x in service.samples() if x["file"] == p.name)
        return p, p.name, "sample", f"Sample {s['id']} · {s['title']}"
    try:
        p = service.sample_path("01")
    except KeyError:
        p = config.DEMO_PHOTO
    return p, "01_emerson_example_4_faults.jpg", "sample", "Sample 01 · Emerson's example"


def _enabled(checks):
    return [c.strip().upper() for c in checks.split(",") if c.strip()] if checks else None


_hits, _hits_lock = {}, threading.Lock()


def _rate_limit(request):
    """At most EAGLE_RATE_PER_MIN inspections per client IP per minute on the public cloud API (0 = no limit)."""
    if not (CLOUD and RATE):
        return
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0]
    now_ = time.time()
    with _hits_lock:
        hits = [t for t in _hits.get(ip, []) if now_ - t < 60]
        if len(hits) >= RATE:
            _err(429, f"Too many inspections from this address: at most {RATE} per minute. Try again shortly.")
        _hits[ip] = hits + [now_]
        for k in [k for k, v in _hits.items() if not v or now_ - v[-1] > 120]:
            _hits.pop(k, None)


# ------------------------------------------------------------------ real-cabinet presets
def _real_data():
    """Folder holding the real-cabinet preset: the private Blob store's copy when EAGLE_PRESET_BLOB is set, else
    EAGLE_EYE_REAL_DATA (data/emerson locally)."""
    if PRESET_BLOB:
        import blobstore
        if blobstore.enabled():
            try:
                return blobstore.sync(PRESET_BLOB, config.DATA / "presets" / PRESET_BLOB.strip("/").split("/")[-1])
            except Exception:  # noqa: BLE001 - a storage hiccup must not take the engine down
                traceback.print_exc()
                d = config.DATA / "presets" / PRESET_BLOB.strip("/").split("/")[-1]
                return d if d.is_dir() else REAL_DATA
    return REAL_DATA


def _presets():
    """Real drawing sets with photos (never in git): a private Blob store in the cloud, data/emerson locally."""
    REAL_DATA = _real_data()
    if not REAL_DATA.is_dir():
        return []
    pdfs = sorted(REAL_DATA.glob("*.pdf"))
    photos = sorted(p for p in REAL_DATA.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not pdfs or not photos:
        return []
    cab = None
    try:
        from kb import drawing_kb
        kb = drawing_kb._load_cached(drawing_kb._cache_file(drawing_kb._sha256(pdfs[0])))
        cab = kb and kb.get("cabinet")
    except Exception:  # noqa: BLE001
        pass
    gt = {}
    if (REAL_DATA / "ground_truth.json").exists():
        try:
            gt = json.loads((REAL_DATA / "ground_truth.json").read_text(encoding="utf-8")).get("photos", {})
        except (OSError, ValueError):
            gt = {}
    title = f"{REAL_DATA.name.capitalize()} {cab}" if cab else f"Real cabinet ({pdfs[0].stem})"
    try:
        title = json.loads((REAL_DATA / "preset.json").read_text(encoding="utf-8")).get("title") or title
    except (OSError, ValueError):
        pass
    return [dict(id=REAL_DATA.name.lower(), title=title, cabinet=cab, ga=pdfs[0], dir=REAL_DATA,
                 photos=[dict(file=p.name, content=gt.get(p.name, {}).get("content", "")) for p in photos])]


def _preset(pid, photo_name=None):
    pre = next((p for p in _presets() if p["id"] == pid), None)
    if pre is None:
        _err(404, f"Unknown preset '{pid}' (no real drawing set on this engine)")
    names = [p["file"] for p in pre["photos"]]
    name = photo_name or names[0]
    if name not in names:
        _err(404, f"Unknown photo '{name}' in preset '{pid}'")
    return dict(pre, photo=pre["dir"] / name)


_PRESET_KINDS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".json": "application/json"}


@app.post("/api/v2/admin/preset", include_in_schema=False)
async def admin_preset_upload(request: Request, file: UploadFile = File(...)):
    """Put one preset file into the engine's PRIVATE Blob store (EAGLE_ADMIN_TOKEN in the x-admin-token header).
    Disabled unless both EAGLE_ADMIN_TOKEN (>= 24 chars) and EAGLE_PRESET_BLOB are set."""
    import hmac
    import blobstore
    if len(ADMIN_TOKEN) < 24 or not PRESET_BLOB or not blobstore.enabled():
        _err(404, "not found")
    if not hmac.compare_digest(request.headers.get("x-admin-token", ""), ADMIN_TOKEN):
        _err(403, "forbidden")
    name = Path(file.filename or "").name
    ext = Path(name).suffix.lower()
    if not name or name.startswith(".") or ext not in _PRESET_KINDS:
        _err(400, "file: .pdf / .jpg / .png / .json")
    data = await file.read()
    if not data:
        _err(400, "empty file")
    rec = blobstore.put(PRESET_BLOB.rstrip("/") + "/" + name, data, _PRESET_KINDS[ext])
    blobstore.sync(PRESET_BLOB, config.DATA / "presets" / PRESET_BLOB.strip("/").split("/")[-1], force=True)
    return dict(stored=rec.get("pathname"), bytes=len(data), access="private")


# ------------------------------------------------------------------ API
@app.get("/api/health")
def health():
    t = tesseract_info()
    eh = _engine_health()          # ok when either engine can run: Tesseract (demo cabinets) or PP-OCRv4 (real ones)
    return dict(ok=t["ok"] or eh["ocr"].get("ok", False), version=config.VERSION, tesseract=t, workers=config.WORKERS,
                cpu=os.cpu_count(), checks=list(service.CHECKS), runs=len(list(config.RUNS.glob("*/meta.json"))), **eh)


@app.get("/api/presets")
@app.get("/api/v2/presets")
def presets():
    return [dict(id=p["id"], title=p["title"], cabinet=p["cabinet"], ga=p["ga"].name, photos=p["photos"])
            for p in _presets()]


@app.get("/api/presets/{pid}/photos/{name}")
@app.get("/api/v2/presets/{pid}/photos/{name}")
def preset_photo(pid: str, name: str, w: int = 480):
    p = _preset(pid, name)["photo"]
    return FileResponse(service.thumbnail(p, max(64, min(1600, w or 480))), headers={"Cache-Control": "max-age=3600"})


@app.get("/api/checks")
def checks():
    return service.checks_info()


@app.get("/api/samples")
def samples():
    return service.samples()


@app.get("/api/samples/{sid}/image")
def sample_image(sid: str, w: int = 0):
    try:
        p = service.sample_path(sid)
    except KeyError:
        _err(404, "unknown sample")
    return FileResponse(service.thumbnail(p, w) if w else p, headers={"Cache-Control": "max-age=3600"})


@app.get("/api/inputs")
def inputs():
    return {k: dict(name=v.name, size=v.stat().st_size) for k, v in service.default_inputs().items()}


@app.get("/api/inputs/{key}")
def input_file(key: str):
    p = service.default_inputs().get(key)
    if not p:
        _err(404, "unknown input")
    return FileResponse(p, filename=p.name)


@app.get("/api/inputs/ga/preview")
def ga_preview():
    png, _ = service.ga_raster(config.DEMO_GA, dpi=110)
    return FileResponse(png, headers={"Cache-Control": "max-age=3600"})


@app.post("/api/inspect")
async def start_inspect(photo: Optional[UploadFile] = File(None), sample: Optional[str] = Form(None),
                        ga: Optional[UploadFile] = File(None), wires: Optional[UploadFile] = File(None),
                        checklist: Optional[UploadFile] = File(None), checks: Optional[str] = Form(None),
                        parent: Optional[str] = Form(None), engine: Optional[str] = Form(None),
                        preset: Optional[str] = Form(None), preset_photo: Optional[str] = Form(None)):
    folder = UPLOADS / uuid.uuid4().hex[:12]
    try:
        photo_path, photo_name = await _save_upload(photo, "photo", folder)
        ga_p, ga_n = await _save_upload(ga, "ga", folder)
        wl_p, wl_n = await _save_upload(wires, "wires", folder)
        cl_p, cl_n = await _save_upload(checklist, "checklist", folder)
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if parent:
        try:
            service.get_meta(parent)
        except KeyError:
            _err(404, f"Unknown run '{parent}'")
    if preset and not photo_path:
        pre = _preset(preset, preset_photo)
        src, name, source, label = pre["photo"], pre["photo"].name, "preset", f"{pre['title']} · {pre['photo'].name}"
        if not ga_p:
            ga_p, ga_n = pre["ga"], pre["ga"].name
    else:
        src, name, source, label = _photo_source(sample, photo_path, photo_name)
    enabled = _enabled(checks)
    names = {k: n for k, n in (("ga", ga_n), ("wires", wl_n), ("checklist", cl_n)) if n}

    def work(emit, job):
        meta = service.run_inspection(src, ga_p, wl_p, cl_p, enabled=enabled, parent=parent or None,
                                      label=("Re-check · " + label) if parent else label, source=source,
                                      photo_name=name, input_names=names, on_event=emit, engine=engine or "auto")
        return [meta]

    return JOBS.submit("recheck" if parent else "inspect", work, cleanup=lambda: shutil.rmtree(folder, ignore_errors=True),
                       label=label, parent=parent)


class ForgeRequest(BaseModel):
    faults: Optional[int] = Field(None, ge=0, le=5, description="number of planted faults (random if empty)")
    strength: float = Field(1.0, ge=0.5, le=1.6, description="camera nastiness: angle, light, colour cast, blur, noise")
    seed: Optional[int] = Field(None, ge=0, le=10_000_000)
    count: int = Field(1, ge=1, le=10)


@app.post("/api/forge")
def start_forge(req: ForgeRequest):
    def work(emit, job):
        metas = []
        for i in range(req.count):
            emit(dict(stage="cabinet", status="start", index=i + 1, count=req.count, t=0))
            seed = None if req.seed is None else req.seed + i
            metas.append(service.run_forge(k=req.faults, strength=req.strength, seed=seed, on_event=emit))
            with JOBS.lock:
                job["runs"] = [m["id"] for m in metas]
        return metas

    return JOBS.submit("forge", work, label=f"Fault Forge × {req.count}", count=req.count)


@app.get("/api/jobs/{jid}")
def job(jid: str, since: int = 0):
    v = JOBS.view(jid, since)
    if v is None:
        _err(404, "unknown job")
    return v


def _meta_or_404(rid):
    try:
        return service.get_meta(rid)
    except KeyError:
        _err(404, f"Unknown run '{rid}'")


@app.get("/api/runs")
def runs(limit: int = 100):
    return service.list_runs(limit)


@app.delete("/api/runs")
def clear_runs():
    return dict(deleted=service.delete_runs())


@app.get("/api/runs/{rid}")
def run(rid: str):
    _meta_or_404(rid)
    return service.run_payload(rid)


@app.get("/api/runs/{rid}/chain")
def run_chain(rid: str):
    _meta_or_404(rid)
    return service.chain(rid)


@app.get("/api/runs/{rid}/files/{name}")
def run_file(rid: str, name: str, w: int = 0, download: int = 0):
    meta = _meta_or_404(rid)
    try:
        p = service.artefact(rid, name)
    except KeyError:
        _err(404, "unknown file")
    if w and p.suffix.lower() in (".jpg", ".jpeg", ".png") and name != "overlay":
        p = service.thumbnail(p, w)
    fname = None
    if download:
        stem = f"{meta['cabinet']}_{rid}"
        fname = {"checklist": f"QC_Checklist_{stem}.xlsx", "pdf": f"EAGLE_EYE_Report_{stem}.pdf",
                 "json": f"EAGLE_EYE_{stem}.json", "marked": f"Marked_{stem}.jpg"}.get(name, p.name)
    return FileResponse(p, filename=fname, headers={"Cache-Control": "max-age=86400"})


@app.get("/api/runs/{rid}/items/{item_id}/{kind}")
def run_item_crop(rid: str, item_id: str, kind: str):
    _meta_or_404(rid)
    try:
        return FileResponse(service.item_crop(rid, item_id, kind), headers={"Cache-Control": "max-age=86400"})
    except KeyError:
        _err(404, "unknown item")


class ReviewRequest(BaseModel):
    item: str = Field(..., max_length=80)
    decision: Literal["PASS", "FAIL", "CLEAR"]
    note: str = Field("", max_length=500)
    by: str = Field("Inspector", max_length=80)


@app.post("/api/runs/{rid}/review")
def run_review(rid: str, req: ReviewRequest):
    """Human-in-the-loop: an inspector confirms or overrides an item (REVIEW items mostly). Kept as an audit trail."""
    _meta_or_404(rid)
    try:
        return service.save_review(rid, req.item, req.decision, req.note, req.by)
    except KeyError:
        _err(404, f"Unknown item '{req.item}'")


@app.get("/api/forge/live")
def forge_live():
    return service.forge_live()


@app.get("/api/forge/selftest")
def forge_selftest():
    return service.selftest()


@app.get("/api/forge/gap")
@app.get("/api/v2/forge/gap")
def forge_gap():
    """Fault Forge, synthetic vs real: the saved comparison (python eval_gap.py), else the synthetic side alone."""
    import eval_gap
    return eval_gap.load()


# ------------------------------------------------------------------ stateless cloud API (/api/v2)
GATE = threading.BoundedSemaphore(max(1, int(os.environ.get("EAGLE_EYE_CONCURRENCY", "1"))))
_waiting = [0]
_waiting_lock = threading.Lock()


def _jpeg_b64(path, max_side, quality=82):
    im = Image.open(path).convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return base64.b64encode(buf.getvalue()).decode()


def _file_b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def _pack(meta):
    """What the browser keeps of a run: metadata (payload + report), the PDF and the filled checklist.

    Photos are never sent back: the browser shows its own copy of the photo it inspected and draws the boxes from the
    metadata. Only images the browser cannot have are included, all small: the preview of an engine-generated photo
    (Fault Forge, server samples), the demo engine's drawing-aligned view, and drawing crops of a real drawing set.
    """
    rid = meta["id"]
    d = service.run_dir(rid)
    F = service.FILES
    files = dict(pdf=_file_b64(d / F["pdf"]), checklist=_file_b64(d / F["checklist"]))
    payload = service.run_payload(rid)
    report = service.get_report(rid)
    if meta.get("source") in ("forge", "sample", "preset"):
        files["preview"] = _file_b64(d / F["preview"])
    if meta.get("engine_kind") != "real":
        if (d / F["rectified"]).exists():
            files["rectified"] = _file_b64(d / F["rectified"])
        if not meta["inputs"]["ga"]["demo"]:              # the demo drawing's overlay and raster ship with the console
            files["overlay"] = _file_b64(d / F["overlay"])
            png, scale = service.ga_raster(service.input_path(rid, meta, "ga"))
            with Image.open(png) as im:
                payload["ga_raster"] = dict(w=im.width, h=im.height, **scale)
            files["ga"] = _jpeg_b64(png, 2400, 88)
    else:
        # one drawing crop per checklist target (MISS-X and LBL-X share it); photo crops are made by the browser
        seen = {}
        for r in report["results"]:
            if r["result"] == "NOT_IN_VIEW":
                continue
            key = f"{r['check'] in ('MISSING', 'LABEL') and r['target'] or r['id']}"
            if key not in seen:
                p = service.item_crop(rid, r["id"], "expected", rep=report, meta=meta)
                seen[key] = _jpeg_b64(p, service.CROP_SIDE, 80)
            files[f"exp:{r['id']}"] = seen[key]
    for k in ("ga", "wires", "checklist"):                 # server paths mean nothing to the browser
        payload["meta"]["inputs"][k].pop("path", None)
    return dict(payload=payload, report=report, files=files, storage="metadata")


def _stream(work, cleanup=None, session_kb=None):
    """Run ``work(emit) -> [meta, ...]`` on a worker thread; stream progress, then each packed run, as NDJSON.
    With several runs and ``session_kb`` (real drawing set), a ``session`` line merges them (coverage across photos)."""
    q = queue.Queue()

    def runner():
        made = []
        with _waiting_lock:
            _waiting[0] += 1
            ahead = _waiting[0] - 1
        if ahead:
            q.put(dict(type="queued", position=ahead))
        try:
            with GATE:
                with _waiting_lock:
                    _waiting[0] -= 1
                ahead = None

                def emit(ev):
                    q.put(dict(type="event", event=ev))

                reports = []
                for meta in work(emit, made):
                    packed = _pack(meta)
                    reports.append(packed["report"])
                    q.put(dict(type="result", **packed))
                if session_kb and len(reports) > 1:
                    import pipeline
                    q.put(dict(type="session", session=pipeline.session(reports, session_kb), runs=list(made)))
        except service.NeedPhoto as e:
            q.put(dict(type="need", need=[str(e)]))
        except InspectionError as e:
            q.put(dict(type="error", detail=str(e)))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            q.put(dict(type="error", detail=f"Unexpected error: {e}"))
        finally:
            if ahead is not None:
                with _waiting_lock:
                    _waiting[0] -= 1
            for rid in made:
                shutil.rmtree(config.RUNS / rid, ignore_errors=True)
            if cleanup:
                cleanup()
            q.put(None)

    threading.Thread(target=runner, name="ee-v2", daemon=True).start()

    def lines():
        while True:
            try:
                msg = q.get(timeout=8)
            except queue.Empty:
                msg = dict(type="ping")                   # keeps proxies from closing a quiet connection
            if msg is None:
                return
            yield json.dumps(msg, separators=(",", ":"), default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def _parent_data(raw):
    try:
        data = json.loads(raw)
        meta, rep = data["meta"], data["report"]
        assert isinstance(meta, dict) and isinstance(rep.get("results"), list)
    except Exception:  # noqa: BLE001
        _err(400, "parent: expected JSON {meta, report} of the run being re-checked")
    return meta, rep


def _engine_health():
    out = {}
    try:
        from vision import ocr
        out["ocr"] = ocr.engine_info()
    except Exception as e:  # noqa: BLE001
        out["ocr"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        from agent import status
        out["agent"] = status()
    except Exception as e:  # noqa: BLE001
        out["agent"] = {"enabled": False, "reason": f"{type(e).__name__}: {e}"}
    out["presets"] = [dict(id=p["id"], title=p["title"], photos=len(p["photos"])) for p in _presets()]
    out["storage"] = "metadata"                  # photos are read once and never stored
    return out


@app.get("/api/v2/health")
def health_v2():
    t = tesseract_info()
    return dict(ok=t["ok"] or _engine_health()["ocr"].get("ok", False), version=config.VERSION, tesseract=t,
                workers=config.WORKERS, cpu=os.cpu_count(), checks=list(service.CHECKS),
                mode="cloud" if CLOUD else "local", stateless=True, uptime=round(time.time() - STARTED, 1),
                busy=_waiting[0], **_engine_health())


class _Need(Exception):
    def __init__(self, need):
        super().__init__(", ".join(need))
        self.need = need


def _fingerprinted(kind, up_path, sha):
    """An input given as a file, or as a SHA-256 fingerprint the engine already holds; None when neither."""
    if up_path is not None:
        if sha and service.sha256_file(up_path) != sha:
            _err(400, f"{kind}: the file does not match its fingerprint")
        return up_path
    if sha:
        p = service.input_by_sha(sha, KINDS[kind][0])
        if p is None:
            raise _Need([kind])
        return p
    return None


@app.post("/api/v2/inputs")
async def store_input_v2(request: Request, file: UploadFile = File(...), kind: str = Form(...)):
    """Keep one input (drawing set / wire list / checklist) by its SHA-256 so inspections can name it by fingerprint.

    Lets a client send a large drawing on its own request, then inspect with ``ga_sha`` + the photo: a serverless host
    caps each request body (4.5 MB on Vercel), so drawing and photo cannot always travel together."""
    _rate_limit(request)
    if kind not in ("ga", "wires", "checklist"):
        _err(400, "kind: ga | wires | checklist")
    folder = UPLOADS / uuid.uuid4().hex[:12]
    try:
        p, name = await _save_upload(file, kind, folder)
        ref = service.store_input(p, name)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return dict(kind=kind, sha256=ref["sha256"], name=name, stored=True)


@app.post("/api/v2/inspect")
async def inspect_v2(request: Request, photo: Optional[UploadFile] = File(None), sample: Optional[str] = Form(None),
                     ga: Optional[UploadFile] = File(None), wires: Optional[UploadFile] = File(None),
                     checklist: Optional[UploadFile] = File(None), checks: Optional[str] = Form(None),
                     parent: Optional[UploadFile] = File(None), label: Optional[str] = Form(None),
                     photo_sha: Optional[str] = Form(None), photo_name: Optional[str] = Form(None),
                     ga_sha: Optional[str] = Form(None), wires_sha: Optional[str] = Form(None),
                     checklist_sha: Optional[str] = Form(None), engine: Optional[str] = Form(None),
                     preset: Optional[str] = Form(None), preset_photo: Optional[str] = Form(None),
                     photos: Optional[List[UploadFile]] = File(None), ga_name: Optional[str] = Form(None),
                     wires_name: Optional[str] = Form(None), checklist_name: Optional[str] = Form(None)):
    """Inspect and stream progress + the complete run back (metadata, never the photo).

    Fingerprint-first: send ``photo_sha`` (and ``ga_sha`` / ``wires_sha`` / ``checklist_sha``) without the files. If
    the engine already holds the result / the inputs, nothing is uploaded; otherwise it answers 409 with
    ``{"need": [...]}`` and the client sends just those files. ``photos`` (several files) inspects one cabinet from
    several sides and ends with a ``session`` line (coverage across photos). ``parent`` = JSON {meta, report} of the
    run being re-checked (the browser keeps the history). Without GA / wire list / checklist the demo set is used.
    """
    _rate_limit(request)
    folder = UPLOADS / uuid.uuid4().hex[:12]
    try:
        photo_path, up_name = await _save_upload(photo, "photo", folder)
        ga_p, ga_n = await _save_upload(ga, "ga", folder)
        wl_p, wl_n = await _save_upload(wires, "wires", folder)
        cl_p, cl_n = await _save_upload(checklist, "checklist", folder)
        multi = []
        for i, up in enumerate(photos or []):
            p, n = await _save_upload(up, "photo", folder / f"p{i}")
            if p:
                multi.append((p, n))
        parent_data = _parent_data(await parent.read()) if parent is not None and parent.filename else None
        pre = _preset(preset, preset_photo) if preset else None
        if pre:
            ga_p, ga_n = pre["ga"], pre["ga"].name
        need = []
        for kind, up, sha in (("ga", ga_p, ga_sha), ("wires", wl_p, wires_sha), ("checklist", cl_p, checklist_sha)):
            try:
                _fingerprinted(kind, up, sha)
            except _Need as e:
                need += e.need
        ga_p = _fingerprinted("ga", ga_p, ga_sha) if "ga" not in need else None
        wl_p = _fingerprinted("wires", wl_p, wires_sha) if "wires" not in need else None
        cl_p = _fingerprinted("checklist", cl_p, checklist_sha) if "checklist" not in need else None
        if (not photo_path and photo_sha and not sample and not pre and not multi and not need and not
                service.has_result(photo_sha, ga_p, wl_p, cl_p, _enabled(checks), engine or "auto",
                                   (parent_data[0].get("engine_kind") if parent_data else None))):
            need.append("photo")
        if need:
            shutil.rmtree(folder, ignore_errors=True)
            return JSONResponse(status_code=409, content=dict(detail="send these files", need=need))
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    enabled = _enabled(checks)
    names = {k: n for k, n in (("ga", ga_n or ga_name or (ga_p.name if ga_p and ga_sha else None)),
                               ("wires", wl_n or wires_name), ("checklist", cl_n or checklist_name)) if n}
    if multi:
        def work(emit, made):
            for i, (p, n) in enumerate(multi):
                emit(dict(stage="cabinet", status="start", index=i + 1, count=len(multi), t=0))
                meta = service.run_inspection(p, ga_p, wl_p, cl_p, enabled=enabled, label=f"Upload · {n}",
                                              source="upload", photo_name=n, input_names=names, on_event=emit,
                                              engine=engine or "auto")
                made.append(meta["id"])
                yield meta
        return _stream(work, cleanup=lambda: shutil.rmtree(folder, ignore_errors=True),
                       session_kb=str(ga_p) if ga_p else None)
    if pre:
        src, name, source, default_label = pre["photo"], pre["photo"].name, "preset", f"{pre['title']} · {pre['photo'].name}"
    elif photo_path is None and photo_sha and not sample:
        src, name, source, default_label = None, photo_name or "photo", "upload", f"Upload · {photo_name or 'photo'}"
    else:
        src, name, source, default_label = _photo_source(sample, photo_path, up_name)
    label = (label or "").strip()[:120] or (("Re-check · " + default_label) if parent_data else default_label)

    def work(emit, made):
        meta = service.run_inspection(src, ga_p, wl_p, cl_p, enabled=enabled, label=label, source=source,
                                      photo_name=photo_name or name, input_names=names, on_event=emit,
                                      parent_data=parent_data, engine=engine or "auto", photo_sha=photo_sha)
        made.append(meta["id"])
        yield meta

    return _stream(work, cleanup=lambda: shutil.rmtree(folder, ignore_errors=True))


class ForgeOne(BaseModel):
    faults: Optional[int] = Field(None, ge=0, le=5)
    strength: float = Field(1.0, ge=0.5, le=1.6)
    seed: Optional[int] = Field(None, ge=0, le=10_000_000)


@app.post("/api/v2/forge")
def forge_v2(req: ForgeOne, request: Request):
    """Fault Forge: build an unseen cabinet with hidden faults, inspect it, score it against the answer key."""
    _rate_limit(request)

    def work(emit, made):
        meta = service.run_forge(k=req.faults, strength=req.strength, seed=req.seed, on_event=emit)
        made.append(meta["id"])
        yield meta

    return _stream(work)


def _diag(fn):
    with GATE:
        return fn()


@app.get("/api/v2/diag/samples")
def diag_samples(ids: str = "01,02,03,04,05"):
    """Parity check: inspect the shipped sample photos and report counts (compare with the local engine)."""
    def run():
        out = []
        for sid in [x.strip() for x in ids.split(",") if x.strip()][:5]:
            try:
                p = service.sample_path(sid)
            except KeyError:
                _err(404, f"Unknown sample '{sid}'")
            meta = service.run_inspection(p, label=f"diag {sid}", source="sample", reports=False)
            shutil.rmtree(config.RUNS / meta["id"], ignore_errors=True)
            out.append(dict(sample=sid, counts=meta["counts"], verdict=meta["verdict"]["label"],
                            issues=[(i["id"], i["result"]) for i in meta["issues"]], seconds=meta["timing"]["total"]))
        return dict(version=config.VERSION, tesseract=tesseract_info().get("version"), cpu=os.cpu_count(), runs=out)
    return _diag(run)


@app.get("/api/v2/diag/forge")
def diag_forge(start: int = 200, n: int = 3, strength: float = 1.0):
    """Parity check on held-out Fault Forge seeds: planted / caught / false alarms per cabinet."""
    n = max(1, min(int(n), 10))

    def run():
        out = []
        for seed in range(start, start + n):
            meta = service.run_forge(seed=seed, strength=strength, reports=False)
            shutil.rmtree(config.RUNS / meta["id"], ignore_errors=True)
            s = meta["forge"]["score"]
            out.append(dict(seed=seed, planted=s["n_planted"], caught=s["caught"], false_alarms=len(s["false_alarms"]),
                            reviews=len(s["reviews"]), seconds=meta["timing"]["total"]))
        tot = {k: sum(r[k] for r in out) for k in ("planted", "caught", "false_alarms", "reviews")}
        return dict(version=config.VERSION, cpu=os.cpu_count(), total=tot, cabinets=out)
    return _diag(run)


# ------------------------------------------------------------------ web UI
if CLOUD:
    @app.get("/", include_in_schema=False)
    def cloud_root():
        return RedirectResponse(CONSOLE_URL)
elif (config.WEB_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            _err(404, "not found")
        f = config.WEB_DIST / path
        if path and f.is_file() and config.WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(config.WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
else:
    @app.get("/", include_in_schema=False)
    def no_ui():
        return HTMLResponse("<h2>EAGLE EYE API is running.</h2><p>The web UI is not built: run <code>npm install && "
                            "npm run build</code> in <code>eagle_eye/web</code>, or open <a href='/docs'>/docs</a>.</p>")


@app.exception_handler(InspectionError)
def _inspection_error(_, exc):
    if isinstance(exc, service.NeedPhoto):
        return JSONResponse(status_code=409, content=dict(detail="send the photo", need=["photo"]))
    return JSONResponse(status_code=422, content=dict(detail=str(exc)))


def _warm_up():
    """Pre-parse the demo drawing and raster so the first live inspection is as fast as the rest."""
    try:
        from inspector import parse_ga
        parse_ga(str(config.DEMO_GA)); service.ga_raster(config.DEMO_GA); service.ga_raster(config.DEMO_GA, dpi=110)
    except Exception:  # noqa: BLE001
        traceback.print_exc()


def main():
    ap = argparse.ArgumentParser(description="EAGLE EYE console")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    import uvicorn
    t = tesseract_info()
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host}:{a.port}"
    print("\n  EAGLE EYE console  ·  drawing-first cabinet QC")
    print(f"  {url}")
    print(f"  Tesseract: {t['version'] if t['ok'] else 'NOT FOUND - ' + t['error']}")
    print(f"  OCR workers: {config.WORKERS}\n")
    threading.Thread(target=_warm_up, daemon=True).start()
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", a.port)) == 0:
            print(f"  Port {a.port} is already in use (is EAGLE EYE already running? then just open {url}).")
            print(f"  To start a second copy: python server.py --port {a.port + 1}\n")
            raise SystemExit(1)
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
