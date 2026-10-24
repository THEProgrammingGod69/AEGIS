"""Colour of a wire's insulation next to its ferrule, as an IEC 60757 code (BK, BN, RD, ... GN/YE).

A ferrule is printed along its wire, so the wire runs along the sleeve. The sleeve is found around the print (its
bright pixels, text strokes closed) and its long axis gives the wire's direction at any angle, including the slant a
photo taken from the side adds; without a clear sleeve the print's own direction is used. The insulation is sampled in
short slices stepping outward from both ends of the sleeve along that axis; slices that still look like the sleeve
are skipped, and the first two agreeing slices beyond it give that end's colour. Colours are judged after white balance and exposure
correction: the sleeve's bright background is the white reference when it is neutral (white sleeves), else the grey
world of the area around the ferrule (yellow sleeves, no sleeve). A slice's colour is the nearest reference shade in
CIELAB, from the middle of the wire; green-and-yellow is a slice whose full width shows both a green and a yellow share
(the stripe runs along the wire, on any side of it). A slice counts as wire only when it stands out from both of its
flanks (backplate, duct): a colour that fills the whole neighbourhood is a surface, not a wire, and one end of a sleeve
usually runs into its terminal. Confidence comes from the colour margin, how uniform the slices are and whether the
ends agree; nothing is reported when no distinct wire is visible.

    classify(rgb, box, rot=0) -> {"code", "conf", "ends", "swatch", "boxes", "white", "reason"} or None
"""
import math

import cv2
import numpy as np

# Insulation shades under neutral light in CIELAB (L 0-100, a, b), near the RAL shades cable makers use; a colour may
# have more than one shade (light and dark blue: neutral and DC control)
REF = [
    ("BK", (14.0, 0.0, 0.0)), ("BN", (34.0, 17.0, 26.0)), ("BN", (26.0, 12.0, 18.0)), ("RD", (44.0, 62.0, 44.0)),
    ("OG", (63.0, 40.0, 66.0)), ("YE", (84.0, -3.0, 80.0)), ("GN", (51.0, -47.0, 32.0)), ("GN", (38.0, -36.0, 20.0)),
    ("BU", (46.0, 1.0, -42.0)), ("BU", (30.0, 24.0, -58.0)), ("VT", (36.0, 48.0, -45.0)), ("GY", (58.0, 0.0, -1.0)),
    ("WH", (94.0, 0.0, 2.0)), ("PK", (72.0, 35.0, 3.0)), ("TQ", (66.0, -32.0, -15.0)),
]
NAME = {"BK": "black", "BN": "brown", "RD": "red", "OG": "orange", "YE": "yellow", "GN": "green", "BU": "blue",
        "VT": "violet", "GY": "grey", "WH": "white", "PK": "pink", "TQ": "turquoise", "GN/YE": "green-and-yellow",
        "WH/BU": "white with blue stripe"}
_ROW = [c for c, _ in REF]
_LAB = np.array([lab for _, lab in REF], np.float64)
CODES = sorted(set(_ROW))
W_L = 0.55                 # lightness counts less than hue: shading changes it most
SLICES = (0.04, 0.17, 0.30, 0.43, 0.56, 0.69, 0.82)  # slice starts beyond the sleeve's end, in sleeve lengths
SLICE_LEN = 0.12
CORE = 0.15                # half-width of the colour band, in sleeve thicknesses (the middle of the wire)
WIDE = 0.33                # half-width of the stripe band (about the whole wire)
FLANK = (0.65, 1.0)        # flank bands either side of the wire, in sleeve thicknesses off its axis
DISTINCT_DE = 14.0         # a wire stands out from both flanks by at least this colour difference
SLEEVE_DE = 11.0           # a slice this close to the sleeve colour is still the sleeve
WHITE = 235.0              # the white reference is mapped to this level


def name(code):
    return NAME.get(code, code)


def _lab(px):
    """CIELAB (L 0-100, a, b) of uint8 RGB pixels (N, 3)."""
    lab = cv2.cvtColor(np.clip(px, 0, 255).astype(np.uint8).reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3)
    lab = lab.astype(np.float64)
    lab[:, 0] *= 100.0 / 255.0
    lab[:, 1:] -= 128.0
    return lab


def _by_code(lab):
    """(N, len(CODES)) weighted distance of Lab pixels to the nearest shade of every colour."""
    d = lab[:, None, :] - _LAB[None, :, :]
    d[..., 0] *= W_L
    d = np.sqrt((d ** 2).sum(-1))
    return np.stack([d[:, [k for k, c in enumerate(_ROW) if c == code]].min(1) for code in CODES], 1)


def _crop(rgb, b):
    H, W = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in b)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return rgb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float64)


def _gains(rgb, box):
    """(per-channel gains, reference used): sleeve background if it is neutral, else the grey world around it."""
    x0, y0, x1, y1 = box
    m = max(x1 - x0, y1 - y0)
    area = _crop(rgb, (x0 - m, y0 - m, x1 + m, y1 + m))
    if area is None or len(area) < 50:
        return np.ones(3), "none"
    grey = area.mean(0)
    gw = grey.mean() / np.maximum(grey, 1.0)                      # grey world: the surroundings average to grey
    sleeve = _crop(rgb, box)
    if sleeve is not None and len(sleeve) >= 30:
        lum = sleeve.mean(1)
        bright = sleeve[lum >= np.percentile(lum, 60)]
        ref = bright.mean(0) if len(bright) else None
        if ref is not None and ref.min() > 40:
            l, a, b = _lab((ref * gw)[None])[0]
            sat = (ref.max() - ref.min()) / ref.max()
            # a white sleeve: nearly unsaturated as photographed (a colour cast tints it only a little), or neutral
            # once the grey world is taken out; a yellow sleeve is neither
            if (sat < 0.35 or math.hypot(a, b) < 14) and l > 45:
                return np.clip(WHITE / ref, 0.4, 4.0), "ferrule sleeve"
    lum = (area * gw).mean(1)
    top = np.percentile(lum, 97)
    return np.clip(gw * (WHITE / max(top, 30.0)), 0.4, 4.0), "grey world"


def _text_line(box, quad, X0, Y0, lum):
    """(centre, unit direction, extent along it (lo, hi), letter height) of the printed text: from OCR's own
    quadrilateral when there is one, else from the dark strokes inside the print box that sit on the bright sleeve."""
    if quad is not None and len(quad) == 4:
        q = np.asarray(quad, np.float64)
        u = (q[1] - q[0]) + (q[2] - q[3])
        if np.linalg.norm(u) > 1e-6:
            u /= np.linalg.norm(u)
            n = np.array([-u[1], u[0]])
            c = q.mean(0)
            t, a = (q - c) @ u, (q - c) @ n
            return c, u, (float(t.min()), float(t.max())), max(2.0, 0.8 * float(a.max() - a.min()))
    x0, y0, x1, y1 = box
    bx0, by0, bx1, by1 = int(x0 - X0), int(y0 - Y0), int(np.ceil(x1 - X0)), int(np.ceil(y1 - Y0))
    inner = lum[by0:by1, bx0:bx1]
    if inner.size < 40:
        return None
    # strokes: thin dark marks (black-hat: what a closing fills in); a wire or a shadow is wider than the kernel
    k = max(3, int(round(0.35 * min(x1 - x0, y1 - y0))) | 1)
    bh = cv2.morphologyEx(inner.astype(np.uint8), cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    thr, _ = cv2.threshold(bh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ys, xs = np.nonzero(bh > max(thr, 25))
    if len(xs) < 20:
        return None
    pts = np.c_[xs + bx0 + X0, ys + by0 + Y0].astype(np.float64)
    c = pts.mean(0)
    val, vec = np.linalg.eigh(np.cov((pts - c).T))
    if val[1] < 4.0 * max(val[0], 1e-9):
        return None                                               # the strokes do not form one line of text
    u = vec[:, 1] / np.linalg.norm(vec[:, 1])
    t, a = (pts - c) @ u, (pts - c) @ np.array([-u[1], u[0]])
    return (c, u, (float(np.percentile(t, 1)), float(np.percentile(t, 99))),
            max(2.0, float(np.percentile(a, 97) - np.percentile(a, 3))))


def _sleeve(rgb, box, rot, quad=None):
    """(centre, axis u, normal n, (t_start, t_end) of the sleeve along u, sleeve length, thickness, found) around the
    print ``box``. The direction and the letter height come from the printed text itself (OCR's quadrilateral, else
    its dark strokes), which no background can be confused with; the sleeve's ends and thickness from where its bright
    band stops along and across that direction (a white wire or a light backplate merging with it leaves the print's
    extent)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    horizontal = w >= h if rot not in (90, 270) else False
    c = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0])
    u0 = np.array([1.0, 0.0]) if horizontal else np.array([0.0, 1.0])
    length, height = (w, h) if horizontal else (h, w)
    guess = (c, u0, np.array([-u0[1], u0[0]]), (-0.62 * length, 0.62 * length), 1.24 * length, 2.3 * height, False)
    H, W = rgb.shape[:2]
    m = 0.6 * max(w, h)
    X0, Y0, X1, Y1 = int(max(0, x0 - m)), int(max(0, y0 - m)), int(min(W, x1 + m)), int(min(H, y1 + m))
    if X1 - X0 < 8 or Y1 - Y0 < 8:
        return guess
    lum = rgb[Y0:Y1, X0:X1].astype(np.float32).mean(2)
    line = _text_line(box, quad, X0, Y0, lum)
    if line is None:
        return guess
    mu, u, (t_lo, t_hi), ht = line
    if u @ u0 < 0:
        u = -u
    if quad is None and abs(u @ u0) < math.cos(math.radians(40)):
        return guess                                              # strokes found across the print box: not trusted
    n = np.array([-u[1], u[0]])
    Lp = t_hi - t_lo
    bx0, by0, bx1, by1 = int(x0 - X0), int(y0 - Y0), int(np.ceil(x1 - X0)), int(np.ceil(y1 - Y0))
    inner = lum[by0:by1, bx0:bx1]
    if inner.size < 4:
        return guess
    # the sleeve: bright pixels as bright as the print's background, text strokes closed
    ref = float(np.percentile(inner, 90))
    k = max(3, int(round(0.6 * ht)) | 1)
    mask = cv2.morphologyEx((lum > 0.85 * ref).astype(np.uint8), cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    origin = np.array([X0, Y0], np.float64)
    mu = np.asarray(mu, np.float64)

    def occ(t0, t1, v0, v1):
        g = _grid(_rect(mu - origin, u, n, t0, t1, v0, v1), mask.shape, steps=10)
        return None if g is None else float(mask[g[1], g[0]].mean())

    step = 0.4 * ht
    ends = []
    for side in (-1, 1):
        edge = t_hi if side > 0 else t_lo
        reach = None
        for j in range(int(1.2 * Lp / step) + 1):
            o = occ(*sorted((edge + side * j * step, edge + side * (j + 1) * step)), -0.4 * ht, 0.4 * ht)
            if o is None:
                break                                             # the window ends: the sleeve did not
            if o < 0.5:
                reach = edge + side * j * step
                break
        ends.append(reach)
    across = []
    for side in (-1, 1):
        reach = None
        for j in range(int(3.0 * ht / step) + 1):
            o = occ(0.3 * t_lo, 0.3 * t_hi, *sorted((side * j * step, side * (j + 1) * step)))
            if o is None:
                break
            if o < 0.5:
                reach = j * step
                break
        across.append(reach)
    d = float(np.clip(sum(across), 1.4 * ht, 4.0 * ht)) if None not in across else 2.3 * ht
    lo = ends[0] if ends[0] is not None else t_lo - 0.12 * Lp
    hi = ends[1] if ends[1] is not None else t_hi + 0.12 * Lp
    return mu, u, n, (lo, hi), hi - lo, d, True


def _grid(quad, shape, steps=12):
    """Integer pixel coordinates (x, y) covering an oriented rectangle, or None when any of it lies outside ``shape``."""
    a, b, _c, d = (np.asarray(q, np.float64) for q in quad)
    na = max(2, min(steps, int(np.linalg.norm(b - a)) + 1))
    nd = max(2, min(steps, int(np.linalg.norm(d - a)) + 1))
    s, t = np.meshgrid(np.linspace(0, 1, na), np.linspace(0, 1, nd))
    pts = a + s[..., None] * (b - a) + t[..., None] * (d - a)
    x, y = np.rint(pts[..., 0]).astype(int).ravel(), np.rint(pts[..., 1]).astype(int).ravel()
    if x.min() < 0 or y.min() < 0 or x.max() >= shape[1] or y.max() >= shape[0]:
        return None
    return x, y


def _rect(c, u, n, t0, t1, v0, v1):
    """Corners of the oriented rectangle t in [t0, t1] along u, v in [v0, v1] along n."""
    return [c + t0 * u + v0 * n, c + t1 * u + v0 * n, c + t1 * u + v1 * n, c + t0 * u + v1 * n]


def _sample(rgb, quad, steps=12):
    """Pixels of an oriented rectangle (nearest neighbour), or None when any of it lies outside the photo."""
    g = _grid(quad, rgb.shape[:2], steps)
    return None if g is None else rgb[g[1], g[0]].reshape(-1, 3).astype(np.float64)


def _slices(frame, side):
    """(core, wide, flank 1, flank 2) quads per slice, stepping outward from one end of the sleeve (side -1 / +1)."""
    c, u, n, (lo, hi), L, d, _found = frame
    out = []
    for k in SLICES:
        a, b = k * L, (k + SLICE_LEN) * L
        t0, t1 = (lo - b, lo - a) if side < 0 else (hi + a, hi + b)
        out.append((_rect(c, u, n, t0, t1, -CORE * d, CORE * d), _rect(c, u, n, t0, t1, -WIDE * d, WIDE * d),
                    _rect(c, u, n, t0, t1, -FLANK[1] * d, -FLANK[0] * d), _rect(c, u, n, t0, t1, FLANK[0] * d, FLANK[1] * d)))
    return out


def _judge(core, wide):
    """(code, margin 0-1, uniformity 0-1, median Lab) of one slice: core pixels for the colour, wide for the stripe."""
    gi, yi = CODES.index("GN"), CODES.index("YE")
    near_w = _by_code(wide).argmin(1)
    g, y = (near_w == gi).mean(), (near_w == yi).mean()
    med = np.median(core, 0)
    if min(g, y) >= 0.12 and g + y >= 0.45 and min(g, y) / (g + y) >= 0.2:
        return "GN/YE", min(1.0, 0.5 + min(g, y) / (g + y)), float(g + y), med
    d = _by_code(med[None])[0]
    order = np.argsort(d)
    d1, d2 = d[order[0]], d[order[1]]
    share = (_by_code(core).argmin(1) == order[0]).mean()
    return CODES[order[0]], float((d2 - d1) / max(d2, 1e-6)), float(share), med


def _distinct(rgb, med, flanks, gains):
    """The slice's colour stands out from both flanks (a wire, not the surface it lies on)."""
    for q in flanks:
        px = _sample(rgb, q)
        if px is None or len(px) < 6:
            continue                                              # flank outside the photo: no evidence against
        if np.linalg.norm(np.median(_lab(px * gains), 0) - med) < DISTINCT_DE:
            return False
    return True


def _end(rgb, slices, gains, sleeve_lab):
    """Colour of the insulation along one end: the first two agreeing slices that are not the sleeve."""
    seen = []
    for core_b, wide_b, *flanks in slices:
        core, wide = _sample(rgb, core_b), _sample(rgb, wide_b)
        if core is None or wide is None:
            break                                                 # left the photo
        code, margin, uni, med = _judge(_lab(core * gains), _lab(wide * gains))
        if sleeve_lab is not None and np.linalg.norm(med - sleeve_lab) < SLEEVE_DE and code != "GN/YE":
            seen.append(("sleeve", wide_b, med, _distinct(rgb, med, flanks, gains)))
            continue
        seen.append((code, wide_b, med, margin, uni, _distinct(rgb, med, flanks, gains)))
        run = [s for s in seen if s[0] != "sleeve"]
        if len(run) >= 2 and run[-1][0] == run[-2][0]:
            a, z = run[-2], run[-1]
            conf = 0.45 + 0.5 * min(1.0, (a[3] + z[3]) / 2 / 0.45) * (0.6 + 0.4 * (a[4] + z[4]) / 2)
            return {"code": z[0], "conf": round(min(0.95, conf), 3), "boxes": [a[1], z[1]],
                    "lab": ((a[2] + z[2]) / 2).round(1).tolist(), "distinct": a[5] and z[5]}
        if len(run) >= 3:
            break                                                 # no two agreeing slices: not a plain wire
    if seen and all(s[0] == "sleeve" for s in seen) and len(seen) >= 4:
        # white as far as the slices reach: a white wire, surely so when it runs a whole print length past the print
        # (sleeves are at most about 1.5 print lengths long)
        return {"code": "WH", "conf": 0.72 if len(seen) >= 6 else 0.55, "boxes": [s[1] for s in seen[-2:]],
                "lab": seen[-1][2].round(1).tolist(), "sleeve_like": True, "distinct": all(s[3] for s in seen[-2:])}
    return None


def _bbox(quad):
    q = np.asarray(quad, np.float64)
    return [round(float(q[:, 0].min()), 1), round(float(q[:, 1].min()), 1), round(float(q[:, 0].max()), 1),
            round(float(q[:, 1].max()), 1)]


def _hex(lab):
    px = np.array([[[lab[0] * 255.0 / 100.0, lab[1] + 128.0, lab[2] + 128.0]]], np.float64)
    rgb = cv2.cvtColor(np.clip(px, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)[0, 0]
    return "#%02x%02x%02x" % tuple(int(v) for v in rgb)


def classify(rgb, box, rot=0, quad=None):
    """Wire colour next to a ferrule whose printed text is ``box`` [x0, y0, x1, y1] (photo px, text rotation ``rot``;
    ``quad``: OCR's quadrilateral of the text, which gives its slant).

    None when the wire is not visible next to the sleeve (out of the photo, or no two agreeing slices on either end).
    """
    rgb = np.asarray(rgb)
    x0, y0, x1, y1 = (float(v) for v in box)
    if x1 - x0 < 4 or y1 - y0 < 3:
        return None
    gains, white = _gains(rgb, (x0, y0, x1, y1))
    sleeve = _crop(rgb, (x0, y0, x1, y1))
    sleeve_lab = None
    if sleeve is not None and len(sleeve) >= 30 and white == "ferrule sleeve":
        lum = sleeve.mean(1)
        sleeve_lab = np.median(_lab(sleeve[lum >= np.percentile(lum, 60)] * gains), 0)
    frame = _sleeve(rgb, (x0, y0, x1, y1), rot, quad)
    found = [e for e in (_end(rgb, _slices(frame, s), gains, sleeve_lab) for s in (-1, 1)) if e]
    ends = [e for e in found if e["distinct"]]                    # surfaces (backplate, terminal, duct) are not wires
    if not ends:
        return None
    best = max(ends, key=lambda e: e["conf"])
    codes = {e["code"] for e in ends}
    if len(ends) == 2 and ends[0]["code"] == ends[1]["code"]:
        conf = min(0.97, best["conf"] + 0.1 * min(e["conf"] for e in ends))
        reason = f"both ends of the sleeve read {name(best['code'])}"
    elif len(ends) == 2 and codes in ({"GN/YE", "GN"}, {"GN/YE", "YE"}):
        # striped insulation: where the view is narrow only one stripe shows, so plain green (or yellow) at one end
        # agrees with green-and-yellow at the other
        best = next(e for e in ends if e["code"] == "GN/YE")
        one = name(next(c for c in codes if c != "GN/YE"))
        conf = 0.9 * best["conf"]
        reason = f"one end shows both stripes, the other only the {one} one"
    elif len(ends) == 2:
        conf = 0.45 * best["conf"]
        reason = f"the two ends disagree ({' vs '.join(name(e['code']) for e in ends)})"
    else:
        conf = 0.85 * best["conf"]
        reason = (f"one end of the sleeve reads {name(best['code'])}; the other "
                  + ("runs into a surface (terminal, backplate)" if len(found) == 2 else "is not visible"))
    if best.get("sleeve_like"):
        conf = min(conf, 0.8)
        reason = ("white well past the sleeve: a white wire" if best["conf"] > 0.6 else
                  "white as far as the sleeve reaches: a white wire, or a sleeve longer than usual")
    angle = math.degrees(math.atan2(frame[1][1], frame[1][0]))
    return {"code": best["code"], "conf": round(conf, 3), "ends": [{k: e[k] for k in ("code", "conf")} for e in ends],
            "swatch": _hex(best["lab"]), "boxes": [_bbox(q) for e in ends for q in e["boxes"]],
            "white": white, "reason": reason, "axis_deg": round(angle, 1), "sleeve": "found" if frame[6] else "print box"}
