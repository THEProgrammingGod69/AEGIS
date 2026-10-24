"""Photo-sized images of a real cabinet rendered from its GA drawing, for when no photos of the cabinet are available.

Each GA view (the cabinet outline of one side) is rendered so that its device labels are about as large as in a phone
photo taken 1 m away, then given mild camera effects: perspective, light gradient, grey cast, blur, noise and JPEG.
These are not photos. Wiring, shadows and occlusion are missing and every label sits exactly where the drawing puts
it, so results on them are an upper bound for real photos. forge_real.py plants faults in them like in photos and
eval_gap.py scores them; render_info.json marks the folder so reports say "drawing render", never "photo".

    python render_real.py [--pdf PDF] [--out DIR] [--dpi 600] [--seed 7]
"""
import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image

import config
from kb import drawing_kb

REAL = config.BASE.parent / "data" / "emerson"
INFO = "render_info.json"


def render_view(pdf, view, dpi, margin_pt=10):
    """RGB render of one GA view (its cabinet outline plus a small margin)."""
    x0, y0, x1, y1 = view["bbox"]
    with pymupdf.open(pdf) as doc:
        page = doc[view["page"] - 1]
        clip = pymupdf.Rect(x0 - margin_pt, y0 - margin_pt, x1 + margin_pt, y1 + margin_pt) & page.rect
        pix = page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()


def camera(rgb, rng):
    """Mild camera effects on a clean render: grey cast, light gradient, perspective, blur, noise, JPEG."""
    import cv2
    h, w = rgb.shape[:2]
    img = rgb.astype(np.float32) * rng.uniform(0.80, 0.90) + rng.uniform(8, 22)
    img *= np.linspace(rng.uniform(0.85, 0.95), rng.uniform(1.0, 1.1), w, dtype=np.float32)[None, :, None]
    img *= np.array([rng.uniform(0.96, 1.04) for _ in range(3)], np.float32)[None, None, :]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + np.float32([[rng.uniform(-0.025, 0.025) * w, rng.uniform(-0.025, 0.025) * h] for _ in range(4)])
    img = cv2.warpPerspective(np.clip(img, 0, 255).astype(np.uint8), cv2.getPerspectiveTransform(src, dst), (w, h),
                              borderValue=(70, 72, 76))
    img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.6, 1.0))
    img = np.clip(img.astype(np.float32) + rng.normal(0, 4.0, img.shape), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Render photo-sized images of a real cabinet from its GA drawing")
    ap.add_argument("--pdf", default=str(REAL / "Sanitized_Cabinet_Drawing.pdf"))
    ap.add_argument("--out", default=str(REAL.parent / "emerson_render"))
    ap.add_argument("--dpi", type=int, default=600)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    pdf, out = Path(a.pdf), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    kb = drawing_kb.build_kb(str(pdf))
    if not kb.get("views"):
        raise SystemExit(f"{pdf.name}: no GA view with device tags, nothing to render")
    rng = np.random.default_rng(a.seed)
    shutil.copyfile(pdf, out / pdf.name)
    views = {}
    for name, view in kb["views"].items():
        img = camera(render_view(str(pdf), view, a.dpi), rng)
        Image.fromarray(img).save(out / f"{name}.jpg", quality=92)
        views[name] = {"file": f"{name}.jpg", "size": [img.shape[1], img.shape[0]], "tags": len(view["tags"])}
        print(f"{name}.jpg: {img.shape[1]}x{img.shape[0]} px, {len(view['tags'])} drawing tags")
    info = {"kind": "drawing_render", "cabinet": kb["cabinet"], "drawing": pdf.name, "dpi": a.dpi, "seed": a.seed,
            "views": views, "note": "rendered from the GA drawing with camera effects; not photographs"}
    (out / INFO).write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"{len(views)} renders of cabinet {kb['cabinet']} in {out}")


if __name__ == "__main__":
    main()
