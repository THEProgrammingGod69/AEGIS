"""Angle sweep: does the drawing still land on the photo when the photo is taken from the side?

Takes the measured renders of the real cabinet's GA views (render_real.py, data/emerson_render/), looks at each through
a virtual phone camera turned sideways by a yaw angle (the keystone a photo from the left or right shows: the far side
shrinks, rails converge), and runs the real-cabinet engine on every view and angle twice: with the flat registration
alone (similarity, homography only as a refinement) and with the perspective search. Per angle it counts views placed
on the drawing, labels placed (fit inliers), labels verified (PASS), false FAILs (the renders carry no planted fault)
and the viewing angle the engine measured against the true one.

    python eval_angle.py [--data data/emerson_render] [--angles 0 20 35 50] [--views front left right rear]

Writes out/forge/angle_sweep.json and the console's copy (web/src/data/): totals per angle and mode only (no image
names, tags or drawing content), so they can be committed and shown on the Fault Forge page. The renders are drawings with camera effects, not photographs.
"""
import argparse
import datetime
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

import config

DATA = config.BASE.parent / "data" / "emerson_render"
OUT = config.OUT / "forge" / "angle_sweep.json"
WEB = config.BASE / "web" / "src" / "data" / "angle_sweep.json"      # bundled by the console's Fault Forge page
SCHEMA = "eagle-eye-angle/1"
MODES = {"flat": "Similarity fit (homography as refinement only)", "perspective": "With the perspective search"}


def turn(rgb, yaw_deg, focal=None):
    """The image as a camera turned ``yaw_deg`` about the vertical axis would see it (pure-rotation homography
    K R K^-1), scaled back into the same frame. Returns (image, homography original -> new)."""
    h, w = rgb.shape[:2]
    f = focal or 0.8 * max(w, h)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    a = math.radians(yaw_deg)
    R = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    Hc = K @ R @ np.linalg.inv(K)
    corners = np.float64([[0, 0], [w, 0], [w, h], [0, h]])
    q = cv2.perspectiveTransform(corners[None], Hc)[0]
    x0, y0 = q.min(0)
    x1, y1 = q.max(0)
    s = min(w / (x1 - x0), h / (y1 - y0))
    fit = np.array([[s, 0, -s * x0 + (w - s * (x1 - x0)) / 2], [0, s, -s * y0 + (h - s * (y1 - y0)) / 2], [0, 0, 1.0]])
    Ht = fit @ Hc
    out = cv2.warpPerspective(rgb, Ht, (w, h), flags=cv2.INTER_AREA, borderValue=(128, 128, 128))
    return out, Ht


def run_one(rgb, pdf, perspective):
    """The real-cabinet engine on one image with the perspective search on or off -> summary of the run."""
    import pipeline
    from vision import register
    old = register.PERSPECTIVE
    register.PERSPECTIVE = perspective
    try:
        t = time.perf_counter()
        [(rep, _)] = pipeline.inspect_real([rgb], pdf, agent=False)
    finally:
        register.PERSPECTIVE = old
    reg = rep["registration"]
    c = rep["counts"]
    angles = [f.get("angle") for f in reg.get("fits") or [] if f.get("angle")]
    return {"localised": bool(reg.get("localised")), "inliers": reg.get("inliers", 0), "anchors": reg.get("anchors", 0),
            "models": [f["model"] for f in reg.get("fits") or []], "pass": c.get("PASS", 0), "fail": c.get("FAIL", 0),
            "review": c.get("REVIEW", 0), "not_in_view": c.get("NOT_IN_VIEW", 0),
            "verified": (rep.get("coverage") or {}).get("verified", 0),
            "measured": angles[0]["tilt"] if angles else None, "seconds": round(time.perf_counter() - t, 1)}


def sweep(data=DATA, angles=(0, 20, 35, 50), views=("front", "left", "right", "rear"), on_run=None):
    data = Path(data)
    info = json.loads((data / "render_info.json").read_text(encoding="utf-8"))
    pdf = str(data / info.get("drawing", "Sanitized_Cabinet_Drawing.pdf"))
    rows = []
    for v in views:
        rec = (info.get("views") or {}).get(v)
        if not rec:
            continue
        from PIL import Image
        base = np.asarray(Image.open(data / rec["file"]).convert("RGB"))
        for yaw in angles:
            for sign in ((1,) if yaw == 0 else (1, -1)):          # from the left and from the right
                img, _ = turn(base, sign * yaw)
                for mode in MODES:
                    r = run_one(img, pdf, mode == "perspective")
                    r.update(view=v, yaw=sign * yaw, angle=yaw, mode=mode)
                    rows.append(r)
                    if on_run:
                        on_run(r)
    return rows


def summarize(rows, angles):
    out = []
    for yaw in angles:
        for mode in MODES:
            rs = [r for r in rows if r["angle"] == yaw and r["mode"] == mode]
            if not rs:
                continue
            meas = [r["measured"] for r in rs if r["measured"] is not None]
            out.append({"angle": yaw, "mode": mode, "images": len(rs), "localised": sum(r["localised"] for r in rs),
                        "inliers": sum(r["inliers"] for r in rs), "anchors": sum(r["anchors"] for r in rs),
                        "pass": sum(r["pass"] for r in rs), "fail": sum(r["fail"] for r in rs),
                        "review": sum(r["review"] for r in rs), "not_in_view": sum(r["not_in_view"] for r in rs),
                        "verified": sum(r["verified"] for r in rs),
                        "perspective_fits": sum(m != "similarity" for r in rs for m in r["models"]),
                        "measured_mean": round(float(np.mean(meas)), 1) if meas else None,
                        "measured_error": round(float(np.mean([abs(m - yaw) for m in meas])), 1) if meas else None})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Angle sweep of the real-cabinet registration on drawing renders")
    ap.add_argument("--data", default=str(DATA), help="render_real.py output (renders + render_info.json + drawing)")
    ap.add_argument("--angles", type=float, nargs="+", default=[0, 20, 35, 50])
    ap.add_argument("--views", nargs="+", default=["front", "left", "right", "rear"])
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    if not (Path(a.data) / "render_info.json").exists():
        raise SystemExit(f"No renders in {a.data}: run python render_real.py first.")
    t0 = time.perf_counter()
    show = lambda r: print(f"{r['view']:>5} yaw {r['yaw']:+5.0f} {r['mode']:<11} placed {str(r['localised']):<5} "  # noqa: E731
                           f"inliers {r['inliers']:>2}/{r['anchors']:<2} PASS {r['pass']:>3} FAIL {r['fail']} "
                           f"REVIEW {r['review']:>2} measured {r['measured']} {r['models']} {r['seconds']} s", flush=True)
    angles = [int(x) if float(x).is_integer() else x for x in a.angles]
    rows = sweep(a.data, angles, a.views, on_run=show)
    rep = {"schema": SCHEMA, "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "engine_version": config.VERSION, "kind": "drawing_render", "views": len(a.views),
           "note": "GA-drawing renders of the real cabinet seen through a virtual camera turned sideways; not photographs",
           "modes": MODES, "angles": angles, "rows": summarize(rows, angles),
           "seconds": round(time.perf_counter() - t0, 1)}
    for path in (Path(a.out), WEB):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for r in rep["rows"]:
        print(f"{r['angle']:>4} deg {r['mode']:<11} placed {r['localised']}/{r['images']} inliers {r['inliers']}/"
              f"{r['anchors']} PASS {r['pass']} FAIL {r['fail']} REVIEW {r['review']} measured {r['measured_mean']} "
              f"(error {r['measured_error']})")
    print(f"written {a.out} and {WEB}")
    return rep


if __name__ == "__main__":
    main()
