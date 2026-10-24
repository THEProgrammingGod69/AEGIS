"""Multi-pass text reader for cabinet photos: PP-OCRv4 detection + recognition on ONNX Runtime (RapidOCR models).

Passes over one photo (every box is mapped back to photo pixels of the EXIF-transposed, full-resolution image):

  full      the whole photo, detector run at FULL_SIDE px long side; recognition always on native-resolution crops
  tile      TILE px tiles with 20 % overlap, detector run on the tile upscaled x UPSCALE (small labels, ferrules)
  tile90 / tile270   FULL mode only: rotated tiles for vertical labels (CHARM baseplate labels, N-block labels);
            one rotated detection serves both directions, each box is recognised both ways and the better read wins

The detector runs in blocks of DET_BLOCK px (bounded memory per thread, cache friendly) and tile blocks without any
text likelihood in the full pass's probability map are skipped. Boxes found twice inside one pass (tile overlaps) are
recognised once. Reads are merged across passes: same normalised text + overlapping box -> one token whose ``passes``
counts the independent passes that agree; a fragment of a longer read at the same spot is folded into it. Tokens
centred in the photo's ignore bands (watermark, timestamp) are dropped. Results are cached as JSON by
(photo sha, mode, parameters, engine version) under ``config.DATA/cache/ocr``.

RapidOCR's own pipeline is not used as a whole: it shrinks photos to 2000 px before detection *and* recognition and
its ONNX sessions disable the memory arena (2x slower detection on large inputs). This module drives the same models
with explicit detector input sizes, single-threaded sessions (one engine per worker thread) and native-resolution
recognition crops. Tesseract is the fallback only when RapidOCR / ONNX Runtime cannot be imported.

Env: EAGLE_OCR_MODE (FULL | FAST), EAGLE_OCR_WORKERS (default: CPU count), EAGLE_OCR_TILE (900),
EAGLE_OCR_UPSCALE (2.0), EAGLE_OCR_FULL_SIDE (2048), EAGLE_OCR_CACHE (1; 0 disables the cache).
"""
import hashlib
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

import config
from kb.tags import normalize
from vision.preprocess import in_bands, load_photo

ENGINE = "PP-OCRv4 (RapidOCR / ONNX Runtime)"
CACHE_VERSION = "ocr-2"


def _env(name, default, cast):
    try:
        return cast(os.environ.get(name) or default)
    except ValueError:
        return default


MODE = _env("EAGLE_OCR_MODE", "FULL", str).upper()
WORKERS = max(1, _env("EAGLE_OCR_WORKERS", os.cpu_count() or 1, int))
TILE = max(256, _env("EAGLE_OCR_TILE", 900, int))
UPSCALE = max(1.0, _env("EAGLE_OCR_UPSCALE", 2.0, float))
FULL_SIDE = max(640, _env("EAGLE_OCR_FULL_SIDE", 2048, int))
CACHE = _env("EAGLE_OCR_CACHE", "1", str) not in ("0", "false", "off")
CACHE_DIR = config.DATA / "cache" / "ocr"

OVERLAP = 0.2            # tile overlap
DET_BLOCK = 640          # detector input block (px at detector scale)
DET_BLOCK_OVERLAP = 64
DET = {"thresh": 0.3, "box_thresh": 0.5, "unclip_ratio": 1.6}
TEXT_SCORE = 0.5         # minimum recognition confidence of a read
TALL = 1.5               # box height / width above which a box is treated as vertical text
REC_HEIGHT = 48          # recognition crops are upscaled (cubic) to at least this text height
REC_CHUNK = 48           # crops per recognition job
LIKELY_PROB = 0.15       # full-pass probability that marks "some text here" (tile block gating)
ZOOM_MAX_SIDE = 2400     # read_region: cap on the scaled region's long side
PARAMS = {"tile": TILE, "upscale": UPSCALE, "full_side": FULL_SIDE, "overlap": OVERLAP, "det_block": DET_BLOCK,
          "det": DET, "text_score": TEXT_SCORE, "tall": TALL, "rec_height": REC_HEIGHT, "likely": LIKELY_PROB}
PASSES = {"FAST": ("full", "tile"), "FULL": ("full", "tile", "tile90", "tile270")}

try:
    import onnxruntime as ort
    import rapidocr_onnxruntime
    from rapidocr_onnxruntime import RapidOCR
    _BACKEND, _IMPORT_ERROR = "rapidocr", None
except Exception as e:  # noqa: BLE001 - ImportError or a broken ONNX Runtime DLL
    _BACKEND, _IMPORT_ERROR = "tesseract", f"{type(e).__name__}: {e}"

_local = threading.local()
_pools = {}
_pool_lock = threading.Lock()


# ------------------------------------------------------------------ engines
class _Rapid:
    """One PP-OCRv4 pipeline per thread: single-threaded ONNX sessions (no oversubscription across workers)."""

    def __init__(self):
        eng = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
        self.post, self.order = eng.text_det.postprocess_op, eng.text_det.order_points_clockwise
        self.post.thresh, self.post.box_thresh, self.post.unclip_ratio = DET["thresh"], DET["box_thresh"], \
            DET["unclip_ratio"]
        self.cls, self.rec = eng.text_cls, eng.text_rec
        # Own detector session with the memory arena on (RapidOCR turns it off) and shrunk after every run, so
        # memory stays bounded per thread while large inputs run ~2x faster.
        so = ort.SessionOptions()
        so.intra_op_num_threads = so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = True
        so.log_severity_level = 3
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.det = ort.InferenceSession(str(_model_path("Det")), so, providers=["CPUExecutionProvider"])
        eng.text_det.infer.session = self.det          # drop RapidOCR's own detector session
        self.det_input = self.det.get_inputs()[0].name
        self.run_opts = ort.RunOptions()
        self.run_opts.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu:0")

    def detect(self, img):
        """Text boxes of a BGR image: ``(quads [n, 4, 2] float32 clockwise from top-left, scores, prob map)``."""
        h, w = img.shape[:2]
        H, W = -(-h // 32) * 32, -(-w // 32) * 32
        if (H, W) != (h, w):
            img = cv2.copyMakeBorder(img, 0, H - h, 0, W - w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.dnn.blobFromImage(img, 1 / 127.5, mean=(127.5, 127.5, 127.5))
        pred = self.det.run(None, {self.det_input: blob}, self.run_opts)[0]
        boxes, scores = self.post(pred, (H, W))
        quads, keep = [], []
        for b, s in zip(boxes, scores):
            q = self.order(np.asarray(b, np.float32))
            q[:, 0] = np.clip(q[:, 0], 0, w)
            q[:, 1] = np.clip(q[:, 1], 0, h)
            if np.linalg.norm(q[0] - q[1]) > 3 and np.linalg.norm(q[0] - q[3]) > 3:
                quads.append(q)
                keep.append(float(s))
        return np.array(quads, np.float32).reshape(-1, 4, 2), keep, pred[0, 0, :h, :w]

    def recognize(self, crops, use_cls):
        """[(text, conf, flipped)] for horizontal-text crops; ``use_cls`` lets the classifier turn crops by 180 deg."""
        flipped = [False] * len(crops)
        if use_cls and crops:
            crops, cls_res, _ = self.cls(crops)
            flipped = [("180" in str(lab) and float(sc) > self.cls.cls_thresh) for lab, sc in cls_res]
        res, _ = self.rec(crops) if crops else ([], 0)
        return [(r[0], float(r[1]), f) for r, f in zip(res, flipped)]


class _Tess:
    """Fallback: Tesseract word boxes (detection and recognition in one call)."""

    def __init__(self):
        import pytesseract
        cmd = config.find_tesseract()
        if not cmd:
            raise RuntimeError("Tesseract OCR not found (fallback for a missing RapidOCR / ONNX Runtime); "
                               "install rapidocr-onnxruntime, or Tesseract and set TESSERACT_CMD")
        pytesseract.pytesseract.tesseract_cmd = cmd
        self.tess = pytesseract

    def read(self, img):
        d = self.tess.image_to_data(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), config="--psm 11",
                                    output_type=self.tess.Output.DICT)
        out = []
        for t, c, x, y, w, h in zip(d["text"], d["conf"], d["left"], d["top"], d["width"], d["height"]):
            if str(t).strip() and float(c) >= 0:
                q = np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
                out.append((q, str(t).strip(), float(c) / 100.0))
        return out


def _model_path(section):
    from rapidocr_onnxruntime.utils import read_yaml
    root = Path(rapidocr_onnxruntime.__file__).resolve().parent
    return root / read_yaml(root / "config.yaml")[section]["model_path"]


def _engine():
    eng = getattr(_local, "engine", None)
    if eng is None:
        eng = _local.engine = _Rapid() if _BACKEND == "rapidocr" else _Tess()
    return eng


def _pool(n):
    with _pool_lock:
        if n not in _pools:
            _pools[n] = ThreadPoolExecutor(n, thread_name_prefix=f"ee-ocr{n}")
        return _pools[n]


def engine_info():
    """Which OCR engine is used, its version and whether it can run (health checks, UI status)."""
    info = {"engine": ENGINE, "version": None, "ok": False, "fallback": None, "mode": MODE, "workers": WORKERS}
    if _BACKEND == "rapidocr":
        try:
            from importlib.metadata import version
            info["version"] = f"rapidocr-onnxruntime {version('rapidocr_onnxruntime')}, onnxruntime {ort.__version__}"
            _engine()
            info["ok"] = True
        except Exception as e:  # noqa: BLE001 - surfaced as a setup hint
            info["error"] = f"{type(e).__name__}: {e}"
        return info
    info.update(engine="Tesseract (fallback)", fallback="tesseract", import_error=_IMPORT_ERROR)
    try:
        import subprocess
        _engine()
        out = subprocess.run([config.find_tesseract(), "--version"], capture_output=True, text=True, timeout=10)
        info["version"] = (out.stdout or out.stderr).splitlines()[0].strip()
        info["ok"] = True
    except Exception as e:  # noqa: BLE001
        info["error"] = f"{type(e).__name__}: {e}"
    return info


# ------------------------------------------------------------------ geometry
_ROTATE = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 270: cv2.ROTATE_90_CLOCKWISE}


def rotate_frame(img, rot):
    """Turn an image so that text with clockwise rotation ``rot`` (90: reads top-to-bottom) becomes horizontal."""
    return img if rot == 0 else cv2.rotate(img, _ROTATE[rot])


def frame_to_image(pts, rot, w, h):
    """Map points of ``rotate_frame(img, rot)`` back to ``img`` (``w`` x ``h``); continuous pixel coordinates."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    if rot == 90:       # frame (u, v) = (y, w - x)
        return np.stack([w - pts[:, 1], pts[:, 0]], 1)
    if rot == 270:      # frame (u, v) = (h - y, x)
        return np.stack([pts[:, 1], h - pts[:, 0]], 1)
    return pts.copy()


def image_to_frame(pts, rot, w, h):
    """Inverse of :func:`frame_to_image`."""
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    if rot == 90:
        return np.stack([pts[:, 1], w - pts[:, 0]], 1)
    if rot == 270:
        return np.stack([h - pts[:, 1], pts[:, 0]], 1)
    return pts.copy()


def _bbox(q):
    q = np.asarray(q).reshape(-1, 2)
    return [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())]


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b):
    """Intersection over union of two ``[x0, y0, x1, y1]`` boxes."""
    i = _inter(a, b)
    return i / (_area(a) + _area(b) - i + 1e-9)


def _text_rot(q):
    """Clockwise rotation of the reading direction (top-left -> top-right edge), snapped to 0/90/180/270."""
    d = q[1] - q[0]
    return int(round(math.degrees(math.atan2(d[1], d[0])) / 90.0)) % 4 * 90


def _windows(n, size, overlap):
    if n <= size:
        return [0]
    step = max(1, int(size * (1 - overlap)))
    xs = list(range(0, n - size + 1, step))
    if xs[-1] + size < n:
        xs.append(n - size)
    return xs


def _split(n, size, overlap_px):
    """Evenly spaced ``(start, length)`` windows of at most ~``size`` (10 % slack) covering ``n`` with overlap."""
    if n <= size * 1.1:
        return [(0, n)]
    k = math.ceil((n - overlap_px) / (size * 1.1 - overlap_px))
    length = min(n, math.ceil((n + (k - 1) * overlap_px) / k))
    return [(round(i * (n - length) / (k - 1)), length) for i in range(k)]


def _split_region(region, size, overlap_px):
    x0, y0, x1, y1 = region
    return [[x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh] for by, bh in _split(y1 - y0, size, overlap_px)
            for bx, bw in _split(x1 - x0, size, overlap_px)]


def tiles(w, h, size=TILE, overlap=OVERLAP):
    """``[x0, y0, x1, y1]`` windows of ``size`` px covering a ``w`` x ``h`` image with the given overlap."""
    return [[x, y, min(w, x + size), min(h, y + size)] for y in _windows(h, size, overlap)
            for x in _windows(w, size, overlap)]


class _Grid:
    """Spatial hash of boxes for overlap queries."""

    def __init__(self, cell=256):
        self.cell, self.cells = cell, {}

    def _keys(self, b):
        c = self.cell
        for gx in range(int(b[0] // c), int(b[2] // c) + 1):
            for gy in range(int(b[1] // c), int(b[3] // c) + 1):
                yield gx, gy

    def add(self, b, item):
        for k in self._keys(b):
            self.cells.setdefault(k, []).append(item)

    def near(self, b):
        seen = set()
        for k in self._keys(b):
            for it in self.cells.get(k, ()):
                if id(it) not in seen:
                    seen.add(id(it))
                    yield it


# ------------------------------------------------------------------ detection jobs
def _detect_image(eng, img, want_map=False):
    """Detect in DET_BLOCK blocks; returns quads (image coords), scores and (optionally) the stitched prob map."""
    h, w = img.shape[:2]
    pmap = np.zeros((h, w), np.float32) if want_map else None
    blocks = _split_region([0, 0, w, h], DET_BLOCK, DET_BLOCK_OVERLAP)
    found = []
    for x0, y0, x1, y1 in blocks:
        q, s, p = eng.detect(np.ascontiguousarray(img[y0:y1, x0:x1]))
        if pmap is not None:
            np.maximum(pmap[y0:y1, x0:x1], p, out=pmap[y0:y1, x0:x1])
        found += [(qq + (x0, y0), ss) for qq, ss in zip(q, s)]
    if len(blocks) > 1:
        found = _dedupe_boxes(found)
    return [f[0] for f in found], [f[1] for f in found], pmap


def _dedupe_boxes(found, thr=0.5):
    """Drop boxes that are (mostly) inside a larger one: block / tile overlaps detect the same text twice."""
    found = sorted(found, key=lambda f: -_area(_bbox(f[0])))
    grid, keep = _Grid(), []
    for q, s in found:
        b = _bbox(q)
        a = _area(b)
        if any(_inter(b, k) / (a + 1e-9) > thr for k in grid.near(b)):
            continue
        grid.add(b, b)
        keep.append((q, s))
    return keep


def _det_job(bgr, pass_id, rot, region, scale, gate=None, want_map=False):
    """Detection over one region (photo coords) seen through rotation ``rot`` at ``scale``; quads in photo coords."""
    x0, y0, x1, y1 = region
    sub = bgr[y0:y1, x0:x1]
    rw, rh = x1 - x0, y1 - y0
    if gate is not None and not gate(region):
        return {"pass": pass_id, "rot": rot, "quads": [], "scores": [], "skipped": True, "reads": None}
    frame = rotate_frame(sub, rot)
    if scale != 1.0:
        fh, fw = frame.shape[:2]
        frame = cv2.resize(frame, (max(1, round(fw * scale)), max(1, round(fh * scale))),
                           interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    eng = _engine()
    if isinstance(eng, _Tess):
        reads = []
        for q, t, c in eng.read(frame):
            qq = frame_to_image(q / scale, rot, rw, rh) + (x0, y0)
            reads.append((qq.astype(np.float32), t, c))
        return {"pass": pass_id, "rot": rot, "quads": [r[0] for r in reads], "scores": [1.0] * len(reads),
                "skipped": False, "reads": reads}
    quads, scores, pmap = _detect_image(eng, frame, want_map)
    out = [(frame_to_image(q / scale, rot, rw, rh) + (x0, y0)).astype(np.float32) for q in quads]
    return {"pass": pass_id, "rot": rot, "quads": out, "scores": scores, "skipped": False, "reads": None,
            "pmap": pmap}


# ------------------------------------------------------------------ recognition jobs
def _crop(rgb_or_bgr, quad, shift=0):
    """Perspective crop of ``quad`` (reading order) upscaled to REC_HEIGHT; ``shift`` turns it by 90 deg steps."""
    q = np.roll(np.asarray(quad, np.float32).reshape(4, 2), -shift, axis=0)
    w = max(np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[2] - q[3]))
    h = max(np.linalg.norm(q[0] - q[3]), np.linalg.norm(q[1] - q[2]))
    s = min(4.0, max(1.0, REC_HEIGHT / max(h, 1.0)))
    W, H = max(2, int(round(w * s))), max(2, int(round(h * s)))
    if W > 64 * H:                                    # absurdly long boxes are never labels
        W = 64 * H
    M = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [W, 0], [W, H], [0, H]]))
    return cv2.warpPerspective(rgb_or_bgr, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE), q


def _rec_job(bgr, items):
    """Recognise items ``(pass_id, quad, strategy)``; returns raw reads ``(pass_id, quad, text, conf)``.

    strategy "auto": horizontal box -> as is + 180 deg classifier; tall box -> as is, 90 and 270 deg, best wins.
    strategy "both": rotated-frame box -> as is and 180 deg, best wins (vertical text of either direction).
    strategy "cls": as is + 180 deg classifier only.
    """
    eng = _engine()
    cls_crops, cls_idx, plain, plain_idx = [], [], [], []
    for i, (pid, q, strategy) in enumerate(items):
        if strategy in ("auto", "cls"):
            w = np.linalg.norm(q[0] - q[1])
            h = np.linalg.norm(q[0] - q[3])
            if strategy == "cls" or h < TALL * w:
                c, qq = _crop(bgr, q, 0)
                cls_crops.append(c)
                cls_idx.append((i, qq))
                continue
            shifts = (0, 1, 3)
        else:
            shifts = (0, 2)
        for s in shifts:
            c, qq = _crop(bgr, q, s)
            plain.append(c)
            plain_idx.append((i, qq))
    best = {}
    for (i, qq), (t, c, flipped) in zip(cls_idx, eng.recognize(cls_crops, True)):
        best[i] = (np.roll(qq, -2, axis=0) if flipped else qq, t, c)
    for (i, qq), (t, c, _) in zip(plain_idx, eng.recognize(plain, False)):
        if i not in best or c > best[i][2]:
            best[i] = (qq, t, c)
    out = []
    for i, (pid, _q, strategy) in enumerate(items):
        if i in best:
            qq, t, c = best[i]
            out.append((pid, qq, t, c))
    return out


# ------------------------------------------------------------------ merging
def _read(pid, quad, text, conf):
    q = np.asarray(quad, np.float64).reshape(4, 2)
    rot = _text_rot(q)
    if pid in ("tile90", "tile270"):
        pid = pid[:-3] + ("270" if rot == 270 else "90")
    return {"text": text, "norm": normalize(text), "quad": q, "box": _bbox(q), "conf": float(conf), "pass": pid,
            "rot": rot}


def merge(reads, ignore=()):
    """Merge raw reads from several passes into tokens (see module docstring)."""
    reads = [r for r in reads if r["norm"] and r["conf"] >= TEXT_SCORE
             and not in_bands((r["box"][0] + r["box"][2]) / 2, (r["box"][1] + r["box"][3]) / 2, ignore)]
    groups = []
    by_norm = {}
    for r in sorted(reads, key=lambda r: -r["conf"]):
        for g in by_norm.get(r["norm"], ()):
            if any(iou(r["box"], o["box"]) >= 0.3 for o in g):
                g.append(r)
                break
        else:
            g = [r]
            by_norm.setdefault(r["norm"], []).append(g)
            groups.append(g)
    tokens = []
    for g in groups:
        b = g[0]
        support = sorted({r["pass"] for r in g})
        tokens.append({"text": b["text"], "norm": b["norm"], "box": [round(v, 1) for v in b["box"]],
                       "quad": [[round(float(x), 1), round(float(y), 1)] for x, y in b["quad"]],
                       "conf": round(b["conf"], 4), "rot": b["rot"],
                       "pass": "".join(ch for ch in b["pass"] if not ch.isdigit()), "passes": len(support),
                       "support": support,
                       "variants": [{"text": r["text"], "conf": round(r["conf"], 4), "pass": r["pass"], "rot": r["rot"],
                                     "box": [round(v, 1) for v in r["box"]]} for r in g]})
    # Fold fragments ('CB1' inside 'CB11', 'PS12-L' inside 'CB12-2/PS12-L') into the longer read at the same spot,
    # unless the fragment is supported by more passes than the longer read.
    tokens.sort(key=lambda t: (-t["passes"], -len(t["norm"]), -t["conf"]))
    grid, keep = _Grid(), []
    for t in tokens:
        a = _area(t["box"])
        host = next((k for k in grid.near(t["box"]) if t["norm"] in k["norm"] and len(t["norm"]) < len(k["norm"])
                     and t["passes"] <= k["passes"] and _inter(t["box"], k["box"]) / (a + 1e-9) >= 0.6), None)
        if host is not None:
            host["variants"].extend(dict(v, fragment=True) for v in t["variants"])
            continue
        grid.add(t["box"], t)
        keep.append(t)
    keep.sort(key=lambda t: (t["box"][1], t["box"][0]))
    return keep


# ------------------------------------------------------------------ passes
def _likelihood_gate(pmap, scale, frac=0.002):
    """Gate for tile regions: True when the full-pass probability map shows any text-like response there."""
    if pmap is None:
        return None
    mask = (pmap > LIKELY_PROB).astype(np.uint8)
    integral = cv2.integral(mask)

    def gate(region):
        x0, y0, x1, y1 = (int(round(v * scale)) for v in region)
        x1, y1 = min(x1, mask.shape[1]), min(y1, mask.shape[0])
        if x1 <= x0 or y1 <= y0:
            return False
        n = integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0]
        return n >= frac * (x1 - x0) * (y1 - y0)
    return gate


def _dedupe_pass(results):
    """Unique boxes of one pass (tile and block overlaps) as (pass_id, quad)."""
    found = [(q, s) for r in results for q, s in zip(r["quads"], r["scores"])]
    return _dedupe_boxes(found, thr=0.6)


def _run(photo, mode, workers, info):
    bgr = cv2.cvtColor(photo["rgb"], cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    pool = _pool(workers)
    passes = PASSES.get(mode, PASSES["FULL"])
    t0 = time.perf_counter()
    stats = {"det_jobs": {}, "det_skipped": {}, "rec_boxes": {}}

    # 1. full pass: whole photo at FULL_SIDE, detector blocks in parallel; its probability map gates the tiles
    fscale = min(1.0, FULL_SIDE / max(h, w))
    full_regions = _split_region([0, 0, w, h], DET_BLOCK / fscale, DET_BLOCK_OVERLAP / fscale)
    jobs = {"full": [pool.submit(_det_job, bgr, "full", 0, r, fscale, None, True) for r in full_regions]}
    full = [f.result() for f in jobs["full"]]
    pmap = _stitch([r.get("pmap") for r in full], full_regions, fscale, h, w)
    gate = _likelihood_gate(pmap, fscale)
    stats["t_full_det"] = round(time.perf_counter() - t0, 2)

    # 2. tile passes: TILE windows upscaled, split into detector blocks; the rotated pass serves 90 and 270 deg
    for pid in passes[1:]:
        if pid == "tile270":
            continue
        rot = 90 if pid == "tile90" else 0
        regs = [b for t in tiles(w, h) for b in _split_region(t, DET_BLOCK / UPSCALE, DET_BLOCK_OVERLAP / UPSCALE)]
        jobs[pid] = [pool.submit(_det_job, bgr, pid, rot, r, UPSCALE, gate) for r in regs]

    # 3. recognition per pass as soon as its detections are in (boxes found twice in one pass are read once)
    raw, rec_futs = [], []
    for pid, futs in jobs.items():
        results = full if pid == "full" else [f.result() for f in futs]
        stats["det_jobs"][pid] = len(results)
        stats["det_skipped"][pid] = sum(1 for r in results if r["skipped"])
        if results and results[0]["reads"] is not None:          # Tesseract fallback: reads come with the boxes
            raw += [(pid, q, t, c) for r in results for q, t, c in r["reads"]]
            continue
        strategy = "both" if pid == "tile90" else "auto"
        items = [(pid, q, strategy) for q, _s in _dedupe_pass(results) if _recognisable(q, strategy)]
        stats["rec_boxes"][pid] = len(items)
        items.sort(key=lambda it: _aspect(it[1]))
        rec_futs += [pool.submit(_rec_job, bgr, items[i:i + REC_CHUNK]) for i in range(0, len(items), REC_CHUNK)]
    stats["t_det"] = round(time.perf_counter() - t0, 2)
    for f in rec_futs:
        raw.extend(f.result())
    reads = [_read(pid, q, t, c) for pid, q, t, c in raw]
    tokens = merge(reads, photo.get("ignore") or ())
    stats.update(reads=len(reads), tokens=len(tokens), seconds=round(time.perf_counter() - t0, 2))
    info.update(stats)
    return tokens


def _stitch(maps, regions, scale, h, w):
    """Full-photo probability map (at ``scale``) from per-region maps."""
    if any(m is None for m in maps):
        return None
    out = np.zeros((max(1, round(h * scale)), max(1, round(w * scale))), np.float32)
    for m, (x0, y0, _x1, _y1) in zip(maps, regions):
        X, Y = round(x0 * scale), round(y0 * scale)
        hh, ww = min(m.shape[0], out.shape[0] - Y), min(m.shape[1], out.shape[1] - X)
        if hh > 0 and ww > 0:
            np.maximum(out[Y:Y + hh, X:X + ww], m[:hh, :ww], out=out[Y:Y + hh, X:X + ww])
    return out


def _recognisable(q, strategy):
    """Skip boxes that cannot be a label read: absurd aspect ratios, and (rotated passes) boxes that are vertical
    in the rotated frame, i.e. horizontal in the photo, which the 0-degree passes read already."""
    wq, hq = np.linalg.norm(q[0] - q[1]), np.linalg.norm(q[0] - q[3])
    if max(wq, hq) > 40 * max(1.0, min(wq, hq)):
        return False
    return not (strategy == "both" and hq >= TALL * wq * 0.8)


def _aspect(q):
    w = np.linalg.norm(q[0] - q[1])
    h = np.linalg.norm(q[0] - q[3])
    return max(w, h) / max(1.0, min(w, h))


def _cache_path(photo, mode):
    key = json.dumps({"v": CACHE_VERSION, "sha": photo["sha"], "mode": mode, "params": PARAMS,
                      "ignore": photo.get("ignore"), "engine": engine_info().get("version"), "backend": _BACKEND},
                     sort_keys=True)
    return CACHE_DIR / f"{photo['sha']}_{mode}_{hashlib.sha256(key.encode()).hexdigest()[:12]}.json"


def read_photo(photo, mode=None, workers=None, info=None):
    """Read all text in a photo -> list of Token dicts (spec section 4), cached on disk.

    ``photo`` is a :func:`vision.preprocess.load_photo` dict (or a path). ``mode`` FULL | FAST (default
    EAGLE_OCR_MODE), ``workers`` threads (default EAGLE_OCR_WORKERS). ``info`` (optional dict) receives timings and
    pass statistics. Token: ``{text, norm, box, quad, conf, rot, pass, passes, support, variants}``.
    """
    if not isinstance(photo, dict):
        photo = load_photo(photo)
    mode = (mode or MODE).upper()
    workers = max(1, int(workers or WORKERS))
    info = {} if info is None else info
    path = _cache_path(photo, mode) if CACHE else None
    if path is not None and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            info.update(data.get("stats", {}), cached=True)
            return data["tokens"]
        except (ValueError, KeyError, OSError):
            pass
    tokens = _run(photo, mode, workers, info)
    info.update(cached=False, mode=mode, workers=workers)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({"stats": info, "tokens": tokens}), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
    return tokens


def read_region(photo, box, rotations=(0, 90, 270), scale=3.0):
    """Targeted zoom re-read of ``box`` ``[x0, y0, x1, y1]`` (photo px) at ``scale`` for each text rotation.

    Used by the MISSING check and the agent's ``ocr_region`` tool; tokens are in photo coordinates with
    ``pass == "zoom"`` and support ids ``zoom`` / ``zoom90`` / ``zoom270``. Runs in the calling thread (safe to call
    from worker threads); not cached.
    """
    if not isinstance(photo, dict):
        photo = load_photo(photo)
    rgb = photo["rgb"]
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (float(v) for v in box)
    m = max(8.0, 0.1 * max(x1 - x0, y1 - y0))
    region = [int(max(0, math.floor(x0 - m))), int(max(0, math.floor(y0 - m))),
              int(min(w, math.ceil(x1 + m))), int(min(h, math.ceil(y1 + m)))]
    if region[2] - region[0] < 4 or region[3] - region[1] < 4:
        return []
    bgr = np.ascontiguousarray(cv2.cvtColor(rgb[region[1]:region[3], region[0]:region[2]], cv2.COLOR_RGB2BGR))
    sub = [0, 0, region[2] - region[0], region[3] - region[1]]
    s = max(1.0, min(float(scale), ZOOM_MAX_SIDE / max(sub[2], sub[3])))
    raw = []
    for rot in rotations:
        pid = "zoom" if rot == 0 else f"zoom{rot}"
        det = _det_job(bgr, pid, rot, sub, s)
        if det["reads"] is not None:
            raw += [(pid, q, t, c) for q, t, c in det["reads"]]
            continue
        strategy = "auto" if rot == 0 else "cls"
        items = [(pid, q, strategy) for q in det["quads"] if _recognisable(q, "both" if rot else "auto")]
        raw += _rec_job(bgr, items) if items else []
    reads = [_read(pid, np.asarray(q, np.float64) + (region[0], region[1]), t, c) for pid, q, t, c in raw]
    return merge(reads, photo.get("ignore") or ())
