"""Phase 1 - drawing knowledge base.

``build_kb(pdf)`` turns a real, vector drawing set (CAD-exported PDF) into the cabinet model of
docs/FINALE_ENGINE_SPEC.md section 3 (schema ``eagle-eye-kb/1``): page kinds, GA views with the in-drawing position of
every device tag, ordered groups of aligned devices, the nameplate schedule, the tag vocabulary, wiring links read from
the power-distribution schematics and the wire colour legend.

Nothing is specific to one cabinet: font-size bands, view outlines and tolerances are derived from the drawing's own
distributions and tags are recognised by the shared families of ``kb.tags``. The model is cached as JSON by the PDF's
SHA-256 under ``config.DATA/cache/kb``; bump ``KB_VERSION`` whenever the algorithm changes so stale caches are rebuilt.

CLI (repository root):  python -m eagle_eye.kb.drawing_kb <pdf> [--out DIR] [--refresh] [--json]
"""
import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if not __package__:  # `python kb/drawing_kb.py <pdf>`: make the engine's top-level imports resolve
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

import config
from kb.tags import FAMILIES, family_of, normalize, tag_sort_key

KB_SCHEMA = "eagle-eye-kb/1"
KB_VERSION = "1.1"
# Wire colours come from the drawing set's own legend only: colour codes differ by standard, edition and customer (a
# black wire is a phase under IEC 60445 and a neutral under India's legacy IS 732), so none is assumed. wire_rules.py
# adds explicitly chosen profiles. UNNAMED holds a legend group whose table cell names no circuit.
UNNAMED = "UNNAMED"

# Page kinds by title keywords, matched on the normalised title (upper case, punctuation -> space). First match wins.
PAGE_KINDS = [
    ("nameplate", r"NAME ?PLATE|LABEL (SCHEDULE|LIST|DETAILS)|LABELL?ING|ENGRAVING"),
    ("bom", r"BILL OF MATERIAL|\bBOM\b|PARTS? LIST|MATERIAL LIST"),
    ("abbreviations", r"ABBREVIATION"),
    ("legend", r"\bLEGEND|SYMBOLS? (LIST|SHEET)"),
    ("power", r"POWER (DISTRIBUTION|WIRING|SCHEMATIC)|\b(AC|DC) DISTRIBUTION|WIRING DIAGRAM|SCHEMATIC"),
    ("network", r"NETWORK|COMMUNICATION|ETHERNET"),
    ("grounding", r"GROUNDING"),
    ("earthing", r"EARTHING|EARTH DETAILS"),
    ("ga", r"GENERAL ARRANGEMENT|\bGA\b|INTERNAL (VIEW|LAYOUT)|INSIDE VIEW|(COMPONENT|PANEL|EQUIPMENT|MOUNTING) LAYOUT"),
    ("top_view", r"TOP VIEW|PLINTH|GLAND PLATE"),
    ("outline", r"OUTLINE|DIMENSION"),
]
_VIEW_KEYS = [("door", {"DOOR"}), ("rear", {"REAR", "BACK"}), ("front", {"FRONT"}), ("left", {"LEFT", "LHS"}),
              ("right", {"RIGHT", "RHS"})]
_VIEW_FILLER = {"VIEW", "VIEWS", "INSIDE", "INTERNAL", "INNER", "OF", "THE", "CABINET", "PANEL", "SECTION"}
_PIN = re.compile(r"^(?:L[123]?|N|E|PE|\+|-|\(\+\)|\(-\)|\d{1,2})$")
_WIRE_LAYER = re.compile(r"MM2|AWG|WIRE|CABLE", re.I)
_TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_MEDIABOX_CLIP


# ------------------------------------------------------------------ small helpers
def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cache_root(cache_dir=None):
    d = Path(cache_dir) if cache_dir else config.DATA / "cache" / "kb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _r(v, nd=2):
    return round(float(v), nd)


def _box(b):
    return [_r(v) for v in b]


def _center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _inside(pt, box, margin=0.0):
    return box[0] - margin <= pt[0] <= box[2] + margin and box[1] - margin <= pt[1] <= box[3] + margin


def _median(vals, default=0.0):
    vals = list(vals)
    return statistics.median(vals) if vals else default


def _edit1(a, b):
    """True when two strings differ by at most one substitution, insertion or deletion."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    return any(b[:i] + b[i + 1:] == a for i in range(len(b)))


def kind_of_title(title):
    """Page kind named by a title ('INTERNAL GENERAL ARRANGEMENT - REAR VIEW' -> 'ga'), or None."""
    t = re.sub(r"\bG\s*\.\s*A\b\.?", " GA ", (title or "").upper())
    t = " ".join(re.sub(r"[^A-Z0-9&]+", " ", t).split())
    for kind, rx in PAGE_KINDS:
        if re.search(rx, t):
            return kind
    return None


def view_key(title):
    """Canonical view key of a view sub-title ('FRONT INSIDE VIEW' -> 'front', 'LEFT SIDE VIEW' -> 'left')."""
    words = re.findall(r"[A-Z0-9]+", (title or "").upper())
    for key, names in _VIEW_KEYS:
        if names & set(words):
            return key
    return "-".join(w for w in words if w not in _VIEW_FILLER).lower() or "view"


def tag_of(text):
    """Device tag inside a drawing word ('PS11', '13CSLS03335(PRI)' -> '13CSLS03335', 'D13-In1(+)' -> 'D13')."""
    n = normalize(text)
    if family_of(n):
        return n
    for part in re.split(r"[()\[\]{}<>,;:]+", text or ""):
        n = normalize(part)
        while n:
            if family_of(n):
                return n
            if "-" not in n:
                break
            n = n.rsplit("-", 1)[0]
    return None


# ------------------------------------------------------------------ page reading
def _read_text(page):
    """Text lines and words of a page; each word carries its line's font size and rotation (0/90/180/270)."""
    tp = page.get_textpage(flags=_TEXT_FLAGS)
    lines, meta = [], {}
    for bno, b in enumerate(page.get_text("dict", textpage=tp)["blocks"]):
        for lno, ln in enumerate(b.get("lines", ())):
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            dx, dy = ln["dir"]
            rot = int(round(math.degrees(math.atan2(-dy, dx)) / 90.0)) % 4 * 90
            meta[(bno, lno)] = (spans, rot)
            lines.append({"text": "".join(s["text"] for s in ln["spans"]).strip(), "bbox": tuple(ln["bbox"]),
                          "size": max(s["size"] for s in spans), "rot": rot})
    words = []
    for x0, y0, x1, y1, w, bno, lno, wno in page.get_text("words", textpage=tp):
        spans, rot = meta.get((bno, lno), ((), 0))
        best, size = -1.0, (spans[0]["size"] if spans else 0.0)
        for s in spans:                               # font size of the span the word sits in
            sb = s["bbox"]
            ov = max(0.0, min(x1, sb[2]) - max(x0, sb[0])) * max(0.0, min(y1, sb[3]) - max(y0, sb[1]))
            if ov > best:
                best, size = ov, s["size"]
        words.append({"text": w, "bbox": (x0, y0, x1, y1), "size": size, "rot": rot, "line": (bno, lno), "n": wno})
    return lines, words


def _tag_tokens(words):
    """Tag-shaped tokens of a page: whole words, split words ('FILTER 1') and tags inside annotated words."""
    out, by_line = [], defaultdict(list)
    for w in words:
        by_line[w["line"]].append(w)
    for ws in by_line.values():
        ws.sort(key=lambda w: w["n"])
        i = 0
        while i < len(ws):
            w, tag = ws[i], tag_of(ws[i]["text"])
            if not tag and i + 1 < len(ws) and len(ws[i + 1]["text"]) <= 3 and not tag_of(ws[i + 1]["text"]):
                pair = normalize(w["text"] + ws[i + 1]["text"])
                if family_of(pair):
                    out.append(dict(w, tag=pair, display=f"{w['text']} {ws[i + 1]['text']}",
                                    bbox=_union([w["bbox"], ws[i + 1]["bbox"]])))
                    i += 2
                    continue
            if tag:
                out.append(dict(w, tag=tag, display=w["text"]))
            i += 1
    return out


def _paths(page):
    """Vector paths with plain tuple coordinates (get_cdrawings when available: about 2x faster)."""
    if hasattr(page, "get_cdrawings"):
        return page.get_cdrawings()
    out = []
    for d in page.get_drawings():
        items = []
        for it in d["items"]:
            if it[0] == "re":
                items.append(("re", tuple(it[1]), 0))
            elif it[0] == "qu":
                q = it[1]
                items.append(("qu", (tuple(q.ul), tuple(q.ll), tuple(q.ur), tuple(q.lr))))
            else:
                items.append((it[0],) + tuple(tuple(p) for p in it[1:]))
        out.append(dict(d, items=items, rect=tuple(d["rect"])))
    return out


def _rect_like(items, bbox):
    """True when a path is a closed outline that fills its bounding box: rectangles, axis-aligned quads and
    rectangular outlines with small notches (device bodies), drawn stroked or filled."""
    if len(items) == 1 and items[0][0] == "re":
        return True
    if len(items) == 1 and items[0][0] == "qu":
        q = items[0][1]
        pts = [q[0], q[1], q[3], q[2]]
    elif 3 <= len(items) <= 64 and all(it[0] == "l" for it in items):
        if any(math.dist(items[i][2], items[i + 1][1]) > 0.3 for i in range(len(items) - 1)):
            return False                                # not one polyline (e.g. a fill made of triangles)
        pts = [items[0][1]] + [it[2] for it in items]
    else:
        return False
    area = 0.5 * abs(sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1])))
    return area >= 0.85 * (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])


def _geometry(page, want_circles=False):
    """Visible straight segments (+ layer), rectangle-like paths and (optionally) small circles of a page."""
    segs, layers, rects, circles = [], [], [], []
    for d in _paths(page):
        c, typ = d.get("color"), d.get("type") or ""
        visible = "s" in typ and c is not None and min(c) < 0.9    # white strokes / fills are masks, not linework
        if not visible and "f" not in typ:
            continue
        items, layer = d["items"], d.get("layer") or ""
        kinds = {it[0] for it in items}
        x0, y0, x1, y1 = d["rect"]
        straight = []
        if want_circles and visible and kinds == {"c"}:
            if 3 <= len(items) <= 8 and 0.4 < x1 - x0 < 8 and abs((x1 - x0) - (y1 - y0)) < 0.25 * (x1 - x0):
                circles.append(((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, layer))
                continue
            straight.append((*items[0][1], *items[-1][4]))   # a wire hop over a crossing: keep its chord
        for it in items:
            k = it[0]
            if k == "l":
                straight.append((*it[1], *it[2]))
            elif k == "re":
                a, b, e, f = it[1]
                straight += [(a, b, e, b), (e, b, e, f), (e, f, a, f), (a, f, a, b)]
            elif k == "qu":
                p = it[1]
                straight += [(*p[0], *p[1]), (*p[1], *p[3]), (*p[3], *p[2]), (*p[2], *p[0])]
        if visible:
            segs += straight
            layers += [layer] * len(straight)
        if x1 - x0 > 0.8 and y1 - y0 > 0.8 and _rect_like(items, (x0, y0, x1, y1)):
            rects.append((x0, y0, x1, y1))
    S = np.array(segs, dtype=np.float64).reshape(-1, 4)
    R = np.unique(np.round(np.array(rects, dtype=np.float64).reshape(-1, 4), 2), axis=0)
    return {"segs": S, "layers": np.array(layers, dtype=object), "rects": R,
            "rect_area": (R[:, 2] - R[:, 0]) * (R[:, 3] - R[:, 1]), "circles": circles}


def _page_title(lines, width, height):
    """The line that names the page: title-block text when it names a kind, else the topmost large title."""
    cands = [ln for ln in lines if len(ln["text"]) >= 6 and re.search(r"[A-Za-z]{3}", ln["text"])]
    if not cands:
        return None
    block = [ln for ln in cands if ln["bbox"][0] > 0.55 * width and ln["bbox"][1] > 0.72 * height
             and kind_of_title(ln["text"])]
    if block:
        return max(block, key=lambda ln: ln["size"])
    smax = max(ln["size"] for ln in cands)
    big = [ln for ln in cands if ln["size"] >= 0.7 * smax]
    named = [ln for ln in big if kind_of_title(ln["text"])]
    return min(named or big, key=lambda ln: (ln["bbox"][1], -len(ln["text"])))


def _cabinet_id(titles, texts, pdf_path):
    ids = Counter()
    for t in titles:
        m = re.search(r"-\s*([A-Z0-9][A-Z0-9_.]{3,})\s*$", (t or "").upper())
        if m and re.search(r"\d", m.group(1)) and re.search(r"[A-Z]", m.group(1)):
            ids[m.group(1)] += 1
    if ids:
        return ids.most_common(1)[0][0]
    for txt in texts:
        m = re.search(r"CABINET\s*(?:NO\.?|ID)?[:\s]\s*([A-Z0-9][A-Z0-9_.\-]*\d[A-Z0-9_.\-]*)", txt.upper())
        if m:
            return m.group(1)
    return Path(pdf_path).stem


# ------------------------------------------------------------------ GA views
def _view_titles(lines, title):
    """Sub-titles of the views drawn on a GA page ('LEFT INSIDE VIEW', ...)."""
    if not lines:
        return []
    body = _median(ln["size"] for ln in lines)
    tsize = title["size"] if title else max(ln["size"] for ln in lines)
    out = []
    for ln in lines:
        up = ln["text"].upper()
        if ln is title or ln["rot"] != 0 or not re.search(r"\bVIEWS?\b", up) or len(up.split()) > 7:
            continue
        if ln["size"] >= max(0.55 * tsize, 1.3 * body):
            out.append(ln)
    return out


def _view_regions(vts, width, height):
    """Column of each view title: x up to the midpoints with its neighbours, y from the title down."""
    regs = []
    for v in vts:
        x0, y0, x1, y1 = v["bbox"]
        cx, cy, h = (x0 + x1) / 2, (y0 + y1) / 2, y1 - y0
        row = [(u["bbox"][0] + u["bbox"][2]) / 2 for u in vts
               if u is not v and abs((u["bbox"][1] + u["bbox"][3]) / 2 - cy) < 3 * h]
        lefts, rights = [c for c in row if c < cx], [c for c in row if c > cx]
        lo = (max(lefts) + cx) / 2 if lefts else None
        hi = (min(rights) + cx) / 2 if rights else None
        if lo is None:
            lo = max(0.0, cx - (hi - cx)) if hi is not None else 0.0
        if hi is None:
            hi = min(width, cx + (cx - lo)) if lefts else width
        below = [u["bbox"][1] for u in vts if u["bbox"][1] > y1 + h and min(u["bbox"][2], hi) > max(u["bbox"][0], lo)]
        regs.append((lo, y1, hi, min(below) if below else height))
    return regs


def _view_outline(S, region, page_h):
    """Cabinet outline of a view: the frame of long vertical lines (+ the long horizontals closing it) in its column."""
    if not len(S):
        return None
    x0, y0, x1, y1 = region
    dx, dy = np.abs(S[:, 2] - S[:, 0]), np.abs(S[:, 3] - S[:, 1])
    mnx, mxx = np.minimum(S[:, 0], S[:, 2]), np.maximum(S[:, 0], S[:, 2])
    mny, mxy = np.minimum(S[:, 1], S[:, 3]), np.maximum(S[:, 1], S[:, 3])
    inside = (mnx >= x0) & (mxx <= x1) & (mny >= y0) & (mxy <= y1)
    V = (dx <= 0.5) & inside & (dy >= 0.3 * (y1 - y0)) & (dy <= 0.92 * page_h)
    if not V.any():
        return None
    bx0, bx1, by0, by1 = mnx[V].min(), mxx[V].max(), mny[V].min(), mxy[V].max()
    w, h = bx1 - bx0, by1 - by0
    Hm = (dy <= 0.5) & inside & (dx >= 0.5 * w) & (mnx >= bx0 - 0.1 * w) & (mxx <= bx1 + 0.1 * w) \
        & (mny >= by0 - 0.15 * h) & (mxy <= by1 + 0.15 * h)
    if Hm.any():
        bx0, bx1 = min(bx0, mnx[Hm].min()), max(bx1, mxx[Hm].max())
        by0, by1 = min(by0, mny[Hm].min()), max(by1, mxy[Hm].max())
    return (float(bx0), float(by0), float(bx1), float(by1))


def _size_bands(inst):
    """Font-size thresholds from the drawing's own distribution of tag text.

    ``ref`` = median size of tag text inside the view outlines. Callouts are much larger (>= 2.4 x ref, or >= 1.8 x
    ref outside the outline). Device text is a minority band of much smaller text: below the lowest size gap
    (ratio >= 1.18) that leaves 2-40 % of the in-drawing tag text underneath; no such gap -> no device text.
    """
    inner = [i["size"] for i in inst if i["inside"]] or [i["size"] for i in inst]
    ref = _median(inner, 1.0)
    callout = 2.4 * ref
    sizes = sorted(round(s, 2) for s in inner if s < callout)
    split = 0.0
    for a, b in zip(sorted(set(sizes)), sorted(set(sizes))[1:]):
        below = sum(1 for s in sizes if s <= a) / len(sizes)
        if b / a >= 1.18 and 0.02 <= below <= 0.4:
            split = math.sqrt(a * b)
            break
    return {"ref_pt": _r(ref, 3), "callout_pt": _r(callout, 3), "device_text_below_pt": _r(split, 3)}


def _kind(i, bands):
    ref = bands["ref_pt"]
    if i["size"] >= bands["callout_pt"] or (not i["inside"] and i["size"] >= 1.8 * ref):
        return "callout"
    return "device_text" if i["size"] < bands["device_text_below_pt"] else "nameplate"


def _enclosing(R, A, box):
    """Rectangles that fully contain ``box``, smallest first (indices into R)."""
    if not len(R):
        return []
    m = (R[:, 0] <= box[0] + 0.3) & (R[:, 1] <= box[1] + 0.3) & (R[:, 2] >= box[2] - 0.3) & (R[:, 3] >= box[3] - 0.3)
    idx = np.nonzero(m)[0]
    return idx[np.argsort(A[idx])]


def _boxes_for(inst, geo, view_bbox):
    """(label_bbox, device_bbox) of an in-drawing instance from the enclosing vector rectangles."""
    R, A = geo["rects"], geo["rect_area"]
    if not len(R):
        return None, None
    b = inst["bbox"]
    tarea = max(0.5, (b[2] - b[0]) * (b[3] - b[1]))
    vb = view_bbox or (0, 0, 1e4, 1e4)
    cap = 0.04 * (vb[2] - vb[0]) * (vb[3] - vb[1])
    label = device = None
    floor = tarea
    for k in _enclosing(R, A, b):
        r, a = R[k], A[k]
        if label is None and a <= 12 * tarea:      # the label outline drawn tight around the text
            label, floor = r, a
            continue
        if a > cap:
            break
        w, h = r[2] - r[0], r[3] - r[1]
        cx, cy = _center(b)
        central = 0.06 <= (cx - r[0]) / w <= 0.94 and 0.06 <= (cy - r[1]) / h <= 0.94   # not a neighbour's edge
        if a > 2.5 * floor and max(w, h) <= 5 * min(w, h) and central:     # not a label strip / DIN rail
            device = r
            break
    return (_box(label) if label is not None else None), (_box(device) if device is not None else None)


def _cluster1d(items, coord, tol):
    items = sorted(items, key=coord)
    out = []
    for it in items:
        if out and coord(it) - coord(out[-1][-1]) <= tol:
            out[-1].append(it)
        else:
            out.append([it])
    return out


def _split_gaps(seq, a):
    """Split an aligned run where a gap is much larger than its typical spacing (two separate rails, ...)."""
    if len(seq) < 3:
        return [seq]
    gaps = [seq[i + 1][1][a] - seq[i][1][a] for i in range(len(seq) - 1)]
    low = sorted(gaps)[: max(1, len(gaps) // 2)]
    lim = 2.5 * _median(low)
    out, cur = [], [seq[0]]
    for g, it in zip(gaps, seq[1:]):
        if g > lim:
            out.append(cur)
            cur = []
        cur.append(it)
    return out + [cur]


def _groups(view, recs):
    """Ordered groups: same family, aligned on the perpendicular axis, >= 2 members (nameplate positions only)."""
    fams = defaultdict(list)
    for r in recs:
        pts = [i["center"] for i in r["instances"] if i["kind"] == "nameplate" and not i["stray"]]
        if pts:
            fams[r["family"]].append((r["tag"], (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))))
    groups = []
    for fam, items in sorted(fams.items()):
        if len(items) < 2:
            continue
        nn = [min(math.dist(p, q) for t2, q in items if t2 != t) for t, p in items]
        tol = min(6.0, max(1.0, 0.25 * _median(nn)))
        left = list(items)
        while len(left) >= 2:
            cands = []
            for axis, a in (("y", 1), ("x", 0)):        # axis = direction the group runs along
                for cl in _cluster1d(left, lambda it, p=1 - a: it[1][p], tol):
                    cl.sort(key=lambda it, a=a: it[1][a])
                    for part in _split_gaps(cl, a):
                        if len(part) >= 2:
                            gap = _median(part[i + 1][1][a] - part[i][1][a] for i in range(len(part) - 1))
                            cands.append((len(part), -gap, axis, part))
            if not cands:
                break
            size, neg_gap, axis, part = max(cands, key=lambda c: (c[0], c[1], c[2] == "y"))
            names = {t for t, _ in part}
            left = [it for it in left if it[0] not in names]
            first = part[0][1]                          # number columns left->right, rows top->bottom
            groups.append((fam, (axis, first[0], first[1]) if axis == "y" else (axis, first[1], first[0]), axis,
                           [t for t, _ in part], -neg_gap))
    groups.sort(key=lambda g: (g[0], g[1]))
    out, seen = [], Counter()
    for fam, _, axis, order, pitch in groups:
        seen[fam] += 1
        out.append({"id": f"{view}-{fam}-{seen[fam]}", "view": view, "family": fam, "axis": axis, "order": order,
                    "pitch_pt": _r(pitch)})
    return out


def _vlm_tags(pdf_path, page_no, clip, warnings):
    """Optional Claude extraction for raster GA views (agent.drawing_extract, added in Phase 5)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        warnings.append(f"p{page_no}: no vector text inside the view outline; VLM fallback skipped (no API key)")
        return []
    try:
        from agent.drawing_extract import extract_drawing_tags
    except ImportError:
        warnings.append(f"p{page_no}: no vector text inside the view outline; VLM fallback not available")
        return []
    try:
        return list(extract_drawing_tags(pdf_path, page_no, list(clip)) or [])
    except Exception as e:  # noqa: BLE001 - optional enrichment, never fatal
        warnings.append(f"p{page_no}: VLM fallback failed ({type(e).__name__}: {e})")
        return []


# ------------------------------------------------------------------ nameplate table, legend
_HEAD_DESC = re.compile(r"^(DESCRIPTION|TAG( NO\.?| NUMBER)?|DEVICE( TAG)?)$")


def _nameplates(page_no, lines, width):
    """Rows of the nameplate schedule tables: DESCRIPTION | NAMEPLATE TYPE | NAMEPLATE SIZE | LETTER SIZE | QTY."""
    heads = [ln for ln in lines if _HEAD_DESC.match(ln["text"].strip().upper())]
    rows = []
    for h in heads:
        hy = (h["bbox"][1] + h["bbox"][3]) / 2
        row = sorted([ln for ln in lines if abs((ln["bbox"][1] + ln["bbox"][3]) / 2 - hy) < 3
                      and ln["bbox"][0] >= h["bbox"][0] - 2], key=lambda ln: ln["bbox"][0])
        cols = []
        for ln in row:
            if cols and _HEAD_DESC.match(ln["text"].strip().upper()):
                break
            up = ln["text"].upper()
            name = ("desc" if not cols else "letter" if "LETTER" in up else "qty" if re.search(r"QTY|QUANT", up)
                    else "size" if "SIZE" in up else "type" if "TYPE" in up else None)
            cols.append((ln["bbox"][0], name))
        if len(cols) < 3:
            continue
        nxt = [o["bbox"][0] for o in heads if o["bbox"][0] > h["bbox"][0] + 5 and abs(o["bbox"][1] - h["bbox"][1]) < 3]
        xmax = min(nxt) - 4 if nxt else width
        xs = [c[0] for c in cols]
        cells = [ln for ln in lines if ln["bbox"][1] > h["bbox"][3] - 1 and h["bbox"][0] - 6 <= ln["bbox"][0] < xmax]

        def col_of(ln):
            k = max((i for i, x in enumerate(xs) if x <= ln["bbox"][0] + 6), default=None)
            return cols[k][1] if k is not None else None

        descs = sorted([c for c in cells if col_of(c) == "desc"], key=lambda c: c["bbox"][1])
        ys = [(c["bbox"][1] + c["bbox"][3]) / 2 for c in descs]
        pitch = _median([b - a for a, b in zip(ys, ys[1:]) if b - a > 2], 12.0)
        for d, yc in zip(descs, ys):
            tag = normalize(d["text"])
            if not family_of(tag):
                continue
            rec = {"tag": tag, "display": d["text"].strip(), "type": None, "size": None, "w_mm": None, "h_mm": None,
                   "letter": None, "qty": None, "page": page_no}
            for c in cells:
                if c is d or abs((c["bbox"][1] + c["bbox"][3]) / 2 - yc) > 0.45 * pitch:
                    continue
                name, txt = col_of(c), c["text"].strip().upper()
                if name == "type":
                    rec["type"] = txt
                elif name == "size":
                    m = re.search(r"(\d+(?:\.\d+)?)\s*MM\s*[X×]\s*(\d+(?:\.\d+)?)\s*MM", txt)
                    if m:
                        w, hh = float(m.group(1)), float(m.group(2))
                        rec.update(size=f"{m.group(1)}MM X {m.group(2)}MM", w_mm=int(w) if w.is_integer() else w,
                                   h_mm=int(hh) if hh.is_integer() else hh)
                elif name == "letter":
                    m = re.search(r"(\d+(?:\.\d+)?)\s*MM", txt)
                    rec["letter"] = f"{m.group(1)}MM" if m else txt
                elif name == "qty":
                    m = re.search(r"\d+", txt)
                    rec["qty"] = int(m.group()) if m else None
            rows.append(rec)
    return rows


_TURN = {90: lambda x, y: (-y, x), 180: lambda x, y: (-x, -y), 270: lambda x, y: (y, -x)}


def _turn_box(b, f):
    pts = [f(b[0], b[1]), f(b[2], b[1]), f(b[0], b[3]), f(b[2], b[3])]
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _reading_frame(lines, S, rot):
    """Lines and segments turned so that text at rotation ``rot`` reads left to right (rotated legend tables)."""
    f = _TURN.get(rot)
    if f is None:
        return lines, S
    out = [dict(ln, bbox=_turn_box(ln["bbox"], f)) for ln in lines]
    if not len(S):
        return out, S
    a = np.array([f(x, y) for x, y in S[:, :2]], dtype=np.float64).reshape(-1, 2)
    b = np.array([f(x, y) for x, y in S[:, 2:]], dtype=np.float64).reshape(-1, 2)
    return out, np.hstack([a, b])


def _wire_colours(lines, S):
    """Wire colour legend: {'230VAC': ['BK', 'BN', 'GN/YE'], ...} from a 'Colour' column, or None. A legend printed
    rotated (some sheets turn the table 90 degrees) is read in its own reading frame."""
    for head in [ln for ln in lines if re.fullmatch(r"COLOU?RS?", ln["text"].strip().upper())]:
        rot = head.get("rot", 0)
        same = [ln for ln in lines if ln.get("rot", 0) == rot]
        frame, seg = _reading_frame(same, S, rot)
        found = _legend_at(frame, seg, frame[next(i for i, ln in enumerate(same) if ln is head)])
        if found:
            return found
    return None


def _legend_at(lines, S, h):
    """The legend under one 'Colour' header (lines and segments in the header's reading frame), or None."""
    heads = [h]
    for h in heads:
        hx = (h["bbox"][0] + h["bbox"][2]) / 2
        cols = [ln for ln in lines if ln["bbox"][1] > h["bbox"][3]
                and abs((ln["bbox"][0] + ln["bbox"][2]) / 2 - hx) < 45
                and re.search(r"\(([A-Z]{2}(?:\s*/\s*[A-Z]{2})?)\)", ln["text"].upper())]
        if not cols:
            continue
        ybot = max(c["bbox"][3] for c in cols) + 25
        cats = []
        for ln in lines:
            up = ln["text"].upper()
            if ln["bbox"][2] > min(c["bbox"][0] for c in cols) or not (h["bbox"][1] < ln["bbox"][1] < ybot):
                continue
            m = re.search(r"(\d+)\s*V\s*(AC|DC)", up)
            key = f"{m.group(1)}V{m.group(2)}" if m else "ALARM" if "ALARM" in up else None
            if key:
                cats.append((key, _center(ln["bbox"])))
        if not cats:
            continue
        bounds = []
        if len(S):
            for _, (cx, _cy) in cats:
                hz = (np.abs(S[:, 3] - S[:, 1]) < 0.3) & (np.minimum(S[:, 0], S[:, 2]) <= cx) \
                    & (np.maximum(S[:, 0], S[:, 2]) >= cx) & (S[:, 1] > h["bbox"][1]) & (S[:, 1] < ybot)
                bounds += list(S[hz, 1])
        bounds = sorted(set(round(float(b), 1) for b in bounds))   # table rules between the categories

        def cell(y):
            return max([b for b in bounds if b <= y], default=-1e9), min([b for b in bounds if b > y], default=1e9)

        out = {}
        for c in sorted(cols, key=lambda c: c["bbox"][1]):
            code = re.sub(r"\s+", "", re.search(r"\(([A-Z]{2}(?:\s*/\s*[A-Z]{2})?)\)", c["text"].upper()).group(1))
            cy = _center(c["bbox"])[1]
            home = [k for k, (_, ky) in cats if cell(ky) == cell(cy)] if bounds else []
            # a colour group whose table cell names no circuit stays unnamed: it is never filed under a neighbour
            key = home[0] if home else UNNAMED if bounds else min(cats, key=lambda kc: abs(kc[1][1] - cy))[0]
            if code not in out.setdefault(key, []):
                out[key].append(code)
        if out:
            return out
    return None


# ------------------------------------------------------------------ power schematics -> connections
class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


def _device_box(tok, V, H, tag_centres):
    """Closed frame around a device tag (ray cast to the nearest lines on all four sides), or None."""
    x0, y0, x1, y1 = tok["bbox"]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    sides = []
    for arr, lo_side, coord, span in ((V, True, x0, cy), (V, False, x1, cy), (H, True, y0, cx), (H, False, y1, cx)):
        if not len(arr):
            return None
        m = (arr[:, 1] <= span) & (arr[:, 2] >= span)
        m &= (arr[:, 0] < coord) & (arr[:, 0] > coord - 90) if lo_side else (arr[:, 0] > coord) & (arr[:, 0] < coord + 90)
        if not m.any():
            return None
        sides.append(arr[m, 0].max() if lo_side else arr[m, 0].min())
    bx = (sides[0], sides[2], sides[1], sides[3])
    if bx[2] - bx[0] > 160 or bx[3] - bx[1] > 160:
        return None
    if any(t != tok["tag"] and _inside(c, bx, -0.5) for t, c in tag_centres):
        return None
    return bx


def _power_links(page_no, geo, words, toks):
    """Wires of a schematic page -> pin-level connections (2-ended wires) and device-level bus links.

    Wires are the axis-aligned segments of the CAD wire layers (layer names with 'mm2'/'AWG'/'WIRE'), or every visible
    segment when the PDF has no such layers (lower confidence). A wire end is attached to a terminal circle or a pin
    label (L, N, E, +, -, 1..99) and to the device whose frame contains it or whose tag sits just above/left of it.
    """
    S, L = geo["segs"], geo["layers"]
    if not len(S):
        return [], []
    axis = (np.abs(S[:, 0] - S[:, 2]) < 0.3) | (np.abs(S[:, 1] - S[:, 3]) < 0.3)
    wl = np.array([bool(_WIRE_LAYER.search(x or "")) for x in L], dtype=bool)
    layered = bool(wl.any())
    W = S[axis & wl] if layered else S[axis & (np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) > 1.0)]
    if not len(W):
        return [], []
    n = len(W)
    dsu = _DSU(n)
    ends = np.vstack([W[:, :2], W[:, 2:]])            # endpoint k belongs to segment k % n
    joined = np.zeros(2 * n, dtype=bool)
    cells = defaultdict(list)
    for k, (x, y) in enumerate(ends):
        cells[(int(x // 0.6), int(y // 0.6))].append(k)
    for k, (x, y) in enumerate(ends):
        cx, cy = int(x // 0.6), int(y // 0.6)
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                for j in cells.get((cx + ddx, cy + ddy), ()):
                    if j != k and j % n != k % n and abs(ends[j, 0] - x) <= 0.6 and abs(ends[j, 1] - y) <= 0.6:
                        dsu.union(k % n, j % n)
                        joined[k] = True
    hz = np.abs(W[:, 1] - W[:, 3]) < 0.3
    hx0, hx1 = np.minimum(W[:, 0], W[:, 2]), np.maximum(W[:, 0], W[:, 2])
    vy0, vy1 = np.minimum(W[:, 1], W[:, 3]), np.maximum(W[:, 1], W[:, 3])
    for k, (x, y) in enumerate(ends):                  # T-junctions: an end on another wire's interior
        m = hz & (np.abs(W[:, 1] - y) <= 0.5) & (hx0 + 0.5 < x) & (hx1 - 0.5 > x)
        m |= ~hz & (np.abs(W[:, 0] - x) <= 0.5) & (vy0 + 0.5 < y) & (vy1 - 0.5 > y)
        m[k % n] = False
        for j in np.nonzero(m)[0]:
            dsu.union(k % n, int(j))
            joined[k] = True
    # terminal circles. Two circles joined by a short symbol line are one feed-through terminal (pin number written
    # beside one of them); a device frame drawn through a row of terminal circles links three or more: left apart.
    circ = geo["circles"]
    C = np.array([c[:3] for c in circ]).reshape(-1, 3)
    cd = _DSU(len(circ))
    if len(C) and layered:
        nonw = S[axis & ~wl]
        on_a = np.abs(np.hypot(nonw[:, None, 0] - C[None, :, 0], nonw[:, None, 1] - C[None, :, 1]) - C[None, :, 2]) < 0.4
        on_b = np.abs(np.hypot(nonw[:, None, 2] - C[None, :, 0], nonw[:, None, 3] - C[None, :, 1]) - C[None, :, 2]) < 0.4
        for s in np.nonzero(on_a.any(1) & on_b.any(1))[0]:
            i, j = int(np.argmax(on_a[s])), int(np.argmax(on_b[s]))
            if i != j and math.dist(C[i, :2], C[j, :2]) < 30:
                cd.union(i, j)
    members = defaultdict(list)
    for i in range(len(C)):
        members[cd.find(i)].append(i)
    partner = {i: [j for j in members[cd.find(i)] if j != i] for i in range(len(C)) if len(members[cd.find(i)]) == 2}
    pins = [(w["text"].strip("()") or w["text"], _center(w["bbox"])) for w in words
            if _PIN.match(w["text"]) and w["size"] <= 5.5]
    owner = {}                                          # pin label -> the terminal circle it is written next to
    for k, (_, c) in enumerate(pins):
        if len(C):
            d = np.hypot(C[:, 0] - c[0], C[:, 1] - c[1])
            if d.min() <= 6.5:
                owner[k] = int(np.argmin(d))
    tag_centres = [(t["tag"], _center(t["bbox"])) for t in toks]
    Vs = S[axis & (np.abs(S[:, 0] - S[:, 2]) < 0.3)]
    Hs = S[axis & (np.abs(S[:, 1] - S[:, 3]) < 0.3)]
    V = np.c_[Vs[:, 0], np.minimum(Vs[:, 1], Vs[:, 3]), np.maximum(Vs[:, 1], Vs[:, 3])] if len(Vs) else np.zeros((0, 3))
    H = np.c_[Hs[:, 1], np.minimum(Hs[:, 0], Hs[:, 2]), np.maximum(Hs[:, 0], Hs[:, 2])] if len(Hs) else np.zeros((0, 3))
    boxes = [(t["tag"], b) for t in toks if (b := _device_box(t, V, H, tag_centres)) is not None]

    def pin_at(p, circle):
        """Pin label of a wire end: the label of its terminal circle (or of the circle's feed-through partner),
        else the nearest free label within 6.5 pt of the end."""
        if circle is not None:
            for cs in ([circle], partner.get(circle, [])):
                own = [(math.dist(C[o, :2], pins[k][1]), pins[k][0]) for k, o in owner.items() if o in cs]
                if own:
                    return min(own)[1]
            return None
        free = [(math.dist(p, c), name) for k, (name, c) in enumerate(pins) if k not in owner and math.dist(p, c) <= 6.5]
        return min(free)[1] if free else None

    def device_at(p):
        inside = [(bx[2] - bx[0]) * (bx[3] - bx[1]) for _, bx in boxes]
        hits = [(a, t) for (t, bx), a in zip(boxes, inside) if _inside(p, bx, 2.5)]
        if hits:
            return min(hits)[1]
        for below in (3, 8):                           # the tag heading the pin: above it first, then level
            best = None
            for t, c in tag_centres:
                ddx, ddy = c[0] - p[0], c[1] - p[1]
                if abs(ddx) <= 45 and -60 <= ddy <= below:
                    d = math.hypot(ddx, ddy)
                    if best is None or d < best[0]:
                        best = (d, t)
            if best:
                return best[1]
        return None

    wires = defaultdict(list)
    for k, (x, y) in enumerate(ends):
        if joined[k]:
            continue
        p, circle = (float(x), float(y)), None
        if len(C):
            dc = np.abs(np.hypot(C[:, 0] - x, C[:, 1] - y) - C[:, 2])
            if dc.min() <= 0.8:
                circle = int(np.argmin(dc))
                p = (float(C[circle, 0]), float(C[circle, 1]))
        dev = device_at(p)
        if dev:
            wires[dsu.find(k % n)].append((dev, pin_at(p, circle), p))
    conns, buses = [], []
    base = 0.75 if layered else 0.5
    for wid, ends_ in wires.items():
        uniq = {}
        for dev, pin, p in ends_:
            uniq.setdefault((dev, pin), p)
        devs = {d for d, _ in uniq}
        if len(devs) < 2:
            continue
        if len(uniq) == 2:
            (a, pa), (b, pb) = sorted(uniq.items(), key=lambda kv: (kv[1][0], kv[1][1]))
            conf = base if a[1] and b[1] else base - 0.25
            c = {"from": f"{a[0]}-{a[1]}" if a[1] else a[0], "to": f"{b[0]}-{b[1]}" if b[1] else b[0],
                 "from_device": a[0], "to_device": b[0], "from_pin": a[1], "to_pin": b[1], "page": page_no,
                 "confidence": _r(conf), "wires": 1}
            same = next((o for o in conns if (o["from"], o["to"]) == (c["from"], c["to"])), None)
            if same:                                   # parallel wires between the same two ends (L + N, ...)
                same["wires"] += 1
            else:
                conns.append(c)
        elif len(devs) <= 12:
            b = {"page": page_no, "members": sorted({f"{d}-{p}" if p else d for d, p in uniq}, key=tag_sort_key),
                 "devices": sorted(devs, key=tag_sort_key), "confidence": _r(min(0.5, base - 0.4))}
            if b not in buses:
                buses.append(b)
    return conns, buses


# ------------------------------------------------------------------ build
def _empty_kb(sha, pdf_path):
    return {"schema": KB_SCHEMA, "kb_version": KB_VERSION, "pdf_sha256": sha, "pdf_name": Path(pdf_path).name,
            "cabinet": None, "pages": [], "views": {}, "vocabulary": [], "nameplates": [], "devices": {}, "groups": [],
            "connections": [], "device_links": [], "buses": [], "wire_colours": None,
            "stats": {"warnings": []}}


def _build(pdf_path, sha, use_vlm_fallback=True):
    t_all = time.time()
    kb = _empty_kb(sha, pdf_path)
    warnings, timing = kb["stats"]["warnings"], Counter()
    doc = pymupdf.open(pdf_path)
    with doc:
        pages, texts = [], {}
        for pno, page in enumerate(doc, 1):
            t = time.time()
            lines, words = _read_text(page)
            toks = _tag_tokens(words)
            timing["text"] += time.time() - t
            W, H = page.rect.width, page.rect.height
            title = _page_title(lines, W, H)
            kind = kind_of_title(title["text"]) if title else None
            how = "title" if kind else None
            if not kind:
                up = " ".join(ln["text"] for ln in lines).upper()
                smax = max((ln["size"] for ln in lines), default=0)
                if re.search(r"NAME ?PLATE", up) and "QTY" in up:
                    kind, how = "nameplate", "content"
                elif sum(1 for t_ in toks if t_["size"] <= 0.4 * smax) >= 12:
                    kind, how = "ga", "content"
                else:
                    kind = "other"
            n_img = len(page.get_images())
            if not words and n_img:
                warnings.append(f"p{pno}: no text layer (raster page), not parsed")
            texts[pno] = (lines, words, toks)
            pages.append({"page": pno, "kind": kind, "title": title["text"] if title else "",
                          "size": [_r(W, 1), _r(H, 1)], "vector": bool(words), "views": [], "classified_by": how,
                          "_title_line": title})
        kb["cabinet"] = _cabinet_id([p["title"] for p in pages], [" ".join(ln["text"] for ln in texts[p["page"]][0])
                                                                  for p in pages], pdf_path)

        # GA pages: views, outlines, tag instances
        geos, views, inst = {}, {}, []
        for p in pages:
            if p["kind"] != "ga":
                continue
            pno = p["page"]
            lines, words, toks = texts[pno]
            t = time.time()
            geos[pno] = _geometry(doc[pno - 1])
            timing["geometry"] += time.time() - t
            vts = _view_titles(lines, p["_title_line"])
            if not vts:
                warnings.append(f"p{pno}: GA page without view sub-titles; no views parsed")
                continue
            W, H = p["size"]
            page_views = []
            for vt, reg in zip(vts, _view_regions(vts, W, H)):
                key = view_key(vt["text"])
                base, k = key, 2
                while key in views:
                    key, k = f"{base}-{k}", k + 1
                outline = _view_outline(geos[pno]["segs"], reg, H)
                views[key] = {"page": pno, "title": vt["text"], "bbox": _box(outline) if outline else None,
                              "region": _box(reg), "_cx": _center(vt["bbox"])[0]}
                page_views.append(key)
            p["views"] = sorted(page_views, key=lambda v: (views[v]["region"][1], views[v]["region"][0]))
            for tk in toks:
                c = _center(tk["bbox"])
                cand = [v for v in page_views if views[v]["region"][1] - 2 <= c[1] <= views[v]["region"][3]]
                if not cand:
                    continue
                v = min(cand, key=lambda v: abs(views[v]["_cx"] - c[0]))
                ob = views[v]["bbox"]
                if ob and not _inside(c, ob, max(80.0, 0.45 * (ob[2] - ob[0]))):
                    continue                           # far from the cabinet (notes, title block)
                inst.append({"tag": tk["tag"], "display": tk["display"], "page": pno, "view": v, "bbox": tk["bbox"],
                             "center": c, "rot": tk["rot"], "size": tk["size"],
                             "inside": bool(ob and _inside(c, ob, 3.0)), "source": "vector"})
        # de-duplicate overlapping copies of the same text (CAD exports often draw a text twice)
        kept = defaultdict(list)
        for i in inst:
            same = kept[(i["tag"], i["page"])]
            if not any(math.dist(i["center"], j["center"]) <= 1.0 and abs(i["size"] - j["size"]) < 0.1 for j in same):
                same.append(i)
        inst = [i for same in kept.values() for i in same]
        bands = _size_bands(inst) if inst else {"ref_pt": None, "callout_pt": None, "device_text_below_pt": None}
        for i in inst:
            i["kind"] = _kind(i, bands)
        # raster / text-less views -> optional VLM extraction
        for v, rec in views.items():
            if use_vlm_fallback and not any(i["view"] == v and i["kind"] != "callout" for i in inst):
                clip = rec["bbox"] or rec["region"]
                for e in _vlm_tags(pdf_path, rec["page"], clip, warnings):
                    tag = normalize(e.get("tag", ""))
                    if family_of(tag) and e.get("bbox"):
                        b = tuple(e["bbox"])
                        inst.append({"tag": tag, "display": e.get("tag"), "page": rec["page"], "view": v, "bbox": b,
                                     "center": _center(b), "rot": int(e.get("rot", 0)), "size": 0.0, "inside": True,
                                     "kind": "nameplate", "source": "vlm"})

        # nameplate schedule, wire colours, schematic tags and connections
        nameplates, np_seen = [], set()
        for p in pages:
            if p["kind"] == "nameplate":
                for row in _nameplates(p["page"], texts[p["page"]][0], p["size"][0]):
                    if row["tag"] in np_seen:
                        warnings.append(f"p{p['page']}: nameplate {row['tag']} listed twice")
                        continue
                    np_seen.add(row["tag"])
                    nameplates.append(row)
        nameplates.sort(key=lambda r: tag_sort_key(r["tag"]))
        np_by_tag = {r["tag"]: r for r in nameplates}
        wc, wc_page = None, None
        # legend sheets first, then any sheet with a "Colour" column (some sets print the wiring table elsewhere)
        for p in sorted(pages, key=lambda p: p["kind"] != "legend"):
            if wc is not None:
                break
            if not any(re.fullmatch(r"COLOU?RS?", ln["text"].strip().upper()) for ln in texts[p["page"]][0]):
                continue
            t = time.time()
            g = geos.get(p["page"]) or _geometry(doc[p["page"] - 1])
            timing["geometry"] += time.time() - t
            wc, wc_page = _wire_colours(texts[p["page"]][0], g["segs"]), p["page"]
        kb["wire_colours"] = wc
        kb["stats"]["wire_colours_source"] = "legend" if wc else "none"
        kb["stats"]["wire_colours_page"] = wc_page if wc else None

        conns, buses, schem_tags = [], [], set()
        for p in pages:
            if p["kind"] in ("power", "grounding", "earthing"):
                lines, words, toks = texts[p["page"]]
                body = [t_ for t_ in toks if t_["size"] < 9]
                schem_tags |= {t_["tag"] for t_ in body}
                if p["kind"] == "power":
                    t = time.time()
                    g = _geometry(doc[p["page"] - 1], want_circles=True)
                    c, b = _power_links(p["page"], g, words, body)
                    timing["connections"] += time.time() - t
                    conns += c
                    buses += b

    # ------------------------------------------------------------ assemble the model
    t = time.time()
    by_view = defaultdict(lambda: defaultdict(list))
    for i in inst:
        by_view[i["view"]][i["tag"]].append(i)
    has_nameplate_size = {i["tag"] for i in inst if i["kind"] == "nameplate"}
    # typical distance between the two labels of one device, per family (to spot stray copies of a tag)
    pair_d = defaultdict(list)
    for tagmap in by_view.values():
        for tag, ii in tagmap.items():
            npl = [i for i in ii if i["kind"] == "nameplate"]
            if len(npl) == 2:
                pair_d[family_of(tag)].append(math.dist(npl[0]["center"], npl[1]["center"]))
    strays, all_groups = [], []
    for v, rec in views.items():
        page_geo = geos.get(rec["page"]) or {"rects": np.zeros((0, 4)), "rect_area": np.zeros(0)}
        tags, callouts, callout_only = [], [], []
        for tag, ii in sorted(by_view[v].items(), key=lambda kv: tag_sort_key(kv[0])):
            for i in ii:
                if i["kind"] == "callout":
                    callouts.append({"tag": tag, "bbox": _box(i["bbox"]), "size_pt": _r(i["size"])})
            draw = sorted([i for i in ii if i["kind"] != "callout"], key=lambda i: (i["center"][1], i["center"][0]))
            if not draw:
                callout_only.append(tag)
                continue
            instances, devs = [], []
            for i in draw:
                label, dev = _boxes_for(i, page_geo, rec["bbox"]) if i["source"] == "vector" else (None, None)
                if dev:
                    devs.append((i["kind"] != "nameplate", dev))   # a nameplate's frame wins
                instances.append({"bbox": _box(i["bbox"]), "center": [_r(i["center"][0]), _r(i["center"][1])],
                                  "rot": i["rot"], "size_pt": _r(i["size"]), "kind": i["kind"],
                                  "label_bbox": label if i["kind"] == "nameplate" else None, "source": i["source"],
                                  "stray": False})
            device = min(devs, key=lambda d: d[0]) if devs else None
            npl = [x for x in instances if x["kind"] == "nameplate"]
            if len(npl) >= 3:                          # a third copy far from the device's label pair: drafting stray
                lim = max(15.0, 2.0 * _median(pair_d.get(family_of(tag), ()), 0.0))
                for x in npl:
                    if min(math.dist(x["center"], y["center"]) for y in npl if y is not x) > lim:
                        x["stray"] = True
                        strays.append(f"{tag}@{v}{x['center']}")
            anchor = [x for x in npl if not x["stray"]] or instances
            npr = np_by_tag.get(tag)
            tags.append({"tag": tag, "family": family_of(tag),
                         "center": [_r(sum(x["center"][0] for x in anchor) / len(anchor)),
                                    _r(sum(x["center"][1] for x in anchor) / len(anchor))],
                         "instances": instances, "device_bbox": device[1] if device else None,
                         "label": {"w_mm": npr["w_mm"], "h_mm": npr["h_mm"], "qty": npr["qty"]} if npr else None,
                         "label_expected": bool(npr) or tag in has_nameplate_size,
                         "source": "vlm" if all(x["source"] == "vlm" for x in instances) else "vector"})
        rec["tags"], rec["callouts"], rec["callout_only"] = tags, callouts, callout_only
        rec["stats"] = {"in_drawing": len(tags), "callout_only": len(callout_only), "callouts": len(callouts),
                        "label_expected_false": [r["tag"] for r in tags if not r["label_expected"]]}
        all_groups += _groups(v, tags)
        del rec["_cx"]
    for p in pages:
        del p["_title_line"]

    ga_tags = {i["tag"] for i in inst}
    vocab = set(np_by_tag) | ga_tags | schem_tags
    tag_pages = defaultdict(set)
    for pno, (_, _, toks) in texts.items():
        for t_ in toks:
            tag_pages[t_["tag"]].add(pno)
    kinds = {p["page"]: p["kind"] for p in pages}
    devices = {}
    for tag in sorted(vocab, key=tag_sort_key):
        vs = sorted({i["view"] for i in inst if i["tag"] == tag})
        devices[tag] = {"family": family_of(tag), "views": vs, "pages": sorted(tag_pages.get(tag, ())),
                        "nameplate": tag in np_by_tag, "label_expected": tag in np_by_tag or tag in has_nameplate_size}

    placed = {r["tag"] for v in views.values() for r in v["tags"]}
    explained, unexplained = {}, []
    for tag in sorted(np_by_tag, key=tag_sort_key):
        if tag in placed:
            continue
        other = sorted(pg for pg in tag_pages.get(tag, ()) if kinds[pg] in ("outline", "top_view"))
        similar = sorted((t_ for t_ in placed if family_of(t_) == family_of(tag) and _edit1(t_, tag)), key=tag_sort_key)
        schem = sorted(pg for pg in tag_pages.get(tag, ()) if kinds[pg] in ("power", "grounding", "earthing"))
        if other:
            explained[tag] = f"drawn on the {kinds[other[0]]} page p{other[0]} (door/roof/outside the GA views)"
        elif similar:
            explained[tag] = f"not on the GA; similar GA tag {'/'.join(similar)} (naming mismatch?)"
        elif schem:
            explained[tag] = f"only in the schematics (p{', p'.join(map(str, schem))})"
        else:
            unexplained.append(tag)

    links = {}
    for c in conns:
        k = tuple(sorted((c["from_device"], c["to_device"]), key=tag_sort_key))
        info = links.setdefault(k, {"confidence": 0.0, "pages": set(), "pin_level": False})
        info["confidence"] = max(info["confidence"], c["confidence"])
        info["pages"].add(c["page"])
        info["pin_level"] |= bool(c["from_pin"] and c["to_pin"])
    for b in buses:
        for i_, a in enumerate(b["devices"]):
            for d in b["devices"][i_ + 1:]:
                info = links.setdefault((a, d), {"confidence": 0.0, "pages": set(), "pin_level": False})
                info["confidence"] = max(info["confidence"], b["confidence"])
                info["pages"].add(b["page"])
    kb.update(
        pages=pages,
        views={v: views[v] for v in sorted(views, key=lambda v: (views[v]["page"], views[v]["region"][0]))},
        vocabulary=sorted(vocab, key=tag_sort_key), nameplates=nameplates, devices=devices,
        groups=all_groups, connections=sorted(conns, key=lambda c: (c["page"], tag_sort_key(c["from"]))),
        device_links=[list(k) for k in sorted(links, key=lambda k: (tag_sort_key(k[0]), tag_sort_key(k[1])))],
        device_link_info={f"{a}|{b}": {"confidence": _r(i_["confidence"]), "pages": sorted(i_["pages"]),
                                       "pin_level": i_["pin_level"]} for (a, b), i_ in links.items()},
        buses=buses)
    timing["assemble"] += time.time() - t
    total = len(np_by_tag)
    kb["stats"].update({
        "pages": len(pages), "ga_pages": [p["page"] for p in pages if p["kind"] == "ga"],
        "size_bands": bands, "instances": Counter(i["kind"] for i in inst),
        "nameplate_coverage": {
            "total": total, "placed": len(set(np_by_tag) & placed), "explained": explained, "unexplained": unexplained,
            "ratio_placed": _r(len(set(np_by_tag) & placed) / total, 3) if total else None,
            "ratio_with_explained": _r((len(set(np_by_tag) & placed) + len(explained)) / total, 3) if total else None},
        "label_expected_false": sorted({r["tag"] for v in views.values() for r in v["tags"] if not r["label_expected"]},
                                       key=tag_sort_key),
        "stray_instances": strays, "connections": len(conns), "buses": len(buses), "device_links": len(links),
        "timing_s": {k: _r(v) for k, v in timing.items()} | {"total": _r(time.time() - t_all)},
    })
    if not views:
        warnings.append("no GA view with a parseable outline/tags: not a real (multi-view) drawing set")
    return kb


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))


def _cache_file(sha, cache_dir=None):
    return _cache_root(cache_dir) / f"{sha}.json"


def _load_cached(path):
    try:
        kb = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return kb if kb.get("schema") == KB_SCHEMA and kb.get("kb_version") == KB_VERSION else None


def build_kb(pdf_path, cache_dir=None, use_vlm_fallback=True, refresh=False):
    """Cabinet model of a drawing set (schema eagle-eye-kb/1), cached as JSON by the PDF's SHA-256.

    ``refresh`` ignores the cache. The result is plain JSON data (lists, dicts, numbers), identical whether it was
    built now or read back from the cache; ``stats.cache`` says which.
    """
    sha = _sha256(pdf_path)
    path = _cache_file(sha, cache_dir)
    if not refresh:
        kb = _load_cached(path)
        if kb is not None:
            kb["stats"]["cache"] = "hit"
            return kb
    kb = json.loads(json.dumps(_build(str(pdf_path), sha, use_vlm_fallback), default=_json_default))
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(kb, indent=1, default=_json_default), encoding="utf-8")
    os.replace(tmp, path)
    kb["stats"]["cache"] = "miss"
    return kb


def is_real_drawing(pdf_path):
    """True when the PDF is a real drawing set: at least one GA page with a view sub-title and device tags under it.

    Cheap: answered from the KB cache when present, otherwise from the page text only (no vector geometry).
    Never raises (False for unreadable files).
    """
    try:
        kb = _load_cached(_cache_file(_sha256(pdf_path)))
        if kb is not None:
            return bool(kb["views"])
        with pymupdf.open(pdf_path) as doc:
            for page in doc:
                lines, words = _read_text(page)
                title = _page_title(lines, page.rect.width, page.rect.height)
                toks = _tag_tokens(words)
                if not (title and kind_of_title(title["text"]) == "ga") and len(toks) < 12:
                    continue
                for vt in _view_titles(lines, title):
                    below = [t for t in toks if t["bbox"][1] > vt["bbox"][3]]
                    if len(below) >= 3:
                        return True
    except Exception:  # noqa: BLE001 - routing helper: anything unreadable is "not a real drawing"
        return False
    return False


def view_tags(kb, view):
    """{tag: tagrec} of one GA view ('front', 'rear', ...); empty for an unknown view."""
    return {r["tag"]: r for r in kb.get("views", {}).get(view, {}).get("tags", [])}


# ------------------------------------------------------------------ rasters, crops, debug images
def render_page(pdf_path, page, dpi=150, cache_dir=None):
    """Raster of one drawing page (1-based), cached as PNG next to the KB cache."""
    sha = _sha256(pdf_path)
    path = _cache_root(cache_dir) / sha[:16] / f"p{int(page)}@{int(dpi)}.png"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(pdf_path) as doc:
            pix = doc[int(page) - 1].get_pixmap(dpi=int(dpi), alpha=False)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            pix.save(str(tmp), output="png")
            os.replace(tmp, path)
    with Image.open(path) as im:
        return im.convert("RGB")


def drawing_crop(kb, pdf_path, view, tag=None, bbox=None, margin_pt=12, dpi=300):
    """GA snippet around a tag (all its in-drawing instances + device frame) or a drawing-pt bbox, tag outlined red."""
    rec = kb["views"][view]
    boxes = []
    if tag is not None:
        tr = view_tags(kb, view).get(normalize(tag))
        if tr:
            boxes = [i["bbox"] for i in tr["instances"]] + ([tr["device_bbox"]] if tr["device_bbox"] else [])
        else:
            boxes = [c["bbox"] for c in rec.get("callouts", []) if c["tag"] == normalize(tag)]
        if not boxes and bbox is None:
            raise KeyError(f"{tag} is not drawn on the {view} view")
    region = _union(boxes + ([bbox] if bbox is not None else []))
    clip = pymupdf.Rect(region[0] - margin_pt, region[1] - margin_pt, region[2] + margin_pt, region[3] + margin_pt)
    with pymupdf.open(pdf_path) as doc:
        page = doc[rec["page"] - 1]
        clip &= page.rect
        pix = page.get_pixmap(dpi=int(dpi), clip=clip, alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    k = dpi / 72.0
    d = ImageDraw.Draw(im)
    hl = [i["bbox"] for i in (view_tags(kb, view).get(normalize(tag), {}).get("instances", []) if tag else [])]
    for b in hl or ([bbox] if bbox is not None else []):
        d.rectangle([(b[0] - clip.x0) * k - 3, (b[1] - clip.y0) * k - 3, (b[2] - clip.x0) * k + 3,
                     (b[3] - clip.y0) * k + 3], outline=(230, 30, 30), width=max(2, int(k)))
    return im


_PALETTE = [(230, 25, 75), (60, 160, 60), (0, 110, 200), (245, 130, 48), (145, 30, 180), (0, 170, 170),
            (220, 40, 210), (150, 110, 0), (0, 128, 128), (128, 0, 0), (0, 0, 140), (110, 110, 0), (255, 90, 0),
            (90, 90, 90), (190, 0, 90), (0, 90, 60), (120, 70, 170), (200, 150, 0), (40, 40, 200), (170, 60, 30)]
_FAMILY_INDEX = {f: i for i, (f, _) in enumerate(FAMILIES)}


def _family_colour(fam):
    return _PALETTE[_FAMILY_INDEX.get(fam, len(_PALETTE) - 1) % len(_PALETTE)]


def _dashed_rect(d, box, colour, width=2, dash=8):
    x0, y0, x1, y1 = box
    for a, b, e, f in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        n = max(1, int(math.hypot(e - a, f - b) / dash))
        for s in range(0, n, 2):
            t0, t1 = s / n, min(1.0, (s + 1) / n)
            d.line([a + (e - a) * t0, b + (f - b) * t0, a + (e - a) * t1, b + (f - b) * t1], fill=colour, width=width)


def debug_png(kb, pdf_path, page, out_path, zoom=3.0):
    """Debug image of a GA page: view outlines (blue), callouts (dashed), tags boxed by family, groups numbered."""
    with pymupdf.open(pdf_path) as doc:
        pix = doc[page - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    im = Image.blend(im, Image.new("RGB", im.size, (255, 255, 255)), 0.35)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(config.font("DejaVuSans-Bold.ttf"), int(4.2 * zoom))
        big = ImageFont.truetype(config.font("DejaVuSans-Bold.ttf"), int(9 * zoom))
    except OSError:
        font = big = ImageFont.load_default()
    z = lambda b: [v * zoom for v in b]  # noqa: E731
    for name, v in kb["views"].items():
        if v["page"] != page:
            continue
        _dashed_rect(d, z(v["region"]), (170, 170, 170), 1, 12)
        if v["bbox"]:
            d.rectangle(z(v["bbox"]), outline=(0, 90, 255), width=4)
            d.text((v["bbox"][0] * zoom, v["bbox"][1] * zoom - 12 * zoom), f"{name} ({len(v['tags'])} tags)",
                   fill=(0, 90, 255), font=big)
        for c in v["callouts"]:
            _dashed_rect(d, [x + o for x, o in zip(z(c["bbox"]), (-3, -3, 3, 3))], _family_colour(family_of(c["tag"])), 3)
        for r in v["tags"]:
            col = _family_colour(r["family"])
            if r["device_bbox"]:
                d.rectangle(z(r["device_bbox"]), outline=col, width=1)
            for i in r["instances"]:
                pad = 3 if i["kind"] == "nameplate" else 1
                bb = [x + o for x, o in zip(z(i["bbox"]), (-pad, -pad, pad, pad))]
                if i["stray"]:
                    d.rectangle(bb, outline=(150, 150, 150), width=2)
                    d.line([bb[0], bb[1], bb[2], bb[3]], fill=(150, 150, 150), width=2)
                elif i["kind"] == "nameplate":
                    d.rectangle(bb, outline=col, width=3)
                else:
                    _dashed_rect(d, bb, (120, 120, 120), 2, 4)
            if not r["label_expected"]:
                d.text((r["center"][0] * zoom + 6, r["center"][1] * zoom - 6), "x", fill=(200, 0, 0), font=font)
        for g in kb["groups"]:
            if g["view"] != name:
                continue
            col = _family_colour(g["family"])
            cen = {r["tag"]: r["center"] for r in v["tags"]}
            pts = [(cen[t][0] * zoom, cen[t][1] * zoom) for t in g["order"]]
            d.line(pts, fill=col, width=2)
            for n_, (x, y) in enumerate(pts, 1):
                off = (8, -int(5 * zoom)) if g["axis"] == "y" else (-4, int(2.5 * zoom))
                d.text((x + off[0], y + off[1]), str(n_), fill=col, font=font)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path


# ------------------------------------------------------------------ CLI
def summary(kb, built_s=None):
    """Human-readable summary of a cabinet model (what the CLI prints)."""
    st, out = kb["stats"], []
    out.append(f"EAGLE EYE drawing KB  {kb['pdf_name']}  sha {kb['pdf_sha256'][:12]}  kb {kb['kb_version']}"
               + (f"  ({st.get('cache', '?')}, {built_s:.2f} s)" if built_s is not None else ""))
    out.append(f"cabinet: {kb['cabinet']}")
    out.append("pages:")
    for p in kb["pages"]:
        out.append(f"  p{p['page']:<3} {p['kind']:<13} {','.join(p['views']):<18} {p['title'][:80]}")
    out.append("views:")
    for v, rec in kb["views"].items():
        s = rec["stats"]
        out.append(f"  {v:<6} p{rec['page']}  {rec['title']:<20} bbox {rec['bbox']}  in-drawing {s['in_drawing']}, "
                   f"callout-only {s['callout_only']}, callouts {s['callouts']}")
        if s["label_expected_false"]:
            out.append(f"         label_expected False: {' '.join(s['label_expected_false'])}")
    out.append(f"size bands (pt): {st.get('size_bands')}   instances: {dict(st.get('instances', {}))}")
    out.append(f"vocabulary: {len(kb['vocabulary'])} tags   nameplates: {len(kb['nameplates'])} rows   "
               f"wire colours ({st.get('wire_colours_source')}): {kb['wire_colours']}")
    cov = st.get("nameplate_coverage", {})
    if cov.get("total"):
        out.append(f"nameplate coverage: {cov['placed']}/{cov['total']} placed on a GA view ({100 * cov['ratio_placed']:.1f} %), "
                   f"{len(cov['explained'])} explained, {len(cov['unexplained'])} unexplained "
                   f"-> {100 * cov['ratio_with_explained']:.1f} %")
        for t, why in cov["explained"].items():
            out.append(f"    {t:<16} {why}")
        if cov["unexplained"]:
            out.append(f"    unexplained: {' '.join(cov['unexplained'])}")
    out.append(f"groups: {len(kb['groups'])}")
    for g in kb["groups"]:
        out.append(f"  {g['id']:<14} axis {g['axis']}  {' '.join(g['order'])}")
    pin = [c for c in kb["connections"] if c.get("from_pin") and c.get("to_pin")]
    out.append(f"connections: {len(kb['connections'])} wires ({len(pin)} pin-level), {len(kb.get('buses', []))} buses, "
               f"{len(kb['device_links'])} device links")
    for c in kb["connections"][:12]:
        out.append(f"  p{c['page']}  {c['from']:<14} -> {c['to']:<16} conf {c['confidence']}")
    for b in kb.get("buses", [])[:4]:
        out.append(f"  p{b['page']}  bus {' '.join(b['members'])}  conf {b['confidence']}")
    if st.get("warnings"):
        out.append("warnings:")
        out += [f"  {w}" for w in st["warnings"]]
    out.append(f"timing (s): {st.get('timing_s')}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Parse a cabinet drawing set into the EAGLE EYE cabinet model.")
    ap.add_argument("pdf")
    ap.add_argument("--out", help="output folder (default: DATA/kb_debug/<sha12>/)")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache and rebuild")
    ap.add_argument("--json", action="store_true", help="print the cabinet model JSON instead of the summary")
    a = ap.parse_args(argv)
    t = time.time()
    kb = build_kb(a.pdf, refresh=a.refresh)
    took = time.time() - t
    out = Path(a.out) if a.out else config.DATA / "kb_debug" / kb["pdf_sha256"][:12]
    out.mkdir(parents=True, exist_ok=True)
    (out / "cabinet_model.json").write_text(json.dumps(kb, indent=1), encoding="utf-8")
    pngs = [str(debug_png(kb, a.pdf, p, out / f"page{p:02d}_ga.png")) for p in kb["stats"].get("ga_pages", [])
            if any(v["page"] == p for v in kb["views"].values())]
    if a.json:
        print(json.dumps(kb, indent=1))
    else:
        print(summary(kb, took))
        print(f"wrote: {out / 'cabinet_model.json'}" + "".join(f"\n       {p}" for p in pngs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
