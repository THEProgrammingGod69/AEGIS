"""Phase 3 - registration: place a photo on the GA drawing (spec section 5).

Every label read with certainty is an *anchor*: its photo position (OCR box centre) and the drawing position of the same
tag on a GA view form a correspondence (one per in-drawing instance of the tag). Per view, an exhaustive 2-point
RANSAC over anchor pairs finds the similarity transform drawing (pt) -> photo (px) supported by the most distinct tags;
it is refined by least squares and, with >= 6 well-spread inliers, upgraded to a homography only when that fits clearly
better. A photo taken at an angle is not similar to the drawing (the far side is foreshortened, parallel rails
converge), so when the similarity leaves anchors unexplained a 4-point RANSAC searches the perspective model directly
and keeps it when it explains clearly more labels. The fitted perspective gives the camera's viewing angle (``angle``),
and every in-view tag gets its local scale, so letter sizes and tolerances follow the foreshortening. Outliers are
kept and reported: a label far from where the drawing puts it is a misplaced or mislabelled part candidate, not noise.

The *coverage* of a fit is the hull of its inliers, expanded by the local label spacing and clipped to the photo frame
(ignore bands excluded). Only drawing items inside it are judged; everything else is NOT_IN_VIEW. Fewer than 3 inliers:
the photo is not localised, positions are not judged and one re-photo hint says why.

    register(tokens_or_classified, kb, photo) -> Registration (plain JSON data)
    project(fit, xy) / unproject(fit, xy)
"""
import math

import cv2
import numpy as np

from kb.tags import tag_sort_key
from vision.decode import Vocab, classify_tokens

MIN_INLIERS = 3              # a fit needs this many distinct tags
SECOND_VIEW_MIN = 4          # a second view needs this many inliers of its own (3 labels of a side wall seen at a
                             # steep angle at the photo's edge placed whole walls badly on the Emerson photos)
HOMOGRAPHY_MIN = 6           # inliers before a homography is even tried
TOL_PT = 7.0                 # inlier tolerance in drawing points (labels sit within a few pt of their drawn spot)
TOL_MIN_PX = 18.0            # ... but never tighter than this many photo pixels
MAX_ROT_DEG = 35.0           # photos are EXIF-upright; a steeper fit is a coincidence
MIN_TEXT_PX = 9.0            # expected letter height below which absence cannot be judged (too small to read)
PERSPECTIVE = True           # search the perspective model when the flat one leaves anchors unexplained (eval_angle.py
                             # turns it off to measure the flat registration alone)
PERSPECTIVE_MIN = 5          # inliers a perspective (4-point RANSAC) fit needs
PERSPECTIVE_ITERS = 1500     # 4-point samples tried (seeded: the same photo always gives the same fit)
OBLIQUE_DEG = 25.0           # viewing angle above which the report warns that labels are foreshortened
STEEP_DEG = 50.0             # ... and above which it asks for a straighter photo


# ------------------------------------------------------------------ transforms
def _sim_matrix(a, b):
    """3x3 matrix of the similarity p = a * d + b (complex a, b)."""
    return np.array([[a.real, -a.imag, b.real], [a.imag, a.real, b.imag], [0.0, 0.0, 1.0]])


def _apply(H, pts):
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    q = np.c_[pts, np.ones(len(pts))] @ np.asarray(H, np.float64).T
    w = q[:, 2:3]
    w[np.abs(w) < 1e-12] = 1e-12
    return q[:, :2] / w


def project(fit, xy):
    """Drawing point(s) (pt) -> photo point(s) (px) through a fit."""
    out = _apply(fit["H"], xy)
    return out[0].tolist() if np.asarray(xy).ndim == 1 else out.tolist()


def unproject(fit, xy):
    """Photo point(s) (px) -> drawing point(s) (pt) through a fit."""
    out = _apply(fit["Hinv"], xy)
    return out[0].tolist() if np.asarray(xy).ndim == 1 else out.tolist()


def _ls_similarity(d, p, w=None):
    """Weighted least-squares similarity (complex a, b) mapping drawing d -> photo p (complex arrays)."""
    w = np.ones(len(d)) if w is None else np.asarray(w, np.float64)
    dm, pm = np.sum(w * d) / w.sum(), np.sum(w * p) / w.sum()
    dd, pp = d - dm, p - pm
    den = np.sum(w * np.abs(dd) ** 2)
    if den < 1e-12:
        return None
    a = np.sum(w * pp * np.conj(dd)) / den
    return a, pm - a * dm


def local_scale(H, xy):
    """Photo px per drawing pt at a drawing point: sqrt of the Jacobian determinant of the projective map there."""
    H = np.asarray(H, np.float64)
    x, y = float(xy[0]), float(xy[1])
    w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
    if abs(w) < 1e-12:
        return 0.0
    u = (H[0, 0] * x + H[0, 1] * y + H[0, 2]) / w
    v = (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / w
    J = np.array([[H[0, 0] - u * H[2, 0], H[0, 1] - u * H[2, 1]], [H[1, 0] - v * H[2, 0], H[1, 1] - v * H[2, 1]]]) / w
    return float(math.sqrt(abs(np.linalg.det(J))))


def view_angle(H, size, focal=None):
    """Viewing angle of the camera against the cabinet plane from a fit drawing -> photo.

    The homography of a plane is K [r1 r2 t] up to scale; with square pixels and the principal point at the photo
    centre, r1 . r2 = 0 and |r1| = |r2| give the focal length when the perspective is strong enough; otherwise a phone
    camera's typical one (about 65 degrees across the long side) is assumed. A focal length off by 15 % moves the
    angle by about 3 degrees at 35 degrees, so the angle is shown rounded, as "about". Returns {"tilt", "yaw", "pitch",
    "focal_px", "focal_source"}: tilt is the angle between the line of sight and the plane's normal; yaw > 0 means the
    photo was taken from the right of the cabinet, pitch > 0 from below.
    """
    W, Hh = float(size[0]), float(size[1])
    M = np.array([[1.0, 0.0, -W / 2], [0.0, 1.0, -Hh / 2], [0.0, 0.0, 1.0]]) @ np.asarray(H, np.float64)
    h1, h2 = M[:, 0], M[:, 1]
    long_side = max(W, Hh)
    cands = []
    if abs(h1[2] * h2[2]) > 1e-14:
        cands.append(-(h1[0] * h2[0] + h1[1] * h2[1]) / (h1[2] * h2[2]))
    if abs(h1[2] ** 2 - h2[2] ** 2) > 1e-14:
        cands.append((h2[0] ** 2 + h2[1] ** 2 - h1[0] ** 2 - h1[1] ** 2) / (h1[2] ** 2 - h2[2] ** 2))
    assumed = 0.8 * long_side
    # the estimate is noisy with a few label positions: trusted only near a phone camera's focal length, and then
    # shrunk towards it (an estimate far off is more likely noise than an unusual lens)
    est = [math.sqrt(c) for c in cands if c > 0 and 0.75 * assumed < math.sqrt(c) < 1.33 * assumed]
    if focal:
        f, src = float(focal), "given"
    elif est:
        f, src = math.sqrt(float(np.median(est)) * assumed), "estimated"
    else:
        f, src = assumed, "assumed"
    Ki = np.diag([1.0 / f, 1.0 / f, 1.0])
    r1, r2 = Ki @ h1, Ki @ h2
    lam = (np.linalg.norm(r1) + np.linalg.norm(r2)) / 2.0
    if lam < 1e-12:
        return None
    n = np.cross(r1 / lam, r2 / lam)
    n /= max(np.linalg.norm(n), 1e-12)
    if n[2] < 0:
        n = -n
    return {"tilt": round(math.degrees(math.acos(min(1.0, abs(n[2])))), 1),
            "yaw": round(math.degrees(math.atan2(n[0], n[2])), 1), "pitch": round(math.degrees(math.atan2(n[1], n[2])), 1),
            "focal_px": round(f, 1), "focal_source": src}


def _degenerate(pts, frac=0.015):
    """Four points of which three are (nearly) on one line: no perspective can be fitted to them."""
    pts = np.asarray(pts, np.float64)
    span = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]), 1e-9) ** 2
    for a, b, c in ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)):
        if abs(_cross2(pts[b] - pts[a], pts[c] - pts[a])) / 2.0 < frac * span:
            return True
    return False


def _cross2(u, v):
    """z of the cross product of two 2-D vectors."""
    return float(u[0] * v[1] - u[1] * v[0])


def _perspective(corr, vrec, size, seed=0):
    """Best sane homography from 4-point samples of distinct tags, scored by distinct inlier tags; refined on its
    inliers. Returns (H, inliers, local scale at the inliers' centre) or None."""
    by_tag = {}
    for k, c in enumerate(corr):
        by_tag.setdefault(c[2], []).append(k)
    tags = sorted(by_tag)
    if len(tags) < 4:
        return None
    rng = np.random.default_rng(seed)
    P = np.float32([c[0] for c in corr])
    D = np.float32([c[1] for c in corr])
    best = None
    for _ in range(PERSPECTIVE_ITERS):
        pick = rng.choice(len(tags), 4, replace=False)
        ks = [by_tag[tags[t]][int(rng.integers(len(by_tag[tags[t]])))] for t in pick]
        if _degenerate(D[ks]) or _degenerate(P[ks]):
            continue
        Hh = cv2.getPerspectiveTransform(D[ks], P[ks])
        if not _sane(Hh, vrec, size):
            continue
        sc = local_scale(Hh, D[ks].mean(0))
        n, w, inl = _score(Hh, corr, max(TOL_MIN_PX, TOL_PT * sc))
        if best is None or (n, w) > best[0]:
            best = ((n, w), Hh, inl, sc)
    if best is None:
        return None
    _, Hh, inl, sc = best
    for _ in range(2):                                    # refine on the inliers (least squares), re-collect
        cs = [c for _r, c in inl.values()]
        if len(cs) < 4:
            break
        Hr, _m = cv2.findHomography(np.float32([c[1] for c in cs]), np.float32([c[0] for c in cs]), 0)
        if Hr is None or not _sane(Hr, vrec, size):
            break
        sc = float(np.median([local_scale(Hr, c[1]) for c in cs]))
        n2, _w2, inl2 = _score(Hr, corr, max(TOL_MIN_PX, TOL_PT * sc))
        if n2 < len(inl):
            break
        Hh, inl = Hr, inl2
    return Hh, inl, sc


# ------------------------------------------------------------------ correspondences
def _drawing_points(rec):
    """Anchor positions of one tag on the drawing: its nameplate instances, else every instance, else the centre."""
    inst = rec.get("instances") or []
    pts = [i["center"] for i in inst if i.get("kind") == "nameplate" and not i.get("stray")]
    if not pts:
        pts = [i["center"] for i in inst if not i.get("stray")] or [i["center"] for i in inst]
    if not pts and rec.get("center"):
        pts = [rec["center"]]
    return [[float(x), float(y)] for x, y in pts]


def tag_text_pt(rec, default=1.4):
    """Letter height of a tag on the drawing (pt): nameplate instances first."""
    inst = rec.get("instances") or []
    sz = [i["size_pt"] for i in inst if i.get("kind") == "nameplate" and i.get("size_pt")]
    sz = sz or [i["size_pt"] for i in inst if i.get("size_pt")]
    return float(np.median(sz)) if sz else default


def _view_tags(kb, view):
    return {r["tag"]: r for r in kb.get("views", {}).get(view, {}).get("tags", [])}


def _corr(reads, vtags):
    """[(photo xy, drawing xy, tag, read index)] for anchor reads of tags drawn on this view."""
    out = []
    for k, r in enumerate(reads):
        if not r.get("anchor") or r["tag"] not in vtags:
            continue
        for d in _drawing_points(vtags[r["tag"]]):
            out.append((r["center"], d, r["tag"], k))
    return out


# ------------------------------------------------------------------ RANSAC
def _score(H, corr, tol_px):
    """Distinct inlier tags of a model, their summed weight and the residual of the best correspondence per tag."""
    if not corr:
        return 0, 0.0, {}
    P = np.array([c[0] for c in corr]); D = np.array([c[1] for c in corr])
    res = np.hypot(*(_apply(H, D) - P).T)
    best = {}
    for c, r in zip(corr, res):
        if r <= tol_px and (c[2] not in best or r < best[c[2]][0]):
            best[c[2]] = (float(r), c)
    return len(best), sum(1.0 / (1.0 + r / tol_px) for r, _ in best.values()), best


def _fit_view(view, reads, kb, size):
    vtags = _view_tags(kb, view)
    corr = _corr(reads, vtags)
    tags = sorted({c[2] for c in corr})
    cand = {"view": view, "matches": len(tags), "inliers": 0}
    if len(tags) < 2:
        return None, cand
    W, H = size
    vb = kb["views"][view].get("bbox") or kb["views"][view].get("region")
    extent = max(vb[2] - vb[0], vb[3] - vb[1], 1.0)
    s_min = 0.2 * min(W, H) / extent                     # the whole view cannot be much smaller than the photo
    s_max = 60.0 * max(W, H) / extent                    # nor a few labels fill a whole photo many times over
    P = np.array([complex(*c[0]) for c in corr]); D = np.array([complex(*c[1]) for c in corr])
    best = None
    for i in range(len(corr)):
        for j in range(i + 1, len(corr)):
            if corr[i][2] == corr[j][2] or abs(D[j] - D[i]) < 1e-6:
                continue
            a = (P[j] - P[i]) / (D[j] - D[i])
            s, rot = abs(a), math.degrees(math.atan2(a.imag, a.real))
            if not (s_min <= s <= s_max) or abs(rot) > MAX_ROT_DEG:
                continue
            Hm = _sim_matrix(a, P[i] - a * D[i])
            tol = max(TOL_MIN_PX, TOL_PT * s)
            n, w, inl = _score(Hm, corr, tol)
            key = (n, w)
            if best is None or key > best[0]:
                best = (key, Hm, inl, s)
    if best is None or best[0][0] < 2:
        return None, cand
    _, Hm, inl, s = best
    model = "similarity"
    for _ in range(3):                                    # refine on the inliers, re-collect
        cs = [c for _r, c in inl.values()]
        sol = _ls_similarity(np.array([complex(*c[1]) for c in cs]), np.array([complex(*c[0]) for c in cs]))
        if sol is None:
            break
        a, b = sol
        s = abs(a)
        Hm = _sim_matrix(a, b)
        _n, _w, inl = _score(Hm, corr, max(TOL_MIN_PX, TOL_PT * s))
    tol = max(TOL_MIN_PX, TOL_PT * s)
    rms = _rms(inl)
    if len(inl) >= HOMOGRAPHY_MIN and _spread(inl, size) >= 0.08:
        cs = [c for _r, c in inl.values()]
        Hh, _mask = cv2.findHomography(np.float32([c[1] for c in cs]), np.float32([c[0] for c in cs]), 0)
        if Hh is not None and _sane(Hh, kb["views"][view], size):
            n2, _w2, inl2 = _score(Hh, corr, tol)
            if n2 >= len(inl) and _rms(inl2) < 0.8 * rms:
                Hm, inl, rms, model = Hh, inl2, _rms(inl2), "homography"
    if PERSPECTIVE and len(tags) - len(inl) >= 2 and len(tags) >= PERSPECTIVE_MIN:
        # anchors the flat model cannot explain: the photo may be taken at an angle, search the perspective directly
        per = _perspective(corr, kb["views"][view], size)
        # kept when it explains clearly more labels, or the same labels clearly better (a steep photo with few labels
        # read: the flat fit still catches them within its tolerance, but places everything between them wrongly)
        better = per and (len(per[1]) >= len(inl) + 2 or (len(per[1]) >= len(inl) and _rms(per[1]) < 0.7 * rms))
        if better and len(per[1]) >= PERSPECTIVE_MIN and _spread(per[1], size) >= 0.02:
            Hm, inl, s, model = per[0], per[1], per[2], "perspective"
            tol, rms = max(TOL_MIN_PX, TOL_PT * s), _rms(per[1])
    cand["inliers"] = len(inl)
    return {"view": view, "H": Hm, "inl": inl, "corr": corr, "model": model, "scale": float(s), "tol": float(tol),
            "rms": float(rms)}, cand


def _rms(inl):
    return float(np.sqrt(np.mean([r * r for r, _ in inl.values()]))) if inl else 0.0


def _spread(inl, size):
    """Area of the inliers' photo hull as a fraction of the photo."""
    pts = np.float32([c[0] for _r, c in inl.values()])
    if len(pts) < 3:
        return 0.0
    return float(cv2.contourArea(cv2.convexHull(pts))) / float(size[0] * size[1])


def _sane(Hh, vrec, size):
    """A homography is sane when it keeps the view outline convex, unflipped and not absurdly distorted."""
    try:
        if np.linalg.cond(Hh) > 1e9:
            return False
        vb = vrec.get("bbox") or vrec.get("region")
        corners = np.array([[vb[0], vb[1]], [vb[2], vb[1]], [vb[2], vb[3]], [vb[0], vb[3]]], np.float64)
        q = np.c_[corners, np.ones(4)] @ Hh.T
        if np.any(q[:, 2] <= 0):
            return False
        q = q[:, :2] / q[:, 2:3]
        cross = [_cross2(q[(k + 1) % 4] - q[k], q[(k + 2) % 4] - q[(k + 1) % 4]) for k in range(4)]
        if not (all(c > 0 for c in cross) or all(c < 0 for c in cross)):
            return False
        sides = [np.linalg.norm(q[(k + 1) % 4] - q[k]) for k in range(4)]
        return max(sides[0], sides[2]) / max(1e-6, min(sides[0], sides[2])) < 3 and \
            max(sides[1], sides[3]) / max(1e-6, min(sides[1], sides[3])) < 3
    except (np.linalg.LinAlgError, ValueError):
        return False


# ------------------------------------------------------------------ coverage
def _frame(size, ignore):
    """Photo frame polygon minus the ignore bands' height at the bottom (they span the bottom corners)."""
    W, H = size
    bottom = H - max([b[3] - b[1] for b in ignore if b[3] >= H - 1] or [0])
    return np.float32([[0, 0], [W, 0], [W, H], [0, H]]), np.float32([[0, 0], [W, 0], [W, bottom], [0, bottom]])


def _expanded_hull(pts, margin):
    ring = [(margin * math.cos(k * math.pi / 8), margin * math.sin(k * math.pi / 8)) for k in range(16)]
    grown = np.float32([[x + dx, y + dy] for x, y in pts for dx, dy in ring])
    return cv2.convexHull(grown).reshape(-1, 2)


def _clip(poly, frame):
    area, inter = cv2.intersectConvexConvex(np.float32(poly), np.float32(frame))
    if inter is None or area <= 0:
        return np.zeros((0, 2), np.float32)
    return inter.reshape(-1, 2)


def _coverage(fit, size, ignore):
    """Coverage polygon in photo px: inlier hull grown by the local label spacing, clipped to the usable frame."""
    pts = np.array([c[0] for _r, c in fit["inl"].values()], np.float64)
    if len(pts) >= 2:
        nn = [min(np.hypot(*(pts[k] - pts[j])) for j in range(len(pts)) if j != k) for k in range(len(pts))]
        spacing = float(np.median(nn))
    else:
        spacing = 0.0
    diag = math.hypot(*size)
    margin = float(np.clip(1.25 * spacing, 0.04 * diag, 0.18 * diag))
    _full, usable = _frame(size, ignore)
    return _clip(_expanded_hull(pts, margin), usable), margin, _anchored_box(fit)


def _anchored_box(fit):
    """Drawing area spanned by the labels read (inliers), grown by half their spacing (3-15 pt): positions inside it
    are interpolated between read labels; outside it they are extrapolated, which a non-to-scale drawing or a steep
    photo angle makes unreliable, so absence is not judged there."""
    d = np.array([c[1] for _r, c in fit["inl"].values()], np.float64)
    if len(d) >= 2:
        nn = [min(np.hypot(*(d[k] - d[j])) for j in range(len(d)) if j != k) for k in range(len(d))]
        m = float(np.clip(0.5 * np.median(nn), 3.0, 15.0))
    else:
        m = 3.0
    return [float(d[:, 0].min() - m), float(d[:, 1].min() - m), float(d[:, 0].max() + m), float(d[:, 1].max() + m)]


def _in_box(b, xy):
    return b[0] <= xy[0] <= b[2] and b[1] <= xy[1] <= b[3]


def _inside(poly, pt):
    """Signed distance (px) of a point to a polygon: > 0 inside."""
    if len(poly) < 3:
        return -1e9
    return float(cv2.pointPolygonTest(np.float32(poly).reshape(-1, 1, 2), (float(pt[0]), float(pt[1])), True))


# ------------------------------------------------------------------ public API
def register(tokens, kb, photo):
    """Registration of one photo against the cabinet model (spec section 5); plain JSON data.

    ``tokens`` are OCR tokens (vision.ocr.read_photo) or the output of ``vision.decode.classify_tokens``. Besides the
    spec fields the result carries ``reads`` (decoded label reads with ``view``/``inlier``/``predicted``) so the checks
    do not decode twice, and ``text_px`` (expected letter height per in-view tag).
    """
    vocab = Vocab(kb.get("vocabulary") or ())
    cls = tokens if isinstance(tokens, dict) and "reads" in tokens else classify_tokens(tokens, vocab)
    reads = cls["reads"]
    size = [int(v) for v in photo["size"]]
    ignore = photo.get("ignore") or []
    views = list(kb.get("views") or {})

    fits, candidates = [], []
    for v in views:
        f, cand = _fit_view(v, reads, kb, size)
        candidates.append(cand)
        if f is not None and len(f["inl"]) >= 2:
            fits.append(f)
    candidates.sort(key=lambda c: (-c["inliers"], -c["matches"], c["view"]))
    fits.sort(key=lambda f: (-len(f["inl"]), f["rms"]))

    chosen = []
    if fits and len(fits[0]["inl"]) >= MIN_INLIERS:
        chosen.append(fits[0])
        used = set(fits[0]["inl"])
        for f in fits[1:]:
            own = set(f["inl"]) - used
            if len(own) >= SECOND_VIEW_MIN:
                chosen.append(f)
                used |= own
    out = {"localised": bool(chosen), "hint": None, "fits": [], "candidates": candidates, "in_view": {},
           "not_in_view": [], "reads": [], "anchors": sum(1 for r in reads if r.get("anchor")),
           "text_px": {}}
    if not chosen:
        n = len({r["tag"] for r in reads if r.get("anchor")})
        if n == 0:
            out["hint"] = ("No drawing label could be read in this photo. Re-photo the cabinet straight on from about "
                           "1 m, in good light, so the device labels are sharp.")
        elif fits and len(fits[0]["inl"]) == 2:
            out["hint"] = (f"Only 2 labels of the {fits[0]['view']} view could be placed on the drawing; include more "
                           f"of that view (at least 3 labelled devices) in the photo.")
        else:
            out["hint"] = (f"{n} drawing label(s) were read but they do not agree on one place on the drawing. Re-photo "
                           f"one side of the cabinet at a time, straight on.")

    for f in chosen:
        W, H = size
        Hinv = np.linalg.inv(f["H"])
        cov, margin, anchored = _coverage(f, size, ignore)
        inl_tags = set(f["inl"])
        inliers = [{"tag": t, "photo": [round(c[0][0], 1), round(c[0][1], 1)],
                    "drawing": [round(c[1][0], 2), round(c[1][1], 2)], "residual_px": round(r, 1)}
                   for t, (r, c) in sorted(f["inl"].items(), key=lambda kv: tag_sort_key(kv[0]))]
        outliers = []
        for k, r in enumerate(reads):
            if not r.get("anchor") or r["tag"] not in _view_tags(kb, f["view"]) or r["tag"] in inl_tags:
                continue
            dpts = _drawing_points(_view_tags(kb, f["view"])[r["tag"]])
            pred = _apply(f["H"], dpts)
            j = int(np.argmin(np.hypot(*(pred - np.array(r["center"])).T)))
            outliers.append({"tag": r["tag"], "photo": [round(v, 1) for v in r["center"]],
                             "drawing": [round(v, 2) for v in dpts[j]], "predicted": [round(float(v), 1) for v in pred[j]],
                             "residual_px": round(float(np.hypot(*(pred[j] - np.array(r["center"])))), 1)})
        out["fits"].append({
            "view": f["view"], "page": kb["views"][f["view"]]["page"], "model": f["model"],
            "H": np.round(f["H"], 8).tolist(), "Hinv": np.round(Hinv, 10).tolist(),
            "inliers": inliers, "outliers": outliers,
            "coverage_photo": np.round(cov, 1).tolist(),
            "anchored_drawing": [round(v, 2) for v in anchored],
            "coverage_drawing": np.round(_apply(Hinv, cov), 2).tolist() if len(cov) else [],
            "scale_px_per_pt": round(f["scale"], 4), "rms_px": round(f["rms"], 2), "tol_px": round(f["tol"], 1),
            "margin_px": round(margin, 1),
            "angle": view_angle(f["H"], size) if f["model"] != "similarity" else None})

    # what each fit can see: tags predicted inside the coverage, or read near their prediction
    read_by_tag = {}
    for r in reads:
        read_by_tag.setdefault(r["tag"], []).append(r)
    for fo in out["fits"]:
        vtags = _view_tags(kb, fo["view"])
        cov = fo["coverage_photo"]
        s = fo["scale_px_per_pt"]
        for tag, rec in vtags.items():
            if tag in out["in_view"]:
                continue
            dpts = _drawing_points(rec)
            if not dpts:
                continue
            preds = _apply(fo["H"], dpts)
            centre = _apply(fo["H"], [rec.get("center") or dpts[0]])[0]
            margin = max(_inside(cov, p) for p in preds)
            near = [r for r in read_by_tag.get(tag, [])
                    if min(np.hypot(*(preds - np.array(r["center"])).T)) <= 2.5 * fo["tol_px"]]
            if margin > 0 or near:
                # letters shrink towards the far side of a photo taken at an angle: the local scale, not the mean
                ls = local_scale(fo["H"], rec.get("center") or dpts[0]) if fo["model"] != "similarity" else s
                out["in_view"][tag] = {"view": fo["view"], "predicted": [round(float(v), 1) for v in centre],
                                       "instances": [[round(float(x), 1), round(float(y), 1)] for x, y in preds],
                                       "margin_px": round(margin, 1), "read_near": bool(near),
                                       "anchored": any(_in_box(fo["anchored_drawing"], p) for p in dpts),
                                       "scale_px_per_pt": round(ls, 4)}
                out["text_px"][tag] = round(tag_text_pt(rec) * ls, 1)
    # Labels of a fitted view read with certainty but away from the fit (the drawing is not to scale everywhere, and a
    # close-up is strongly perspective-distorted): in view, and their position is judged by the drawing's layout order
    # relative to the anchored labels (above/below, left/right) instead of by distance.
    for fo in out["fits"]:
        vtags = _view_tags(kb, fo["view"])
        for tag, rs in read_by_tag.items():
            if tag in out["in_view"] or tag not in vtags:
                continue
            rs = [r for r in rs if r.get("anchor")]
            if not rs:
                continue
            dpts = _drawing_points(vtags[tag])
            preds = _apply(fo["H"], dpts)
            best = min(rs, key=lambda r: (-r["passes"], -r["conf"]))
            ok, n_cmp, bad = layout_consistent(fo, best["center"], dpts[0])
            out["in_view"][tag] = {"view": fo["view"], "predicted": [round(float(v), 1) for v in _apply(fo["H"], [vtags[tag].get("center") or dpts[0]])[0]],
                                   "instances": [[round(float(x), 1), round(float(y), 1)] for x, y in preds],
                                   "margin_px": round(_inside(fo["coverage_photo"], best["center"]), 1),
                                   "anchored": True,
                                   "read_near": False, "off_fit": True,
                                   "layout": {"consistent": ok, "compared": n_cmp, "violations": bad}}
            out["text_px"][tag] = round(tag_text_pt(vtags[tag]) * fo["scale_px_per_pt"], 1)
    fitted_views = {fo["view"] for fo in out["fits"]}
    out["not_in_view"] = sorted({r["tag"] for v in views for r in kb["views"][v]["tags"]} - set(out["in_view"]),
                                key=tag_sort_key)

    # decoded reads, annotated with their view and whether they sit where the drawing expects them
    for r in reads:
        rec = dict(r)
        iv = out["in_view"].get(r["tag"])
        if iv:
            fo = next(f for f in out["fits"] if f["view"] == iv["view"])
            d = min(math.hypot(r["center"][0] - p[0], r["center"][1] - p[1]) for p in iv["instances"])
            rec.update(view=iv["view"], dist_px=round(d, 1), at_predicted=d <= fo["tol_px"] * 1.5)
        else:
            owner = next((v for v in views if r["tag"] in _view_tags(kb, v)), None)
            rec.update(view=owner, dist_px=None, at_predicted=None, other_view=owner not in fitted_views)
        out["reads"].append(rec)
    out["ferrules"] = cls["ferrules"]
    out["unknown"] = cls["unknown"]
    out["inliers"] = sum(len(f["inliers"]) for f in out["fits"])
    return out


def layout_consistent(fit, photo_xy, drawing_xy, refs=None, min_pt=3.5, min_pt_other=None):
    """Is a label's photo position consistent with the drawing's layout relative to the other labels?

    ``refs`` = [(photo xy, drawing xy[, same_family])] of other labels read with certainty (default: the fit's
    inliers). For every reference clearly apart from the label on the drawing (> ``min_pt``; > ``min_pt_other`` for a
    reference of another device family, whose label sits elsewhere on a device of another size) and in the photo
    (> half the fit tolerance) along an axis, the label must sit on the same side of it in both. Returns (consistent, comparisons, violations);
    consistent needs >= 2 comparisons and no violation. Scale-free, so it holds where the drawing is not to scale or the
    photo is strongly perspective-distorted, while a swapped or moved label breaks the order against its neighbours.
    """
    half = 0.5 * fit["tol_px"]
    if refs is None:
        refs = [(a["photo"], a["drawing"]) for a in fit["inliers"]]
    n = bad = 0
    for ref in refs:
        p_ref, d_ref = ref[0], ref[1]
        same = ref[2] if len(ref) > 2 else True
        need = min_pt if same or min_pt_other is None else max(min_pt, min_pt_other)
        for ax in (0, 1):
            dd = drawing_xy[ax] - d_ref[ax]
            dp = photo_xy[ax] - p_ref[ax]
            if abs(dd) <= need or abs(dp) <= half:
                continue
            n += 1
            bad += (dd > 0) != (dp > 0)
    return n >= 2 and bad == 0, n, bad


def view_of_point(reg, xy):
    """The fit whose coverage contains a photo point (deepest inside), or None."""
    best = None
    for f in reg.get("fits") or []:
        d = _inside(f["coverage_photo"], xy)
        if d > 0 and (best is None or d > best[0]):
            best = (d, f)
    return best[1] if best else None
