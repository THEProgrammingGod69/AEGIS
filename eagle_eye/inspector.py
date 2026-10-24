"""EAGLE EYE inspection engine.

Drawing-first, closed-world verification:
  1. Parse the GA drawing PDF (vector) -> exact list of expected items + positions. No AI.
  2. Register the photo to the drawing: backplate quad (coarse) + device labels as fiducials (RANSAC refine).
  3. Run plug-in checks, each answering a narrow question about ONE expected item in ONE known region.
  4. Consensus: an item is FAIL only when evidence agrees; disagreement -> REVIEW (re-photo zone).

Adding a check = one class decorated with ``@check("NAME")``; nothing else needs rewriting.
OCR calls run in parallel (one single-threaded tesseract process per core), so a full inspection takes a
few seconds on a laptop instead of ~20 s, with results identical to the sequential version.
"""
import copy
import difflib
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pymupdf
import pytesseract
from openpyxl import load_workbook

import config

R = 4  # rectified px per mm
WL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-/+:"

_TESS = config.find_tesseract()
if _TESS:
    pytesseract.pytesseract.tesseract_cmd = _TESS

# Two pools so per-item work (outer) can wait on OCR calls (inner) without ever deadlocking:
# inner tasks never submit further work.
_OCR = ThreadPoolExecutor(config.WORKERS, thread_name_prefix="ee-ocr")
_ITEMS = ThreadPoolExecutor(config.WORKERS, thread_name_prefix="ee-item")


class InspectionError(RuntimeError):
    """A problem with the inputs that the user can fix (unreadable photo, wrong drawing format...)."""


def pmap(fn, items):
    """Order-preserving parallel map for independent per-item work."""
    return list(_ITEMS.map(fn, items))


def tesseract_info():
    """Which tesseract binary is used and its version (for health checks and the UI status pill)."""
    cmd = pytesseract.pytesseract.tesseract_cmd
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
        ver = (out.stdout or out.stderr).splitlines()[0].strip()
        return dict(ok=True, cmd=cmd, version=ver, backend="libtesseract in-process" if _CAPI else "tesseract CLI")
    except Exception as e:  # noqa: BLE001 - surfaced to the UI as a setup hint
        return dict(ok=False, cmd=cmd, version=None,
                    error=f"Tesseract OCR not found ({e}). Install it or set TESSERACT_CMD.")


# ------------------------------------------------------------------ 1. drawing parser
TYPE_BY_PREFIX = [(r"^\d*CBP\d+", "baseplate"), (r"^CB\d+", "breaker"), (r"^PS\d+", "psu"),
                  (r"^D\d+", "controller"), (r"^PE$", "earth")]

_GA_CACHE = {}


def parse_ga(pdf_path):
    """Vector GA drawing -> exact list of devices, terminals and rails (mm, origin top-left). Cached."""
    st = os.stat(pdf_path)
    key = (os.path.abspath(pdf_path), st.st_mtime_ns, st.st_size)
    if key not in _GA_CACHE:
        _GA_CACHE[key] = _parse_ga(pdf_path)
    return copy.deepcopy(_GA_CACHE[key])


def _parse_ga(pdf_path):
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:  # noqa: BLE001
        raise InspectionError(f"Could not open the GA drawing PDF ({e}).") from e
    with doc:
        page = doc[0]
        rects = []
        for d in page.get_drawings():
            for it in d["items"]:
                if it[0] == "re":
                    rects.append(pymupdf.Rect(it[1]))
        words = page.get_text("words")
        text = page.get_text()
    if not rects:
        raise InspectionError("The GA drawing has no vector outlines. EAGLE EYE needs a vector (CAD-exported) "
                              "PDF; scanned drawings are not supported yet.")
    m = re.search(r"BACKPLATE\s+(\d+)\s*x\s*(\d+)\s*mm", text)
    Wmm, Hmm = (int(m.group(1)), int(m.group(2))) if m else (600, 800)
    cab = re.search(r"CABINET\s+([A-Z0-9][A-Z0-9_.\-]*)", text)
    bp = max(rects, key=lambda r: r.width * r.height)
    k = Wmm / bp.width
    mm = lambda r: (round((r.x0 - bp.x0) * k, 1), round((r.y0 - bp.y0) * k, 1),
                    round(r.width * k, 1), round(r.height * k, 1))
    inner = [r for r in rects if r != bp]
    devices, terminals = [], []
    for w in words:
        wr = pymupdf.Rect(w[:4]); txt = w[4]
        if not bp.contains(wr):
            continue
        c = pymupdf.Point((wr.x0 + wr.x1) / 2, (wr.y0 + wr.y1) / 2)
        enc = sorted([r for r in inner if r.contains(c)], key=lambda r: r.width * r.height)
        if re.match(r"^X\d+:\d+$", txt):
            if enc:
                terminals.append(dict(tag=txt, n=int(txt.split(":")[1]), box=mm(enc[0])))
            continue
        typ = next((t for p, t in TYPE_BY_PREFIX if re.match(p, txt)), None)
        if typ is None or not enc:
            continue
        lx, ly, lw, lh = mm(wr)
        devices.append(dict(tag=txt, type=typ, box=mm(enc[0]),
                            label_box=(lx - 2, ly - 2.5, lw + 4, lh + 5)))
    if not devices:
        raise InspectionError("No device tags (PS.., CB.., D.., ..CBP.., PE) were found inside the backplate "
                              "outline of the GA drawing.")
    # group breakers sharing a rail (same top y) and sort left->right
    groups = {}
    for d in devices:
        if d["type"] == "breaker":
            groups.setdefault(round(d["box"][1] / 10), []).append(d)
    rails = []
    for i, (_, g) in enumerate(sorted(groups.items())):
        g.sort(key=lambda d: d["box"][0])
        for d in g:
            d["group"] = f"RAIL-{i+1}"
        rails.append(dict(name=f"RAIL-{i+1}", tags=[d["tag"] for d in g]))
    terminals.sort(key=lambda t: t["n"])
    return dict(size=(Wmm, Hmm), devices=devices, terminals=terminals, rails=rails,
                cabinet=cab.group(1) if cab else os.path.splitext(os.path.basename(pdf_path))[0])


def read_wire_list(path):
    try:
        ws = load_workbook(path, read_only=True, data_only=True).active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:  # noqa: BLE001
        raise InspectionError(f"Could not read the wire list workbook ({e}).") from e
    if not rows:
        raise InspectionError("The wire list is empty.")
    hdr = [str(h).lower() for h in rows[0]]

    def col(*keys):
        for key in keys:
            for i, h in enumerate(hdr):
                if key in h:
                    return i
        raise InspectionError(f"The wire list needs a column whose header contains '{keys[0]}' "
                              f"(found headers: {', '.join(map(str, rows[0]))}).")
    ti, fi, ci = col("terminal"), col("ferrule"), col("colour", "color")
    return [dict(terminal=r[ti], ferrule=r[fi], colour=r[ci]) for r in rows[1:] if r[ti]]


def read_checklist(path):
    ws = load_workbook(path).active
    return [dict(id=r[0], check=r[1], desc=r[2]) for r in list(ws.iter_rows(values_only=True))[1:] if r[0]]


# ------------------------------------------------------------------ 2. registration
def order_quad(p):
    p = p.reshape(4, 2).astype(np.float32)
    s, d = p.sum(1), np.diff(p, axis=1).ravel()
    return np.float32([p[np.argmin(s)], p[np.argmin(d)], p[np.argmax(s)], p[np.argmax(d)]])


def find_backplate(img):
    """Segment everything that is not the cabinet frame (colour sampled at the photo border)."""
    sm = cv2.GaussianBlur(img, (0, 0), 3).astype(np.float32)
    border = np.concatenate([sm[:20].reshape(-1, 3), sm[-20:].reshape(-1, 3), sm[:, :20].reshape(-1, 3), sm[:, -20:].reshape(-1, 3)])
    bg = np.median(border, 0)
    th = (np.linalg.norm(sm - bg, axis=2) > 45).astype(np.uint8) * 255
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((41, 41), np.uint8))
    cs, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        raise InspectionError("Could not find the backplate in the photo. Shoot the whole backplate with some "
                              "cabinet frame visible around it.")
    c = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.15 * img.shape[0] * img.shape[1]:
        raise InspectionError("The backplate covers too little of the photo. Step back so the whole backplate "
                              "fills most of the frame.")
    hull = cv2.convexHull(c)
    for eps in np.linspace(0.005, 0.06, 24):
        ap = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(ap) == 4:
            return order_quad(ap)
    return order_quad(cv2.boxPoints(cv2.minAreaRect(c)))


def norm(s):
    s = (s or "").upper().strip()
    return re.sub(r"[^A-Z0-9]", "", s.replace("O", "0").replace("I", "1"))


def ocr_words(img_gray, psm=11):
    d = pytesseract.image_to_data(img_gray, config=f"--psm {psm} -c tessedit_char_whitelist={WL}",
                                  output_type=pytesseract.Output.DICT)
    out = []
    for i, t in enumerate(d["text"]):
        if t.strip() and float(d["conf"][i]) > 30:
            out.append(dict(text=t.strip(), conf=float(d["conf"][i]),
                            box=(d["left"][i], d["top"][i], d["width"][i], d["height"][i])))
    return out


def _warp_pts(H, pts):
    return cv2.perspectiveTransform(np.float32(pts).reshape(1, -1, 2), np.asarray(H, np.float64))[0]


def register(photo, ga, wires=()):
    Wmm, Hmm = ga["size"]
    quad = find_backplate(photo)
    dst = np.float32([[0, 0], [Wmm * R, 0], [Wmm * R, Hmm * R], [0, Hmm * R]])
    Hc = cv2.getPerspectiveTransform(quad, dst)
    rect = cv2.warpPerspective(photo, Hc, (Wmm * R, Hmm * R), flags=cv2.INTER_CUBIC)
    # label fiducials: look for each tag near where the drawing says its label is (closed vocabulary)
    targets = [dict(tag=d["tag"], label_box=d["label_box"], kind="label") for d in ga["devices"]]
    for t, w in zip(ga["terminals"], wires):   # ferrules are fiducials too (closed vocabulary from wire list)
        x, y, tw, th = t["box"]
        targets.append(dict(tag=w["ferrule"], label_box=(x + tw + 4, y + th / 2 - 8, 66, 16), kind="ferrule"))
    vocab = {norm(d["tag"]): d for d in targets}
    tags = [v["tag"] for v in vocab.values()]

    def look(d):
        lx, ly, lw, lh = d["label_box"]; pad = 10
        x0, y0 = int(max(0, (lx - pad) * R)), int(max(0, (ly - pad) * R))
        win = rect[y0:int((ly + lh + pad) * R), x0:int((lx + lw + pad) * R)]
        win = cv2.cvtColor(cv2.cvtColor(win, cv2.COLOR_RGB2GRAY), cv2.COLOR_GRAY2RGB)
        best, agr, raw = vote(ocr_variants(win, fast=True), tags)
        return x0, y0, best, agr, find_sticker(win)

    src, dstp, matched = [], [], []
    for x0, y0, best, agr, st in pmap(look, targets):
        if best and agr >= 1.0 and st:
            e = vocab[norm(best)]; x, y, bw, bh = st
            ex, ey, ew, eh = e["label_box"]
            src.append((x0 + x + bw / 2, y0 + y + bh / 2))
            dstp.append(((ex + ew / 2) * R, (ey + eh / 2) * R)); matched.append(e)
    info = dict(quad=quad.tolist(), anchors=len(src), inliers=0, outliers=[], refined=False, targets=len(targets))
    H = Hc
    mask = np.ones(len(src), bool)
    ransac = False
    if len(src) >= 6:
        Hr, m = cv2.findHomography(np.float32(src), np.float32(dstp), cv2.RANSAC, 6 * R)
        if Hr is not None:
            ransac = True
            mask = m.ravel().astype(bool)
            info["inliers"] = int(mask.sum())
            info["outliers"] = [e["tag"] for e, k in zip(matched, mask) if not k]
            # only accept a refinement that is small (sanity guard)
            corners = cv2.perspectiveTransform(dst[None], Hr)[0]
            if np.abs(corners - dst).max() < 15 * R:
                H = Hr @ Hc
                info["refined"] = True
                rect = cv2.warpPerspective(photo, H, (Wmm * R, Hmm * R), flags=cv2.INTER_CUBIC)
    # anchor geometry for the UI: where each fiducial was found vs where the drawing expects it
    if src:
        found_rect = _warp_pts(H @ np.linalg.inv(Hc), src)
        found_px = _warp_pts(np.linalg.inv(Hc), src)
        exp_px = _warp_pts(np.linalg.inv(H), dstp)
        info["anchor_points"] = [
            dict(tag=e["tag"], kind=e["kind"], inlier=bool(k) if ransac else None,
                 found_px=[round(float(v), 1) for v in fp], expected_px=[round(float(v), 1) for v in ep],
                 found_mm=[round(float(v) / R, 1) for v in fr], expected_mm=[round(v / R, 1) for v in de],
                 residual_mm=round(float(np.hypot(*(fr - np.float32(de)))) / R, 2))
            for e, k, fp, ep, fr, de in zip(matched, mask, found_px, exp_px, found_rect, dstp)]
    else:
        info["anchor_points"] = []
    return rect, H, info


# ------------------------------------------------------------------ helpers on the rectified image
def crop(img, box, pad=0):
    x, y, w, h = box
    x0, y0 = int(max(0, (x - pad) * R)), int(max(0, (y - pad) * R))
    x1, y1 = int(min(img.shape[1], (x + w + pad) * R)), int(min(img.shape[0], (y + h + pad) * R))
    return img[y0:y1, x0:x1]


class Backplate:
    """Illumination-aware model of the empty backplate colour (fit on free space from the drawing)."""
    def __init__(self, rect, ga):
        Wmm, Hmm = ga["size"]
        mask = np.ones((Hmm * R, Wmm * R), bool)
        for d in ga["devices"]:
            x, y, w, h = d["box"]; mask[int((y - 8) * R):int((y + h + 8) * R), int((x - 8) * R):int((x + w + 8) * R)] = False
        for t in ga["terminals"]:
            x, y, w, h = t["box"]; mask[int((y - 10) * R):int((y + h + 10) * R), int((x - 10) * R):] = False
        mask[int(180 * R):int(230 * R), :] = False; mask[:, int(325 * R):int(375 * R)] = False  # ducts (PoC)
        mask[:20 * R] = False; mask[-20 * R:] = False; mask[:, :15 * R] = False; mask[:, -15 * R:] = False
        ys, xs = np.nonzero(mask[::8, ::8]); ys *= 8; xs *= 8
        A = np.c_[np.ones_like(xs), xs / 1000, ys / 1000, (xs / 1000) ** 2, (ys / 1000) ** 2, xs * ys / 1e6].astype(np.float32)
        Y = rect[ys, xs].astype(np.float32)
        self.coef, *_ = np.linalg.lstsq(A, Y, rcond=None)

    def predict(self, box):
        x, y, w, h = box
        xs, ys = np.meshgrid(np.arange(int(x * R), int((x + w) * R)), np.arange(int(y * R), int((y + h) * R)))
        A = np.stack([np.ones_like(xs), xs / 1000, ys / 1000, (xs / 1000) ** 2, (ys / 1000) ** 2, xs * ys / 1e6], -1).astype(np.float32)
        return A @ self.coef


def occupancy(rect, bpm, box, shrink=0.12):
    x, y, w, h = box
    b = (x + w * shrink, y + h * shrink, w * (1 - 2 * shrink), h * (1 - 2 * shrink))
    c = crop(rect, b).astype(np.float32); p = bpm.predict(b)[:c.shape[0], :c.shape[1]]
    dist = np.linalg.norm(c - p, axis=2)
    return float((dist > 38).mean())


def white_fraction(rect, bpm, box, shrink=0.15):
    x, y, w, h = box
    b = (x + w * shrink, y + h * shrink, w * (1 - 2 * shrink), h * (1 - 2 * shrink))
    c = crop(rect, b).astype(np.float32); p = bpm.predict(b)[:c.shape[0], :c.shape[1]]
    bright = c.mean(2) / np.maximum(p.mean(2), 1)
    sat = c.max(2) - c.min(2)
    return float(((bright > 1.10) & (sat < 45)).mean())


def find_outlined(img):
    """Find a printed label by its rectangular outline (works even when label and background are both bright)."""
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    e = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 30, 90)
    e = cv2.dilate(e, np.ones((2, 2), np.uint8))
    cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    H_, W_ = g.shape; best, bd = None, 1e9
    for c in cs:
        x, y, w, h = cv2.boundingRect(c)
        if not (0.06 * W_ * H_ < w * h < 0.8 * W_ * H_) or h < 14 or w < h * 1.3:
            continue
        ap = cv2.approxPolyDP(c, 0.04 * cv2.arcLength(c, True), True)
        if len(ap) != 4 or cv2.contourArea(ap) < 0.75 * w * h:
            continue
        inner = g[y + h // 6:y + h - h // 6, x + h // 6:x + w - h // 6]
        if inner.size == 0 or (inner < 0.55 * np.percentile(inner, 90)).mean() < 0.03:
            continue                                   # must contain print
        dd = abs(x + w / 2 - W_ / 2) + abs(y + h / 2 - H_ / 2) + 0.002 * w * h
        if dd < bd:
            best, bd = (x, y, w, h), dd
    return best


def find_sticker(img):
    o = find_outlined(img)
    return o if o else find_bright(img)


def find_bright(img):
    """Locate the printed label/sleeve (bright, low-saturation rectangle) nearest the crop centre.
    Returns (x, y, w, h) in crop px or None."""
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    v, s = hsv[..., 2].astype(int), hsv[..., 1].astype(int)
    thr = max(150, np.percentile(v, 60))
    m = ((v >= thr) & (s < 60)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H_, W_ = m.shape; best, bd = None, 1e9
    for c in cs:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < 0.04 * W_ * H_ or h < 12 or w < h * 1.1:
            continue
        dd = abs(x + w / 2 - W_ / 2) + abs(y + h / 2 - H_ / 2)
        if dd < bd:
            best, bd = (x, y, w, h), dd
    return best


def has_label(img):
    """A label/sleeve = bright low-saturation rectangle that contains dark print. Lighting-independent."""
    st = find_sticker(img)
    if not st:
        return False, 0.0
    x, y, w, h = st
    inner = cv2.cvtColor(img[y + int(h * .15):y + h - int(h * .15), x + int(h * .15):x + w - int(h * .15)], cv2.COLOR_RGB2GRAY)
    if inner.size == 0:
        return False, 0.0
    ink = float((inner < 0.55 * np.percentile(inner, 90)).mean())
    return (0.03 < ink < 0.6), ink


try:                                    # in-process libtesseract: identical text, no process start per crop
    import ocr_capi
    _CAPI = ocr_capi.available()
except Exception:  # noqa: BLE001
    _CAPI = False


def _tess(job):
    img, psm = job
    if _CAPI:
        return ocr_capi.image_to_string(img, psm, WL).strip()
    return pytesseract.image_to_string(img, config=f"--psm {psm} -c tessedit_char_whitelist={WL}").strip()


def ocr_variants(img, psm=7, fast=False):
    """Read a small crop several ways (in parallel); returns list of raw strings (for voting)."""
    st = find_sticker(img)
    if st:
        x, y, w, h = st; iy, ix = int(h * 0.14), int(h * 0.05)
        img = img[y + iy:y + h - iy, x + ix:x + w - ix]
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    jobs = []
    # small text (breaker tags) gets upscaled harder: target ~60 px cap height
    scales = (2.0,) if fast else (2.0, 3.0)
    for scale in scales:
        gg = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        for mode in (("raw",) if fast else ("raw", "otsu")):
            if mode == "otsu":
                _, gg2 = cv2.threshold(gg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            else:
                gg2 = gg
            jobs.append((cv2.copyMakeBorder(gg2, 20, 20, 20, 20, cv2.BORDER_REPLICATE), psm))
    return list(_OCR.map(_tess, jobs))


CONF = str.maketrans({"B": "8", "S": "5", "Z": "2", "G": "6", "Q": "0", "D": "0", "L": "1", "T": "7"})


def canon(s):
    """Confusion-aware form (OCR swaps B/8, S/5, ...). Used only to compare against the closed vocabulary."""
    return norm(s).translate(CONF)


def vote(readings, vocab):
    """Closed-vocabulary decoding. Returns (best_vocab_item | None, agreement, raw_majority)."""
    cv = {}
    for v in vocab:
        cv.setdefault(canon(v), []).append(v)
    nv = {norm(v): v for v in vocab}
    for k, vs in cv.items():          # add confusion-aware keys only when they stay unambiguous
        if len(vs) == 1 and k not in nv:
            nv[k] = vs[0]
    hits = {}
    for r in readings:
        n = norm(r)
        if not n:
            continue
        if n not in nv and canon(n) in nv:
            n = canon(n)
        if n in nv:
            hits[nv[n]] = hits.get(nv[n], 0) + 1
        elif len(n) >= 3 and len([k for k in nv if k.endswith(n) and len(k) - len(n) == 1]) == 1:  # first char clipped
            k = [k for k in nv if k.endswith(n) and len(k) - len(n) == 1][0]
            hits[nv[k]] = hits.get(nv[k], 0) + 0.5
        elif len([k for k in nv if len(k) >= 3 and k in n]) == 1:   # vocab item embedded in junk ('CB43E')
            k = [k for k in nv if len(k) >= 3 and k in n][0]
            if len(n) - len(k) <= 2:
                hits[nv[k]] = hits.get(nv[k], 0) + 0.75
        else:
            close = difflib.get_close_matches(n, list(nv), n=2, cutoff=0.85)
            if len(close) == 1:  # unambiguous near-match only
                hits[nv[close[0]]] = hits.get(nv[close[0]], 0) + 0.5
    raw = [norm(r) for r in readings if norm(r)]
    maj = max(set(raw), key=raw.count) if raw else ""
    if not hits:
        return None, 0.0, maj
    best = max(hits, key=hits.get)
    return best, hits[best] / len(readings), maj


def plausible_tag(read, tag):
    """A reading that could be a complete device tag (same shape as the expected one), not an OCR fragment."""
    n = norm(tag)
    return (len(read) >= max(2, len(n) - 1) and (any(c.isalpha() for c in read) or not any(c.isalpha() for c in n))
            and (any(c.isdigit() for c in read) or not any(c.isdigit() for c in n)))


def supports(readings, tag):
    """Do any OCR votes contain a piece of the expected tag (3 characters; 2 for short tags)? Then print is there,
    just unreadable, and "No label" is not proven."""
    t = canon(tag)
    k = 3 if len(t) >= 4 else 2
    pieces = {t[i:i + k] for i in range(len(t) - k + 1)}
    return any(any(p in canon(r) for p in pieces) for r in readings if len(norm(r)) >= k)


def zone_guard(results, keys, note, absent):
    """When most of one zone's items come back *absent or unreadable* at once, the photo of that zone is suspect:
    those absence FAILs become REVIEW. Positive evidence of a wrong item (a full, agreeing wrong reading) stays FAIL."""
    zones = {}
    for k, r in zip(keys, results):
        zones.setdefault(k, []).append(r)
    for rs in zones.values():
        active = [r for r in rs if r["result"] != "SKIP"]
        bad = [r for r in active if r["result"] == "REVIEW" or (r["result"] == "FAIL" and r["found"] == absent)]
        n = len(active)
        need = n // 2 + 1 if n >= 6 else max(2, (n + 1) // 2)       # long zones: a strict majority
        if n >= 3 and len(bad) >= need:
            for r in bad:
                if r["result"] == "FAIL":
                    r.update(result="REVIEW", found=f"Unverified: {r['found']}", conf=0.4,
                             evidence=r["evidence"] + [note.format(bad=len(bad), n=len(active))])
    return results


# ------------------------------------------------------------------ 3. plug-in checks
CHECKS = {}


def check(name):
    """Register a plug-in check. The class needs a ``run(ctx) -> list[result]`` method."""
    def deco(cls):
        CHECKS[name] = cls; return cls
    return deco


def res(item_id, check, target, expected, found, result, box, conf, evidence, **kw):
    return dict(id=item_id, check=check, target=target, expected=expected, found=found, result=result,
                box=box, conf=round(conf, 2), evidence=evidence, **kw)


@check("GA")
class GACheck:
    """Every part present in its place: slot occupancy vs backplate model + label evidence."""
    title = "Part present"
    question = "Is the part the drawing places here physically installed?"

    def run(self, ctx):
        out = []
        for d in ctx.ga["devices"]:
            occ = occupancy(ctx.rect, ctx.bpm, d["box"])
            ctx.facts[("occ", d["tag"])] = occ
            lab, _ = has_label(crop(ctx.rect, d["label_box"], 4))
            if occ > 0.6 or (occ > 0.45 and lab):
                r, found, conf = "PASS", "Present", min(1, occ)
            elif occ < 0.15 or (occ < 0.35 and not lab):  # two evidences agree -> missing
                # (self-test: missing parts read <= 28 % occupancy, installed parts >= 41 %; between is unclear)
                r, found, conf = "FAIL", "Missing", 1 - occ
            else:
                r, found, conf = "REVIEW", f"Unclear (occupancy {occ:.0%})", 0.5
            out.append(res(f"GA-{d['tag']}", "GA", d["tag"], "Installed", found, r, d["box"], conf,
                           [f"slot occupancy {occ:.0%}", f"label seen: {lab}"], occupancy=round(occ, 3)))
            ctx.present[d["tag"]] = (r != "FAIL")
        return out


@check("ORDER")
class OrderCheck:
    """Right place / right order: read labels slot-by-slot along each rail, align with drawing sequence."""
    title = "Rail order"
    question = "Reading left to right along the rail, is every device in the slot the drawing gives it?"

    def run(self, ctx):
        out = []
        for rail in ctx.ga["rails"]:
            devs = [ctx.dev[t] for t in rail["tags"]]

            def read_slot(d):
                if not ctx.present.get(d["tag"], True):
                    return "(empty)", None
                if not has_label(crop(ctx.rect, d["label_box"], 4))[0]:
                    return "(no label)", None                   # LabelCheck owns this item
                best, agr, raw = vote(ocr_variants(crop(ctx.rect, d["label_box"], 4)), rail["tags"])
                if best and agr >= 0.5:
                    f = best
                elif raw and len(raw) >= 3:
                    f = "(other)"                               # readable but not a rail tag -> LabelCheck
                else:
                    f = "?"
                return f, (best, agr, raw)

            found = []
            for d, (f, fact) in zip(devs, pmap(read_slot, devs)):
                found.append(f)
                if fact is not None:
                    ctx.facts[("slotread", d["tag"])] = fact
            exp = rail["tags"]
            swaps, wrong = [], []
            for i in range(len(exp)):
                if found[i] == exp[i] or found[i] in ("(empty)", "?", "(no label)", "(other)"):
                    continue
                if found[i] in exp:
                    j = exp.index(found[i])
                    if found[j] == exp[i] and (j, i) not in swaps:
                        swaps.append((i, j))
                    elif (j, i) not in swaps and (i, j) not in swaps:
                        wrong.append(i)
            box_of = lambda idx: _union([devs[k]["box"] for k in idx])
            seq_e, seq_f = "-".join(exp), "-".join(found)
            slots = [dict(slot=i + 1, expected=exp[i], read=found[i], box=devs[i]["box"]) for i in range(len(exp))]
            if swaps or wrong:
                desc = "; ".join([f"{exp[i]} <-> {exp[j]} swapped" for i, j in swaps] +
                                 [f"slot {i+1} holds {found[i]}" for i in wrong])
                idx = sorted({k for s in swaps for k in s} | set(wrong))
                out.append(res(f"ORD-{rail['name']}", "ORDER", rail["name"], seq_e, desc, "FAIL", box_of(idx), 0.9,
                               [f"read along rail: {seq_f}"], slots=slots, swaps=[[exp[i], exp[j]] for i, j in swaps]))
            elif "?" in found:
                out.append(res(f"ORD-{rail['name']}", "ORDER", rail["name"], seq_e, seq_f, "REVIEW",
                               box_of([i for i, f in enumerate(found) if f == "?"]), 0.5, ["unreadable slot label"],
                               slots=slots))
            else:
                out.append(res(f"ORD-{rail['name']}", "ORDER", rail["name"], seq_e, seq_f, "PASS",
                               box_of(range(len(exp))), 0.9, [f"read along rail: {seq_f}"], slots=slots))
            for i, d in enumerate(devs):  # remember where each breaker's label actually is
                if found[i] in exp:
                    ctx.label_at[found[i]] = d
        return out


@check("LABEL")
class LabelCheck:
    """Every device label present, readable and matching the drawing (closed-vocabulary OCR + voting)."""
    title = "Device label"
    question = "Does the label at this device read exactly the tag printed on the drawing?"

    def run(self, ctx):
        vocab = [d["tag"] for d in ctx.ga["devices"]]

        def one(d):
            iid = f"LBL-{d['tag']}"
            if not ctx.present.get(d["tag"], True):            # presence unknown (GA disabled) -> check the label
                return res(iid, "LABEL", d["tag"], d["tag"], "—", "SKIP", d["box"], 1, [f"blocked by GA-{d['tag']}"],
                           root_cause=f"GA-{d['tag']}")
            if d.get("group") and d["tag"] in ctx.label_at:   # label found on the rail (maybe in swapped slot)
                return res(iid, "LABEL", d["tag"], d["tag"], d["tag"], "PASS", ctx.label_at[d["tag"]]["label_box"], 0.95,
                           ["read on rail"])
            if d.get("group"):
                own = ctx.facts.get(("slotread", d["tag"]))
                rail = next(r for r in ctx.ga["rails"] if r["name"] == d["group"])
                if own and own[0] in rail["tags"] and own[0] != d["tag"]:   # slot holds another rail device
                    return res(iid, "LABEL", d["tag"], d["tag"], f"slot holds {own[0]}", "SKIP", d["label_box"], 1,
                               [f"covered by ORD-{d['group']}"], root_cause=f"ORD-{d['group']}")
            lb = d["label_box"]
            lab, ink = has_label(crop(ctx.rect, lb, 4)); wf = 1.0 if lab else 0.0
            reads = ocr_variants(crop(ctx.rect, lb, 4))
            best, agr, raw = vote(reads, vocab)
            if best == d["tag"] and agr >= 0.5:
                r, found, conf = "PASS", d["tag"], agr
            elif best == d["tag"]:                   # some votes read the right tag: a label is there, just unclear
                r, found, conf = "REVIEW", f"Label unreadable ('{raw}')", 0.4
            elif raw and best != d["tag"] and sum(norm(x) == raw for x in reads) >= 2 and plausible_tag(raw, d["tag"]):
                r, found, conf = "FAIL", f"Wrong label: reads '{raw}'", 0.8
            elif wf < 0.25 and not supports(reads, d["tag"]):
                r, found, conf = "FAIL", "No label", 1 - wf
            else:
                r, found, conf = "REVIEW", f"Label unreadable ('{raw}')", 0.4
            return res(iid, "LABEL", d["tag"], d["tag"], found, r, lb, conf,
                       [f"label sticker+print found: {lab}", f"OCR votes {reads}"], votes=reads)

        devs = ctx.ga["devices"]
        return zone_guard(pmap(one, devs), [d.get("group") or d["type"] for d in devs],
                          "{bad} of {n} labels in this zone missing or unreadable at once: photo of the zone is suspect",
                          absent="No label")


@check("FERRULE")
class FerruleCheck:
    """Read each sleeve; decode against the wire list (closed vocabulary), not free text."""
    title = "Ferrule text"
    question = "Is there a sleeve on this wire, and does it read the wire-list string for this terminal?"

    def run(self, ctx):
        vocab = [w["ferrule"] for w in ctx.wires]
        pairs = list(zip(ctx.ga["terminals"], ctx.wires))

        def fbox(t):
            x, y, tw, th = t["box"]
            return (x + tw + 4, y + th / 2 - 8, 66, 16)

        def one(tw):
            t, w = tw
            fb = fbox(t)
            lab, ink = has_label(crop(ctx.rect, fb, 0))
            wf = white_fraction(ctx.rect, ctx.bpm, fb, shrink=0.2)
            iid = f"FER-{t['tag']}"
            if wf < 0.2 and not lab:
                if wf >= 0.08:                     # some sleeve pixels: look closer before calling it missing
                    reads = ocr_variants(crop(ctx.rect, fb, 0))
                    if any(len(norm(x)) >= 3 for x in reads):
                        return res(iid, "FERRULE", t["tag"], w["ferrule"], f"Sleeve unclear ('{vote(reads, vocab)[2]}')", "REVIEW",
                                   fb, 0.4, [f"sleeve pixels {wf:.0%}", f"OCR votes {reads}"], votes=reads)
                return res(iid, "FERRULE", t["tag"], w["ferrule"], "No ferrule", "FAIL", fb, 1 - wf, [f"sleeve pixels {wf:.0%}"])
            reads = ocr_variants(crop(ctx.rect, fb, 0))
            best, agr, raw = vote(reads, vocab)
            if best == w["ferrule"] and agr >= 0.5:
                return res(iid, "FERRULE", t["tag"], w["ferrule"], best, "PASS", fb, agr, [f"OCR votes {reads}"], votes=reads)
            if best and best != w["ferrule"] and agr >= 0.5:
                return res(iid, "FERRULE", t["tag"], w["ferrule"], f"Wrong ferrule: {best}", "FAIL", fb, agr,
                           [f"OCR votes {reads}"], votes=reads)
            return res(iid, "FERRULE", t["tag"], w["ferrule"], f"Unreadable ('{raw}')", "REVIEW", fb, 0.4,
                       [f"OCR votes {reads}"], votes=reads)

        for t, _ in pairs:
            ctx.facts[("fbox", t["tag"])] = fbox(t)
        # A missing sleeve is a local fact; half a strip's sleeves vanishing or unreadable at once is a photo or
        # alignment problem (keystone, glare, blur on that zone). Then "No ferrule" is not proven: re-photo instead.
        return zone_guard(pmap(one, pairs), [t["tag"].split(":")[0] for t, _ in pairs],
                          "{bad} of {n} sleeves on this strip missing or unreadable at once: photo of the zone is suspect",
                          absent="No ferrule")


COLOUR_WORD = dict(BN="brown", BU="blue", RD="red", GNYE="green-yellow", GY="grey", VT="violet")


@check("COLOUR")
class WireColourCheck:
    """Wire colour after white-balancing on known-white references (labels/ferrules)."""
    title = "Wire colour"
    question = "After white-balancing on the white labels, is the wire the colour the wire list specifies?"

    def run(self, ctx):
        out = []
        gains = ctx.wb_gains
        for t, w in zip(ctx.ga["terminals"], ctx.wires):
            x, y, tw, th = t["box"]
            sb = (x + tw + 78, y + th / 2 - 7, 50, 14)
            c = crop(ctx.rect, sb).astype(np.float32); pm = ctx.bpm.predict(sb)[:c.shape[0], :c.shape[1]]
            dist = np.linalg.norm(c - pm, axis=2).ravel()
            px = c.reshape(-1, 3)[dist > max(45, np.percentile(dist, 55))]
            if len(px) < 30:
                px = c.reshape(-1, 3)
            px = px * gains
            px = np.clip(px, 0, 255).astype(np.uint8)
            hsv = cv2.cvtColor(px[None], cv2.COLOR_RGB2HSV)[0].astype(int)
            h, s, v = hsv[:, 0], hsv[:, 1], hsv[:, 2]
            green = ((h > 40) & (h < 85) & (s > 80)).mean(); yellow = ((h >= 20) & (h <= 35) & (s > 100) & (v > 140)).mean()
            med = np.median(hsv, 0)
            if green > 0.15 and yellow > 0.15:
                c = "GNYE"
            else:
                H_, S_, V_ = med
                if V_ < 70:
                    c = "BK"
                elif S_ > 90 and (H_ < 8 or H_ > 165) and V_ > 120:
                    c = "RD"
                elif 95 <= H_ <= 130 and S_ > 80:
                    c = "BU"
                elif 5 <= H_ <= 25 and S_ > 80 and V_ <= 170:
                    c = "BN"
                else:
                    c = "?"
            iid = f"COL-{t['tag']}"
            ev = [f"green {green:.0%} yellow {yellow:.0%}"]
            if c == w["colour"]:
                r = "PASS"
            elif c == "?":
                r = "REVIEW"
            elif "BK" in (c, w["colour"]) and 50 <= med[2] <= 115:
                r = "REVIEW"                          # a dark wire: black vs a dark colour is not separable in this light
                ev.append(f"brightness {int(med[2])}: black vs {COLOUR_WORD.get(c if c != 'BK' else w['colour'], 'colour')} ambiguous")
            else:
                r = "FAIL"
            rgb = cv2.cvtColor(np.uint8([[med]]), cv2.COLOR_HSV2RGB)[0, 0]
            out.append(res(iid, "COLOUR", t["tag"], w["colour"], c, r, sb, 0.85 if r != "REVIEW" else 0.4, ev,
                           swatch="#%02x%02x%02x" % tuple(int(v) for v in rgb)))
        return out


def _union(boxes):
    boxes = list(boxes)
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


class Ctx:
    pass


def white_balance(rect, ga, bpm):
    """Gains that make the label stickers neutral (known-white references)."""
    pix = []
    for d in ga["devices"]:
        c = crop(rect, d["label_box"]).reshape(-1, 3).astype(np.float32)
        br = c.mean(1)
        if len(br) and np.percentile(br, 90) > 120:
            pix.append(c[br > np.percentile(br, 80)])
    if not pix:
        return np.ones(3, np.float32)
    ref = np.concatenate(pix).mean(0)
    return (ref.mean() / ref).astype(np.float32)


ORDER = ["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"]


def counts(results):
    return {k: sum(r["result"] == k for r in results) for k in ("PASS", "FAIL", "REVIEW", "SKIP")}


def min_anchors(reg):
    """Fewest matched labels/ferrules for a fit we trust (the self-test never goes below 14 of 20)."""
    return max(6, int(0.4 * reg["targets"]))


def load_photo(path):
    """Decode a photo from any path (np.fromfile keeps non-ASCII Windows paths working)."""
    try:
        buf = np.fromfile(str(path), np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
    except OSError:
        img = None
    if img is None:
        raise InspectionError("Could not read the cabinet photo. Upload a JPG or PNG image.")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def inspect(photo_path, ga_pdf, wire_xlsx, checklist_xlsx=None, enabled=ORDER, on_event=None):
    """Run the full pipeline. ``on_event(dict)`` receives live stage events (for progress UIs)."""
    t0 = time.perf_counter()
    emit = on_event or (lambda ev: None)

    def stage(name, status, **kw):
        emit(dict(stage=name, status=status, t=round(time.perf_counter() - t0, 3), **kw))

    timing = {}
    stage("parse", "start")
    photo = load_photo(photo_path)
    ga = parse_ga(str(ga_pdf))
    ctx = Ctx(); ctx.ga = ga; ctx.wires = read_wire_list(str(wire_xlsx))
    timing["parse"] = round(time.perf_counter() - t0, 3)
    stage("parse", "done", cabinet=ga["cabinet"], devices=len(ga["devices"]), terminals=len(ga["terminals"]),
          rails=len(ga["rails"]), wires=len(ctx.wires))

    t = time.perf_counter(); stage("register", "start")
    ctx.rect, ctx.H, ctx.reg = register(photo, ga, ctx.wires)
    need = min_anchors(ctx.reg)
    rotation = 0
    if ctx.reg["anchors"] < need:
        # Too few labels/ferrules matched the drawing. A phone photo taken upside down or sideways is the usual
        # cause, so try the other orientations before giving up. Never triggers on a well-registered photo.
        stage("register", "retry", anchors=ctx.reg["anchors"], reason="weak registration, trying other orientations")
        best = (ctx.reg["anchors"], 0, ctx.rect, ctx.H, ctx.reg, photo)
        for k in (2, 1, 3):
            ph = np.ascontiguousarray(np.rot90(photo, k))
            try:
                rr, hh, gg = register(ph, ga, ctx.wires)
            except InspectionError:
                continue
            if gg["anchors"] > best[0]:
                best = (gg["anchors"], k, rr, hh, gg, ph)
            if gg["anchors"] >= need:
                break
        _, rotation, ctx.rect, ctx.H, ctx.reg, photo = best
    ctx.photo = photo
    ctx.bpm = Backplate(ctx.rect, ga)
    ctx.wb_gains = white_balance(ctx.rect, ga, ctx.bpm)
    timing["register"] = round(time.perf_counter() - t, 3)
    stage("register", "done", anchors=ctx.reg["anchors"], inliers=ctx.reg["inliers"],
          outliers=ctx.reg["outliers"], refined=ctx.reg["refined"], rotated=rotation * 90)

    ctx.dev = {d["tag"]: d for d in ga["devices"]}
    ctx.present, ctx.facts, ctx.label_at = {}, {}, {}
    results = []
    enabled = [e for e in ORDER if e in enabled] + [e for e in enabled if e not in ORDER]
    timing["checks"] = {}
    for name in enabled:
        if name not in CHECKS:
            continue
        t = time.perf_counter(); stage("check", "start", check=name)
        out = CHECKS[name]().run(ctx)
        results += out
        timing["checks"][name] = round(time.perf_counter() - t, 3)
        stage("check", "done", check=name, items=len(out), counts=counts(out))
    warnings = []
    if rotation:
        warnings.append(dict(code="rotated", message=f"The photo was rotated {rotation * 90}° to match the drawing."))
    if ctx.reg["anchors"] < need:
        # Precision first: without a trustworthy fit to the drawing nothing is called FAIL.
        note = (f"weak registration: only {ctx.reg['anchors']} of {ctx.reg['targets']} labels/ferrules matched the drawing; "
                f"the photo may not show cabinet {ga['cabinet']}")
        for r in results:
            if r["result"] == "FAIL":
                r.update(result="REVIEW", found=f"Unverified: {r['found']}", evidence=r["evidence"] + [note], guarded=True)
        warnings.append(dict(code="weak_registration", message=note[0].upper() + note[1:] + ". Every would-be FAIL was "
                             "sent to REVIEW. Check the photo shows the whole backplate of this cabinet, then re-photo."))
    timing["total"] = round(time.perf_counter() - t0, 3)
    c = counts(results)
    stage("consensus", "done", counts=c, root_cause_skips=c["SKIP"], warnings=[w["code"] for w in warnings])
    rep = dict(photo=str(photo_path), results=results, registration=ctx.reg, H=ctx.H.tolist(),
               photo_size=[int(photo.shape[1]), int(photo.shape[0])], rect_px_per_mm=R,
               ga=dict(cabinet=ga["cabinet"], size=list(ga["size"]), devices=ga["devices"],
                       terminals=ga["terminals"], rails=ga["rails"]),
               wires=ctx.wires, enabled=enabled, counts=c, timing=timing, engine=config.VERSION,
               orientation=rotation * 90, warnings=warnings)
    return rep, ctx


if __name__ == "__main__":
    import sys
    t = time.time()
    rep, ctx = inspect(sys.argv[1], config.DEMO_GA, config.DEMO_WIRES)
    for r in rep["results"]:
        if r["result"] != "PASS":
            print(r["result"], r["id"], "|", r["expected"], "->", r["found"], "|", r["evidence"][:1])
    print("pass", sum(r["result"] == "PASS" for r in rep["results"]), "of", len(rep["results"]), rep["registration"]["anchors"], rep["registration"]["inliers"], rep["registration"]["outliers"], f"{time.time()-t:.1f}s")
