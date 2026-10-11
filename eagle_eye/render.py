"""Photo renderer + FAULT FORGE.
Renders an 'as-built' HD photo of the cabinet from the layout, with planted faults and
realistic camera effects (perspective, rotation, lighting gradient, colour cast, blur, noise, JPEG).
Ground truth of planted faults is returned so we can score ourselves.
"""
import copy, random, io
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from spec import base_layout, wire_list, label_box, ferrule_box, W, H

PX = 4  # render px per mm
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_C = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
WIRE_RGB = {"BN": (120, 66, 30), "BU": (30, 80, 190), "RD": (200, 30, 30), "BK": (25, 25, 25),
            "GNYE": None, "GY": (150, 150, 150), "VT": (130, 50, 160)}

def font(sz, cond=False):
    return ImageFont.truetype(FONT_C if cond else FONT, int(sz))

FAULT_TYPES = ["missing_component", "swap_breakers", "missing_label", "wrong_label",
               "missing_ferrule", "wrong_ferrule", "wrong_colour"]

def apply_faults(faults):
    """Return as-built devices/terms/wires after planting faults."""
    devs, terms = base_layout()
    wires = wire_list()
    for d in devs:
        d.update(present=True, label=d["tag"])
    for w in wires:
        w.update(has_ferrule=True, ferrule_txt=w["ferrule"], built_colour=w["colour"])
    by = {d["tag"]: d for d in devs}
    for f in faults:
        k = f["type"]
        if k == "missing_component":
            by[f["tag"]]["present"] = False
        elif k == "missing_label":
            by[f["tag"]]["label"] = None
        elif k == "wrong_label":
            by[f["tag"]]["label"] = f["text"]
        elif k == "swap_breakers":
            a, b = by[f["a"]], by[f["b"]]
            a["x"], b["x"] = b["x"], a["x"]
        elif k == "missing_ferrule":
            wires[f["n"] - 1]["has_ferrule"] = False
        elif k == "wrong_ferrule":
            wires[f["n"] - 1]["ferrule_txt"] = f["text"]
        elif k == "wrong_colour":
            wires[f["n"] - 1]["built_colour"] = f["colour"]
    return devs, terms, wires

def _r(d, x, y, w, h, fill, outline=None, width=1):
    d.rectangle([x * PX, y * PX, (x + w) * PX, (y + h) * PX], fill=fill, outline=outline, width=width)

def draw_label(d, box, text, rng):
    x, y, w, h = box
    f = font(h * PX * 0.72, cond=True)
    tw = d.textlength(text, font=f) / PX
    if w > tw + 3:  # sticker hugs the text, left-aligned where the GA prints the tag
        w = tw + 5
    _r(d, x, y, w, h, (246, 246, 240), (60, 60, 60), 2)
    d.text(((x + w / 2 - tw / 2) * PX, (y + h * 0.12) * PX), text, fill=(15, 15, 15), font=f)

def render_backplate(devs, terms, wires, rng):
    img = Image.new("RGB", (W * PX, H * PX), (196, 198, 192))
    d = ImageDraw.Draw(img)
    # galvanised texture
    arr = np.array(img).astype(np.int16)
    arr += rng.integers(-6, 7, arr.shape[:2])[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(img)
    # ducts
    for (x, y, w, h) in [(0, 185, W, 40), (330, 225, 40, 500)]:
        _r(d, x, y, w, h, (120, 124, 128), (90, 90, 95), 3)
        if w > h:
            for k in range(int(x) + 8, int(x + w) - 4, 14):
                _r(d, k, y + 3, 6, h - 6, (100, 104, 108))
        else:
            for k in range(int(y) + 8, int(y + h) - 4, 14):
                _r(d, x + 3, k, w - 6, 6, (100, 104, 108))
    # DIN rail behind breakers
    _r(d, 330, 92, 150, 20, (170, 172, 176), (130, 130, 130), 2)
    for dv in devs:
        if not dv["present"]:
            continue
        x, y, w, h = dv["x"], dv["y"], dv["w"], dv["h"]
        t = dv["type"]
        if t == "psu":
            _r(d, x, y, w, h, (52, 74, 120), (25, 35, 60), 4)
            _r(d, x + 8, y + 40, w - 16, 30, (40, 58, 96))
            d.text(((x + 14) * PX, (y + 48) * PX), "SolaHD", fill=(220, 220, 225), font=font(9 * PX))
            for k in range(4):
                _r(d, x + 10 + k * 18, y + h - 26, 13, 13, (210, 210, 210), (80, 80, 80), 2)
            for k in range(3):
                d.ellipse([(x + w - 30 + k * 8) * PX, (y + 25) * PX, (x + w - 25 + k * 8) * PX, (y + 30) * PX], fill=(90, 230, 90))
        elif t == "controller":
            _r(d, x, y, w, h, (60, 62, 66), (30, 30, 30), 4)
            for k in range(6):
                _r(d, x + 10, y + 30 + k * 14, w - 20, 8, (85, 88, 92))
        elif t == "breaker":
            _r(d, x, y, w, h, (236, 236, 232), (110, 110, 110), 3)
            _r(d, x + w / 2 - 5, y + 40, 10, 20, (40, 40, 40))
            _r(d, x + 4, y + 70, w - 8, 10, (200, 40, 40))
        elif t == "baseplate":
            _r(d, x, y, w, h, (70, 72, 76), (35, 35, 35), 3)
            for k in range(8):
                _r(d, x + 72 + k * 24, y + 10, 20, h - 20, (238, 196, 30), (120, 95, 10), 2)
        elif t == "earth":
            _r(d, x, y, w, h, (190, 150, 60), (110, 85, 30), 3)
            for k in range(14):
                d.ellipse([(x + 45 + k * 35) * PX, (y + 10) * PX, (x + 55 + k * 35) * PX, (y + 20) * PX], fill=(120, 95, 40))
        if dv["label"]:
            draw_label(d, label_box(dv), dv["label"], rng)
    # terminal strip
    _r(d, 395, 255, 60, 8 * 54, (150, 152, 156), (90, 90, 90), 2)
    for t, w in zip(terms, wires):
        _r(d, t["x"], t["y"], t["w"], t["h"], (60, 110, 190) if w["colour"] != "GNYE" else (40, 150, 60), (30, 50, 90), 2)
        d.text(((t["x"] + 4) * PX, (t["y"] + 6) * PX), str(t["n"]), fill=(255, 255, 255), font=font(11 * PX))
        # wire
        fx, fy, fw, fh = ferrule_box(t)
        cy = (t["y"] + t["h"] / 2) * PX
        x0, x1 = (t["x"] + t["w"] - 4) * PX, (W - 8) * PX
        col = WIRE_RGB[w["built_colour"]]
        th = int(5.5 * PX)
        if col is None:
            d.line([(x0, cy), (x1, cy)], fill=(40, 160, 60), width=th)
            for k in range(int(x0), int(x1), 9 * PX):
                d.line([(k, cy), (min(k + 4 * PX, x1), cy)], fill=(225, 205, 30), width=th)
        else:
            d.line([(x0, cy), (x1, cy)], fill=col, width=th)
        if w["has_ferrule"]:
            _r(d, fx, fy, fw, fh, (250, 250, 246), (150, 150, 150), 2)
            f = font(fh * PX * 0.62, cond=True)
            tw = d.textlength(w["ferrule_txt"], font=f)
            d.text(((fx + fw / 2) * PX - tw / 2, (fy + fh * 0.16) * PX), w["ferrule_txt"], fill=(10, 10, 10), font=f)
    return img

def camera(img, rng, strength=1.0):
    """Place backplate in a dark cabinet and shoot it with a slightly bad camera."""
    bp = np.array(img)
    h, w = bp.shape[:2]
    out_w, out_h = 2200, 2900
    j = lambda m: rng.uniform(-m, m) * strength
    margin = 130
    sx = (out_w - 2 * margin) / w; sy = (out_h - 2 * margin) / h; s = min(sx, sy)
    cw, ch = w * s, h * s
    ox, oy = (out_w - cw) / 2, (out_h - ch) / 2
    dst = np.float32([[ox + j(60), oy + j(60)], [ox + cw + j(60), oy + j(60)],
                      [ox + cw + j(60), oy + ch + j(60)], [ox + j(60), oy + ch + j(60)]])
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    M = cv2.getPerspectiveTransform(src, dst)
    bg = np.full((out_h, out_w, 3), 38, np.uint8)
    bg[:] = (34, 36, 40)
    photo = cv2.warpPerspective(bp, M, (out_w, out_h), dst=bg, borderMode=cv2.BORDER_TRANSPARENT,
                                flags=cv2.INTER_AREA)
    ph = photo.astype(np.float32)
    # lighting gradient
    gx, gy = np.meshgrid(np.linspace(-1, 1, out_w), np.linspace(-1, 1, out_h))
    a, b = rng.uniform(-1, 1, 2)
    light = 1.0 + (0.16 * strength) * (a * gx + b * gy)
    ph *= light[..., None]
    # colour cast (bad white balance)
    cast = 1 + rng.uniform(-0.07, 0.07, 3) * strength
    ph *= cast[None, None, :]
    ph += rng.normal(0, 3.5 * strength, ph.shape)
    ph = np.clip(ph, 0, 255).astype(np.uint8)
    sig = rng.uniform(0.3, 1.1) * strength
    if sig > 0.2:
        ph = cv2.GaussianBlur(ph, (0, 0), sig)
    ok, enc = cv2.imencode(".jpg", ph[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, int(rng.uniform(82, 93))])
    ph = cv2.imdecode(enc, cv2.IMREAD_COLOR)[..., ::-1]
    return Image.fromarray(ph), M

def random_faults(rng, k=None):
    devs, terms = base_layout()
    k = int(rng.integers(0, 5)) if k is None else k
    faults, used = [], set()
    tries = 0
    while len(faults) < k and tries < 50:
        tries += 1
        t = FAULT_TYPES[int(rng.integers(0, len(FAULT_TYPES)))]
        if t == "missing_component":
            tag = ["PS11", "PS12", "D12", "CB41", "CB42", "CB43", "CB44", "1CBP01", "1CBP02", "1CBP03", "1CBP04"][int(rng.integers(0, 11))]
            f = dict(type=t, tag=tag); keys = {tag}
        elif t in ("missing_label", "wrong_label"):
            tag = [d["tag"] for d in devs][int(rng.integers(0, len(devs)))]
            f = dict(type=t, tag=tag); keys = {tag, "L" + tag}
            if t == "wrong_label":
                swaps = {"PS11": "PS17", "PS12": "PS21", "D12": "D21", "CB41": "CB14", "CB42": "CB24",
                         "CB43": "CB34", "CB44": "CB47", "1CBP01": "1CBP10", "1CBP02": "1CBP20",
                         "1CBP03": "1CBP08", "1CBP04": "1CBP06", "PE": "PN"}
                f["text"] = swaps[tag]
        elif t == "swap_breakers":
            i = int(rng.integers(1, 4)); a, b = f"CB4{i}", f"CB4{i+1}"
            f = dict(type=t, a=a, b=b); keys = {a, b, "L" + a, "L" + b, "RAIL"}
        else:
            n = int(rng.integers(1, 9)); f = dict(type=t, n=n); keys = {f"W{n}"}
            if t == "wrong_ferrule":
                m = n % 8 + 1; f["text"] = wire_list()[m - 1]["ferrule"]
            if t == "wrong_colour":
                cur = wire_list()[n - 1]["colour"]
                f["colour"] = [c for c in ["BN", "BU", "RD", "BK", "GNYE"] if c != cur][int(rng.integers(0, 4))]
            if t == "missing_ferrule" and any(x["type"] == "wrong_ferrule" and x["n"] == n for x in faults):
                continue
        if keys & used:
            continue
        # a missing component cannot also have label/order faults
        used |= keys | ({"L" + f["tag"]} if t == "missing_component" else set())
        if t == "missing_component" and f["tag"].startswith("CB"):
            used.add("RAIL")
        faults.append(f)
    return faults

def render(faults, seed=0, strength=1.0):
    rng = np.random.default_rng(seed)
    devs, terms, wires = apply_faults(faults)
    bp = render_backplate(devs, terms, wires, rng)
    photo, M = camera(bp, rng, strength)
    return photo, bp

if __name__ == "__main__":
    import os
    os.makedirs("out", exist_ok=True)
    demo = [dict(type="missing_component", tag="PS12"), dict(type="swap_breakers", a="CB43", b="CB44"),
            dict(type="missing_label", tag="1CBP03"), dict(type="missing_ferrule", n=3)]
    p, bp = render(demo, seed=7)
    p.save("out/demo_photo.jpg", quality=92)
    print(p.size)
