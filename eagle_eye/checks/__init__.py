"""Phase 4 - plug-in checks of the real-cabinet engine (spec section 6).

A check answers one narrow question per expected item at a known spot and returns *candidate* findings; the consensus
stage (consensus.py) turns them into PASS / FAIL / REVIEW / NOT_IN_VIEW / SKIP. Adding a check is one class:

    from checks import check, finding

    @check("MY_CHECK")
    class MyCheck:
        title = "Short title"; question = "The yes/no question it answers"
        def run(self, ctx): return [finding(...), ...]

Built-in checks run in ``ORDER`` (MISSING first: it re-reads unread labels and decides presence, which the label,
order and ferrule checks build on).
"""
import math
from concurrent.futures import ThreadPoolExecutor

CHECKS = {}
ORDER = ["MISSING", "ORDER", "LABEL", "UNKNOWN_LABEL", "FERRULE", "COLOUR"]
STATUSES = ("OK", "CANDIDATE_FAULT", "UNCERTAIN", "NOT_IN_VIEW", "SKIP")


def check(name):
    """Register a plug-in check class (needs ``run(ctx) -> list[finding]``)."""
    def deco(cls):
        CHECKS[name] = cls
        cls.name = name
        return cls
    return deco


def finding(fid, check_name, target, expected, found, status, box=None, *, view=None, strength=None, drawing=None,
            conf=1.0, rule=None, evidence=(), reads=(), question=None, hint=None, root_cause=None, **extra):
    """A candidate finding (spec section 6). ``box`` is [x0, y0, x1, y1] in photo pixels."""
    if status not in STATUSES:
        raise ValueError(f"unknown finding status {status}")
    out = {"id": fid, "check": check_name, "target": target, "view": view, "expected": expected, "found": found,
           "status": status, "strength": strength if status == "CANDIDATE_FAULT" else None,
           "box": [round(float(v), 1) for v in box] if box is not None else None, "drawing": drawing,
           "conf": round(float(conf), 3), "rule": rule, "evidence": [str(e) for e in evidence],
           "reads": list(reads), "question": question, "hint": hint, "root_cause": root_cause}
    out.update(extra)
    return out


def box_around(pt, half_w, half_h, size=None):
    x0, y0, x1, y1 = pt[0] - half_w, pt[1] - half_h, pt[0] + half_w, pt[1] + half_h
    if size:
        x0, y0 = max(0.0, x0), max(0.0, y0)
        x1, y1 = min(float(size[0]), x1), min(float(size[1]), y1)
    return [x0, y0, x1, y1]


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Context:
    """Everything the checks see for one photo (spec section 6)."""

    def __init__(self, kb, pdf, photo, tokens, reg, wires=None, checklist=None, cfg=None, ocr_region=None,
                 workers=4):
        self.kb, self.pdf, self.photo, self.tokens, self.reg = kb, pdf, photo, tokens, reg
        self.reads = reg.get("reads") or []
        self.ferrules = reg.get("ferrules") or []
        self.unknown = reg.get("unknown") or []
        self.in_view = reg.get("in_view") or {}
        self.wires, self.checklist = wires, checklist
        self.cfg = dict(cfg or {})
        self.facts = {}
        self.workers = max(1, int(workers))
        self._ocr = ocr_region
        self._zoom_cache = {}
        self.views = {v: {r["tag"]: r for r in rec.get("tags", [])} for v, rec in (kb.get("views") or {}).items()}
        self.fits = {f["view"]: f for f in reg.get("fits") or []}

    # ---------------------------------------------------------------- helpers for checks
    def ocr_region(self, box, rotations=(0, 90, 270), scale=3.0):
        """Targeted zoom re-read (cached per box for this photo)."""
        key = (tuple(round(v) for v in box), tuple(rotations), float(scale))
        if key not in self._zoom_cache:
            if self._ocr is not None:
                self._zoom_cache[key] = self._ocr(box, rotations, scale)
            else:
                from vision import ocr
                self._zoom_cache[key] = ocr.read_region(self.photo, box, rotations=rotations, scale=scale)
        return self._zoom_cache[key]

    def pmap(self, fn, items):
        items = list(items)
        if len(items) <= 1 or self.workers == 1:
            return [fn(x) for x in items]
        with ThreadPoolExecutor(min(self.workers, len(items)), thread_name_prefix="ee-check") as pool:
            return list(pool.map(fn, items))

    def tag_rec(self, tag):
        iv = self.in_view.get(tag)
        if iv:
            return self.views.get(iv["view"], {}).get(tag)
        return next((v[tag] for v in self.views.values() if tag in v), None)

    def label_expected(self, tag):
        rec = self.tag_rec(tag)
        return bool(rec and rec.get("label_expected", True))

    def reads_of(self, tag):
        return [r for r in self.reads if r["tag"] == tag]

    def fit(self, view):
        return self.fits.get(view)

    def text_px(self, tag):
        return float(self.reg.get("text_px", {}).get(tag) or 0.0)

    def label_box(self, tag):
        """Photo box where the tag's label should be: projected drawing label boxes, else text-sized around the
        prediction (covers every instance of the tag)."""
        iv = self.in_view.get(tag)
        if not iv:
            return None
        th = max(self.text_px(tag), 6.0)
        W, H = self.photo["size"]
        inside = [p for p in iv["instances"] if 0 <= p[0] < W and 0 <= p[1] < H]
        if not inside:                       # drawn spot outside the photo (label read off the fit): where it was read
            return union([r["box"] for r in self.reads_of(tag)])
        rec = self.tag_rec(tag) or {}
        vertical = any(i.get("rot") in (90, 270) for i in rec.get("instances") or [])
        hw, hh = (1.6 * th, 3.4 * th) if vertical else (3.2 * th, 1.4 * th)
        return union([box_around(p, hw, hh, self.photo["size"]) for p in inside])

    def in_ignore(self, pt):
        return any(b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3] for b in self.photo.get("ignore") or [])


def run_checks(ctx, enabled=None, on_event=None, clock=None):
    """Run the enabled checks in ORDER (unknown names ignored); returns (findings, per-check timings)."""
    import time
    enabled = [c for c in ORDER if c in (enabled or ORDER)] + [c for c in (enabled or []) if c not in ORDER]
    emit = on_event or (lambda ev: None)
    t_of = clock or time.perf_counter
    out, timing = [], {}
    for name in enabled:
        cls = CHECKS.get(name)
        if cls is None:
            continue
        t = time.perf_counter()
        emit({"stage": "check", "status": "start", "check": name, "t": t_of()})
        found = cls().run(ctx)
        out += found
        timing[name] = round(time.perf_counter() - t, 3)
        n = {s: sum(f["status"] == s for f in found) for s in STATUSES}
        # provisional counts in the console's terms: candidates show as REVIEW until consensus decides
        emit({"stage": "check", "status": "done", "check": name, "items": len(found), "t": t_of(),
              "candidates": n["CANDIDATE_FAULT"] + n["UNCERTAIN"], "statuses": n,
              "counts": {"PASS": n["OK"], "FAIL": 0, "REVIEW": n["CANDIDATE_FAULT"] + n["UNCERTAIN"],
                         "SKIP": n["SKIP"], "NOT_IN_VIEW": n["NOT_IN_VIEW"]}})
    return out, timing


from checks import builtin  # noqa: E402,F401  (registers the built-in checks)
