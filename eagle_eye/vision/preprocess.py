"""Photo loading for the real-cabinet engine: EXIF orientation, ignore bands and a quality score.

Every photo coordinate in the engine refers to the EXIF-transposed, full-resolution image returned here. Phone
cameras burn a watermark (bottom-left, e.g. "moto g96 5G / EMERSON.PVT.LTD") and a date/time stamp (bottom-right)
into the pixels; both are reported as ``ignore`` bands so OCR never mistakes them for cabinet labels.

Band sizes are fractions of the photo's *short* side (the overlay scales with it, in portrait and landscape alike):
``EAGLE_IGNORE_WATERMARK="0.25,0.10"`` (width, height from the bottom-left corner),
``EAGLE_IGNORE_TIMESTAMP="0.28,0.09"`` (width, height from the bottom-right corner); ``"0"`` disables a band.
"""
import hashlib
import io
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

QUALITY_SIDE = 1536          # quality metrics are measured on a downscale with this long side
BLUR_SHARP = 150.0           # variance of Laplacian (on the downscale) treated as fully sharp ...
BLUR_BLURRY = 40.0           # ... and as blurry
GLARE_LEVEL = 250            # a pixel is saturated when all channels are >= this


def _band_env(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if raw in ("0", "off", "none"):
        return None
    try:
        w, h = (float(v) for v in raw.split(","))
        return (w, h)
    except ValueError:
        return default


WATERMARK = _band_env("EAGLE_IGNORE_WATERMARK", (0.25, 0.10))
TIMESTAMP = _band_env("EAGLE_IGNORE_TIMESTAMP", (0.28, 0.09))


def ignore_bands(width, height, watermark=WATERMARK, timestamp=TIMESTAMP):
    """Watermark (bottom-left) and timestamp (bottom-right) bands ``[[x0, y0, x1, y1], ...]`` in photo pixels."""
    short = min(width, height)
    out = []
    if watermark:
        out.append([0, round(height - watermark[1] * short), round(watermark[0] * short), height])
    if timestamp:
        out.append([round(width - timestamp[0] * short), round(height - timestamp[1] * short), width, height])
    return out


def in_bands(x, y, bands):
    """True when the point lies inside one of the ignore bands."""
    return any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in bands)


def quality(rgb):
    """Blur, brightness and glare of an RGB photo plus a 0..1 score and human-readable issues."""
    h, w = rgb.shape[:2]
    f = min(1.0, QUALITY_SIDE / max(h, w))
    small = cv2.resize(rgb, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else rgb
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean() / 255.0)
    glare = float(np.mean(np.all(small >= GLARE_LEVEL, axis=2)))

    sharp = float(np.clip((np.log(max(blur, 1e-3)) - np.log(BLUR_BLURRY)) / (np.log(BLUR_SHARP) - np.log(BLUR_BLURRY)),
                          0, 1))
    light = float(np.clip(min((brightness - 0.08) / 0.17, (0.95 - brightness) / 0.15), 0, 1))
    clean = float(np.clip(1 - (glare - 0.02) / 0.13, 0, 1))
    res = float(np.clip(min(h, w) / 1500.0, 0, 1))
    score = round(min(sharp, light, clean, res) * 0.6 + (sharp + light + clean + res) / 4 * 0.4, 3)

    issues = []
    if blur < BLUR_BLURRY:
        issues.append("photo is blurry")
    elif blur < (BLUR_BLURRY * BLUR_SHARP) ** 0.5:
        issues.append("photo is slightly blurry")
    if brightness < 0.18:
        issues.append("photo is too dark")
    elif brightness > 0.85:
        issues.append("photo is overexposed")
    if glare > 0.05:
        issues.append(f"glare on {glare:.0%} of the photo")
    if min(h, w) < 1500:
        issues.append(f"low resolution ({w}x{h} px): small labels may be unreadable")
    return {"blur": round(blur, 1), "brightness": round(brightness, 3), "glare": round(glare, 4), "score": score,
            "issues": issues}


def load_photo(src, ignore=None):
    """Load a photo for inspection.

    ``src`` is a path, raw file bytes, a PIL image or an RGB ``np.uint8`` array (already upright). Returns
    ``{"rgb", "sha", "size": [w, h], "exif_orientation", "ignore", "quality", "name"}``; ``rgb`` is the
    EXIF-transposed image at full resolution and ``sha`` the first 16 hex digits of the SHA-256 of the file bytes
    (of the pixel buffer for arrays). ``ignore`` overrides the default watermark/timestamp bands.
    """
    name = None
    if isinstance(src, np.ndarray):
        rgb = src
        if rgb.ndim == 2:
            rgb = cv2.cvtColor(rgb, cv2.COLOR_GRAY2RGB)
        elif rgb.shape[2] == 4:
            rgb = cv2.cvtColor(rgb, cv2.COLOR_RGBA2RGB)
        rgb = np.ascontiguousarray(rgb, dtype=np.uint8)
        sha = hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()[:16]
        orientation = 1
    else:
        if isinstance(src, Image.Image):
            buf = io.BytesIO()
            src.save(buf, format="PNG")
            data, im = buf.getvalue(), src
        else:
            if isinstance(src, (bytes, bytearray)):
                data = bytes(src)
            else:
                name = Path(src).name
                data = Path(src).read_bytes()
            im = Image.open(io.BytesIO(data))
        sha = hashlib.sha256(data).hexdigest()[:16]
        try:
            orientation = int(im.getexif().get(0x0112, 1) or 1)
        except Exception:  # noqa: BLE001 - malformed EXIF must not stop an inspection
            orientation = 1
        rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
    h, w = rgb.shape[:2]
    return {"rgb": rgb, "sha": sha, "size": [int(w), int(h)], "exif_orientation": orientation,
            "ignore": [list(map(int, b)) for b in ignore] if ignore is not None else ignore_bands(w, h),
            "quality": quality(rgb), "name": name}
