"""Precision under bad photos: degraded shots of the samples may lose findings to REVIEW, never gain a false FAIL."""
import cv2
import numpy as np
import pytest

import config
import service

MODERATE = dict(rotate=6, keystone=0.06, bright=0.8, contrast=0.9, blur=1.2, noise=8, warm=0.4, glare=0.25, q=75)
DIM_TILTED = dict(rotate=-10.5, keystone=0.11, bright=0.65, contrast=1.16, blur=1.8, noise=5.6, warm=-0.4, glare=0.57, q=82)


def degrade(img, p, seed=0):
    """Phone-camera defects: keystone, roll, light, contrast, blur, colour cast, glare, sensor noise, JPEG."""
    h, w = img.shape[:2]
    k = p["keystone"]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * k / 2, 0], [w - w * k / 2, 0], [w, h], [0, h]])
    out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(36, 31, 28))
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -p["rotate"], 1.0)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    W, H = int(h * s + w * c), int(h * c + w * s)
    M[0, 2] += W / 2 - w / 2
    M[1, 2] += H / 2 - h / 2
    out = cv2.warpAffine(out, M, (W, H), borderValue=(36, 31, 28)).astype(np.float32)
    out = ((out - 128) * p["contrast"] + 128) * p["bright"]
    out = cv2.GaussianBlur(out, (0, 0), p["blur"])
    tint = np.float32([40, 150, 255]) if p["warm"] > 0 else np.float32([255, 140, 60])
    out = out * (1 - 0.3 * abs(p["warm"])) + tint * 0.3 * abs(p["warm"])
    yy, xx = np.mgrid[0:H, 0:W]
    r = max(W, H) * (0.18 + 0.14 * p["glare"])
    g = np.exp(-(((xx - W * 0.68) ** 2 + (yy - H * 0.3) ** 2) / (2 * (r / 2) ** 2))) * 255 * (0.35 + 0.6 * p["glare"])
    out = 255 - (255 - out) * (1 - g[..., None] / 255)
    out += np.random.default_rng(seed).normal(0, p["noise"], out.shape[:2])[..., None]
    ok, buf = cv2.imencode(".jpg", np.clip(out, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, p["q"]])
    return buf.tobytes()


@pytest.mark.parametrize("sid,preset", [("01", DIM_TILTED), ("04", MODERATE), ("05", MODERATE)])
def test_degraded_photo_never_adds_a_false_fail(runs_dir, tmp_path, sid, preset):
    photo = tmp_path / "degraded.jpg"
    photo.write_bytes(degrade(cv2.imread(str(service.sample_path(sid))), preset))
    meta = service.run_inspection(photo, reports=False)
    expected = {i["id"] for i in next(s for s in service.samples() if s["id"] == sid)["issues"] if i["result"] == "FAIL"}
    fails = {i["id"] for i in meta["issues"] if i["result"] == "FAIL"}
    assert fails <= expected, f"false FAIL on a degraded photo: {sorted(fails - expected)}"


def test_mild_degradation_still_catches_everything(runs_dir, tmp_path):
    mild = dict(rotate=3, keystone=0, bright=0.92, contrast=1, blur=0.6, noise=4, warm=0.2, glare=0.0, q=85)
    photo = tmp_path / "mild.jpg"
    photo.write_bytes(degrade(cv2.imread(str(next(config.SAMPLES.glob("01_*.jpg")))), mild))
    fails = {i["id"] for i in service.run_inspection(photo, reports=False)["issues"] if i["result"] == "FAIL"}
    assert fails == {"GA-PS12", "ORD-RAIL-1", "LBL-1CBP03", "FER-X3:3"}
