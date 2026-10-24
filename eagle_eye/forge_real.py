"""Phase 8 - Fault Forge for real photos: planted-fault variants of real cabinet photos with an answer key.

Fault Forge (render.py) plants faults in generated cabinets; this module plants them in photos of the real cabinet, so
the real-cabinet engine is measured on the photos it will actually see. Faults are planted where the engine itself read
a label with certainty at the spot the drawing gives it (so the answer key is exact). Devices here often carry two
labels (on the device and on the rail): a fault changes all of them, or the other label would still be correct.

    missing   every label of the device is painted out (inpainting)            -> MISS-<tag> must be flagged
    wrong     every label of the device is reprinted with a tag-shaped string the drawing does not list
                                                                                 -> LBL-<tag> / UNK-<text>
    swap      two labels of one ordered group trade places                       -> ORD-<group> (or their LBL items)

A planted fault is *caught* when one of its expected items ends FAIL or REVIEW; FAIL on any other item that is not a
listed drawing deviation is a false alarm. Variants and ``answer_key.json`` go to ``data/emerson/forged/`` (never in git).

    python forge_real.py [--photos DIR] [--pdf PDF] [--out DIR] [--per-photo 3] [--seed 7]
"""
import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config
from kb import drawing_kb
from kb.tags import family_of, normalize, tag_sort_key
from vision import ocr
from vision.preprocess import load_photo
from vision.register import register

REAL = config.BASE.parent / "data" / "emerson"
SCHEMA = "eagle-eye-forge-real/1"


def _box(r, grow=0.18, size=None):
    x0, y0, x1, y1 = r["box"]
    gx, gy = (x1 - x0) * grow, (y1 - y0) * grow
    b = [x0 - gx, y0 - gy, x1 + gx, y1 + gy]
    if size:
        b = [max(0, b[0]), max(0, b[1]), min(size[0], b[2]), min(size[1], b[3])]
    return [int(round(v)) for v in b]


def paint_out(rgb, box):
    """Remove a label: inpaint its box from the surrounding pixels."""
    mask = np.zeros(rgb.shape[:2], np.uint8)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = 255
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    out = cv2.inpaint(bgr, mask, max(3, int(0.15 * min(x1 - x0, y1 - y0))), cv2.INPAINT_TELEA)
    return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)


def rewrite(rgb, box, text, rot=0):
    """Replace a label's print: fill with the label's own background tone, then print ``text`` in its place."""
    x0, y0, x1, y1 = box
    patch = rgb[y0:y1, x0:x1]
    bg = tuple(int(v) for v in np.percentile(patch.reshape(-1, 3), 85, axis=0))
    ink = tuple(int(v) for v in np.percentile(patch.reshape(-1, 3), 8, axis=0))
    w, h = (x1 - x0, y1 - y0) if rot in (0, 180) else (y1 - y0, x1 - x0)
    tile = Image.new("RGB", (max(4, w), max(4, h)), bg)
    d = ImageDraw.Draw(tile)
    size = max(8, int(h * 0.72))
    font = ImageFont.truetype(config.font("DejaVuSans-Bold.ttf"), size)
    while size > 8 and d.textlength(text, font=font) > 0.92 * w:
        size -= 1
        font = ImageFont.truetype(config.font("DejaVuSans-Bold.ttf"), size)
    tw = d.textlength(text, font=font)
    d.text(((w - tw) / 2, (h - size) / 2 - size * 0.1), text, fill=ink, font=font)
    if rot == 90:
        tile = tile.rotate(-90, expand=True)
    elif rot == 270:
        tile = tile.rotate(90, expand=True)
    out = rgb.copy()
    out[y0:y1, x0:x1] = np.asarray(tile.resize((x1 - x0, y1 - y0)))
    return out


def swap(rgb, a, b):
    """Swap the pixels of two label boxes (each resized into the other's box)."""
    out = rgb.copy()
    pa = rgb[a[1]:a[3], a[0]:a[2]].copy()
    pb = rgb[b[1]:b[3], b[0]:b[2]].copy()
    out[a[1]:a[3], a[0]:a[2]] = cv2.resize(pb, (a[2] - a[0], a[3] - a[1]), interpolation=cv2.INTER_AREA)
    out[b[1]:b[3], b[0]:b[2]] = cv2.resize(pa, (b[2] - b[0], b[3] - b[1]), interpolation=cv2.INTER_AREA)
    return out


def _wrong_text(tag, vocab, rng):
    """A tag of the same family and shape that the drawing set does not list (so it is unambiguously wrong)."""
    digits = [i for i, ch in enumerate(tag) if ch.isdigit()]
    for _ in range(40):
        i = digits[-1] if rng.random() < 0.7 else rng.choice(digits)
        ch = str(rng.randrange(10))
        t = tag[:i] + ch + tag[i + 1:]
        if t != tag and t not in vocab and family_of(t) == family_of(tag):
            return t
    return None


def _candidates(reg):
    """Labels read with certainty at the spot the drawing gives them (one read per tag)."""
    best = {}
    for r in reg["reads"]:
        if r.get("anchor") and r.get("method") == "exact" and r.get("at_predicted") and r["passes"] >= 2:
            if r["tag"] not in best or r["conf"] > best[r["tag"]]["conf"]:
                best[r["tag"]] = r
    return best


def forge_photo(path, kb, rng, n=3, kinds=("missing", "wrong", "swap")):
    """Planted-fault variants of one photo: [(rgb, fault dict)], one fault per variant."""
    photo = load_photo(path)
    tokens = ocr.read_photo(photo)
    reg = register(tokens, kb, photo)
    cands = _candidates(reg)
    vocab = set(kb["vocabulary"])
    out, used = [], set()
    tags = sorted(cands, key=tag_sort_key)
    rng.shuffle(tags)
    plan = [kinds[i % len(kinds)] for i in range(n)]
    for kind in plan:
        if kind == "swap":
            pairs = []
            for g in kb.get("groups") or []:
                order = [t for t in g["order"] if t in cands and t not in used]
                pairs += [(a, b, g) for a, b in zip(order, order[1:])]
            if not pairs:
                continue
            a, b, g = pairs[rng.randrange(len(pairs))]
            ra = sorted((x for x in reg["reads"] if x["tag"] == a), key=lambda x: (x["center"][0], x["center"][1]))
            rb = sorted((x for x in reg["reads"] if x["tag"] == b), key=lambda x: (x["center"][0], x["center"][1]))
            if len(ra) != len(rb) or any(x["rot"] != y["rot"] for x, y in zip(ra, rb)):
                continue
            img = photo["rgb"]
            for x, y in zip(ra, rb):                  # each label of a trades places with the matching label of b
                img = swap(img, _box(x, 0.1, photo["size"]), _box(y, 0.1, photo["size"]))
            used |= {a, b}
            out.append((img, {"type": "swap", "tags": [a, b], "group": g["id"],
                              "expect": [f"ORD-{g['id']}", f"LBL-{a}", f"LBL-{b}"],
                              "text": f"{a} and {b} labels swapped ({g['id']})"}))
            continue
        pool = [t for t in tags if t not in used]
        if not pool:
            break
        t = pool[0]
        used.add(t)
        reads = [x for x in reg["reads"] if x["tag"] == t]          # every label of the device, not just one
        n = len(reads)
        if kind == "missing":
            img = photo["rgb"]
            for x in reads:
                img = paint_out(img, _box(x, 0.18, photo["size"]))
            out.append((img, {"type": "missing", "tags": [t], "expect": [f"MISS-{t}", f"LBL-{t}"],
                              "text": f"label{'s' if n > 1 else ''} of {t} removed ({n})"}))
        else:
            wt = _wrong_text(t, vocab, rng)
            if not wt:
                continue
            img = photo["rgb"]
            for x in reads:
                img = rewrite(img, _box(x, 0.05, photo["size"]), wt, x["rot"])
            out.append((img, {"type": "wrong", "tags": [t], "wrong": wt, "expect": [f"LBL-{t}", f"UNK-{wt}", f"MISS-{t}"],
                              "text": f"label{'s' if n > 1 else ''} of {t} reprinted as {wt} ({n})"}))
    return out, {"tokens": len(tokens), "localised": reg["localised"], "candidates": len(cands)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plant faults in real cabinet photos (answer key included)")
    ap.add_argument("--photos", default=str(REAL))
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-photo", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    src = Path(a.photos)
    pdf = Path(a.pdf) if a.pdf else next(iter(sorted(src.glob("*.pdf"))), None)
    if not pdf or not pdf.exists():
        raise SystemExit(f"no drawing set (PDF) in {src}")
    out_dir = Path(a.out) if a.out else src / "forged"
    out_dir.mkdir(parents=True, exist_ok=True)
    kb = drawing_kb.build_kb(str(pdf))
    rng = random.Random(a.seed)
    key = {"schema": SCHEMA, "drawing": pdf.name, "seed": a.seed, "variants": {}}
    for p in sorted(x for x in src.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png")):
        variants, info = forge_photo(p, kb, rng, a.per_photo)
        print(f"{p.name}: {info['candidates']} certain labels, {len(variants)} variant(s)")
        for k, (rgb, fault) in enumerate(variants, 1):
            name = f"{p.stem}__{fault['type']}{k}.jpg"
            Image.fromarray(rgb).save(out_dir / name, quality=92)
            key["variants"][name] = dict(fault, source=p.name)
            print(f"   {name}: {fault['text']}")
    (out_dir / "answer_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(key['variants'])} variants + answer_key.json in {out_dir}")


if __name__ == "__main__":
    main()
