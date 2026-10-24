"""Drawing-guided reading of small labels: the drawing says where every label of a placed view is, so the engine looks
there closely, the way an inspector leans in to read a small label.

A first registration places the photo on the drawing from the labels the full OCR passes read. Small labels (letters
a few pixels high) are often read only partly or not at all, which left them REVIEW or NOT_IN_VIEW. Here every label of
a placed view that is predicted inside the photo but has no certain read is read again in a window around its
predicted spot, magnified so its letters are about MAG_TEXT px high, at two magnifications. A read counts only when it
is exactly that label's tag; two magnifications agreeing count as two passes, like the OCR's own passes. At a few
pixels per letter some characters look alike (B and 8, O and 0, S and 5): a read such as 'C871' where the drawing has
CB71 is then scored by the recognizer itself (lexicon-constrained decoding: the probability of the drawing's tag over
every alignment of the recognizer's per-character output, vision.ocr.score_texts) and taken only when the recognizer
finds the tag at least half as likely as its own first reading, and clearly likelier than any neighbouring tag (CB74,
CB61 ...); such a read verifies only when both magnifications agree, and its evidence keeps what was printed. Exact reads
join the photo's tokens, the photo is registered again with them (more labels, a better fit over more of the photo)
and the next round looks for the rest. When the first registration cannot place the photo at all, the photo is read
once more with the tiles magnified further (small print) before giving up.

Nothing else changes, and nothing is invented: an exact read of the drawing's own tag is evidence that the label is
there, at the position where it was actually read (a label found off its spot is still judged by the label and order
checks). What still cannot be read stays NOT_IN_VIEW or REVIEW as before; a missing label is never inferred here.

    refine(photo, kb, tokens, reg, read=ocr.read_region, small_print=ocr.read_small_print, score=ocr.score_texts)
        -> (tokens, reg, stats)
    small_print(photo, near_boxes) -> tokens
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from kb.tags import canonical, normalize
from vision import register as rg
from vision.decode import Vocab, decode
from vision.preprocess import in_bands

MAG_TEXT = 34.0          # letter height (px) the reader sees in a guided window
MAG_MIN, MAG_MAX = 1.5, 8.0
SECOND = 1.45            # the second magnification, relative to the first
MIN_LETTER_PX = 2.5      # below this a label cannot be read, magnified or not
ACCEPT_CONF = 0.8        # an exact read below this recognition confidence is not taken
CONSTRAINED_RATIO = 0.5  # look-alike read: the tag must be at least this likely relative to the recognizer's reading
RIVAL_MARGIN = 2.0       # ... and this many times likelier than any neighbouring drawing tag
ROUNDS = 2
SMALL_PRINT_MIN_TOKENS = 5   # a photo with less text than this is not a photo of small labels
MAX_SIDE = 2400          # a magnified window's long side (vision.ocr.ZOOM_MAX_SIDE)


def _verified(r):
    """The checks' rule for a certain read (checks.builtin._verified_read)."""
    exact = r.get("method") == "exact" and normalize(r.get("raw", "")) == r.get("tag")
    conf = float(r.get("conf", 0))
    return exact and (conf >= 0.85 or (r.get("passes", 1) >= 2 and conf >= 0.75))


def _instances(rec):
    """The label instances registration places a tag by (nameplates first)."""
    inst = [i for i in rec.get("instances") or [] if i.get("kind") == "nameplate" and not i.get("stray")]
    return inst or [i for i in rec.get("instances") or [] if not i.get("stray")] or list(rec.get("instances") or [])


def targets(kb, reg, size, ignore=(), skip=()):
    """Labels of the placed views predicted inside the photo without a certain read: [{"tag", "view", "box",
    "letter_px", "rot"}], one per label instance."""
    W, H = size
    certain = {r["tag"] for r in reg.get("reads") or [] if _verified(r)}
    out = []
    for fo in reg.get("fits") or []:
        Hm = np.asarray(fo["H"], np.float64)
        persp = fo.get("model") != "similarity"
        for rec in (kb.get("views", {}).get(fo["view"]) or {}).get("tags", []):
            tag = rec["tag"]
            if tag in certain or tag in skip or not rec.get("label_expected", True):
                continue
            for inst in _instances(rec):
                c = rg._apply(Hm, [inst["center"]])[0]
                if not (0 <= c[0] < W and 0 <= c[1] < H) or in_bands(c[0], c[1], ignore):
                    continue
                s = rg.local_scale(Hm, inst["center"]) if persp else float(fo["scale_px_per_pt"])
                th = float(inst.get("size_pt") or rg.tag_text_pt(rec)) * s
                if th < MIN_LETTER_PX:
                    continue
                b = inst.get("bbox") or [inst["center"][0] - 2, inst["center"][1] - 1, inst["center"][0] + 2,
                                         inst["center"][1] + 1]
                corners = rg._apply(Hm, [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]])
                m = max(float(fo["tol_px"]), 2.0 * th)            # search margin: the fit's tolerance at least
                box = [max(0.0, corners[:, 0].min() - m), max(0.0, corners[:, 1].min() - m),
                       min(float(W), corners[:, 0].max() + m), min(float(H), corners[:, 1].max() + m)]
                if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                    continue
                out.append({"tag": tag, "view": fo["view"], "box": box, "letter_px": th, "rot": int(inst.get("rot", 0))})
    return out


def _windows(tgts):
    """Targets grouped into read windows: overlapping windows of labels at the same rotation and a similar letter size
    are read once (dense rows of terminals), as long as the magnified window stays readable in one go."""
    wins = []
    for t in sorted(tgts, key=lambda t: (t["rot"], t["box"][1], t["box"][0])):
        mag = float(np.clip(MAG_TEXT / t["letter_px"], MAG_MIN, MAG_MAX))
        for w in wins:
            if w["rot"] != t["rot"] or not 0.67 < w["letter_px"] / t["letter_px"] < 1.5:
                continue
            b = w["box"]
            if t["box"][0] > b[2] or t["box"][2] < b[0] or t["box"][1] > b[3] or t["box"][3] < b[1]:
                continue
            u = [min(b[0], t["box"][0]), min(b[1], t["box"][1]), max(b[2], t["box"][2]), max(b[3], t["box"][3])]
            if max(u[2] - u[0], u[3] - u[1]) * max(w["mag"], mag) * SECOND > MAX_SIDE:
                continue
            w.update(box=u, mag=max(w["mag"], mag), letter_px=min(w["letter_px"], t["letter_px"]))
            w["targets"].append(t)
            break
        else:
            wins.append({"box": list(t["box"]), "rot": t["rot"], "letter_px": t["letter_px"], "mag": mag,
                         "targets": [t]})
    return wins


def _inside(b, xy):
    return b[0] <= xy[0] <= b[2] and b[1] <= xy[1] <= b[3]


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def constrained(photo, tok, tag, vocab, score):
    """The look-alike read ``tok`` re-scored for ``tag`` by the recognizer: {"read", "ratio", "rival"} when it is
    taken (see module docstring), else None."""
    if score is None or not tok.get("quad"):
        return None
    rivals = [t for t in vocab.near(canonical(tag), 1) if t != tag]
    res = score(photo, tok["quad"], [tag] + rivals)
    if not res:
        return None
    best_text, best_lp = res["best"]
    lp = res["scores"][tag]
    ratio = float(np.exp(min(0.0, lp - best_lp))) if np.isfinite(best_lp) else 0.0
    rival = max(rivals, key=lambda t: res["scores"][t], default=None)
    margin = float(np.exp(lp - res["scores"][rival])) if rival else float("inf")
    if ratio < CONSTRAINED_RATIO or margin < RIVAL_MARGIN:
        return None
    return {"read": tok.get("text"), "ratio": round(ratio, 3), "rival": rival,
            "rival_margin": round(margin, 1) if np.isfinite(margin) else None}


def _read_window(photo, win, vocab, read, score=None):
    """Exact (or recognizer-confirmed look-alike) reads of the window's target tags at two magnifications ->
    {tag: [token, ...]} (photo coordinates)."""
    rots = (0,) if win["rot"] in (0, 180) else (90, 270)
    want = {t["tag"]: t for t in win["targets"]}
    found = {}
    for k, mag in enumerate((win["mag"], min(MAG_MAX * SECOND, win["mag"] * SECOND))):
        for tok in read(photo, win["box"], rotations=rots, scale=mag):
            r = decode(tok, vocab)
            t = want.get(r["tag"])
            if t is None or r["method"] not in ("exact", "confusion") or float(tok.get("conf", 0)) < ACCEPT_CONF:
                continue
            c = ((tok["box"][0] + tok["box"][2]) / 2, (tok["box"][1] + tok["box"][3]) / 2)
            if not _inside(t["box"], c):
                continue                                          # another instance's window, or a stray read
            if r["method"] == "confusion":
                why = constrained(photo, tok, r["tag"], vocab, score)
                if why is None:
                    continue
                tok = dict(tok, text=r["tag"], norm=r["tag"], constrained=why)
            found.setdefault(r["tag"], []).append(dict(tok, _mag=k))
    return found


def _token(reads):
    """One token from the reads of one label at one spot (passes = magnifications that agree). A recognizer-confirmed
    look-alike read keeps what was printed and verifies only with both magnifications (its confidence is capped below
    the single-read threshold of the checks)."""
    plain = [r for r in reads if not r.get("constrained")]
    best = max(plain or reads, key=lambda r: r["conf"])
    mags = sorted({r["_mag"] for r in reads})
    conf = best["conf"] if plain else min(best["conf"], 0.84)
    tok = {"text": best["text"], "norm": best["norm"], "box": best["box"], "quad": best.get("quad"),
           "conf": conf, "rot": best.get("rot", 0), "pass": "guided", "passes": len(mags),
           "support": [f"guided{m + 1}" for m in mags], "guided": True,
           "variants": [{k: r[k] for k in ("text", "conf", "box")} | {"pass": f"guided{r['_mag'] + 1}"} for r in reads]}
    if not plain:
        tok["constrained"] = max((r["constrained"] for r in reads), key=lambda c: c["ratio"])
    return tok


def add_tokens(tokens, new):
    """Tokens plus ``new`` ones: a new read of the same text at the same spot adds its passes to the existing token
    (another independent look agreeing), anything else is appended. Returns (tokens, number added or reinforced)."""
    out = [dict(t) for t in tokens]
    n = 0
    for nt in new:
        same = next((t for t in out if t["norm"] == nt["norm"] and _iou(t["box"], nt["box"]) >= 0.3), None)
        if same is None:
            out.append(nt)
            n += 1
            continue
        support = sorted(set(same.get("support") or [same.get("pass", "full")]) | set(nt.get("support") or []))
        if len(support) > len(same.get("support") or [None]):
            same.update(support=support, passes=len(support), conf=max(same["conf"], nt["conf"]),
                        variants=list(same.get("variants") or []) + list(nt.get("variants") or []))
            n += 1
    return out, n


def _group(reads):
    """Exact reads of one tag grouped by spot (overlapping boxes), most supported spot first."""
    groups = []
    for r in sorted(reads, key=lambda r: -r["conf"]):
        g = next((g for g in groups if any(_iou(r["box"], o["box"]) >= 0.3 for o in g)), None)
        if g is None:
            groups.append([r])
        else:
            g.append(r)
    return groups


def refine(photo, kb, tokens, reg, read=None, small_print=None, score=None, workers=4, rounds=ROUNDS):
    """Guided reads of the small labels a first registration could not read for certain (see module docstring).
    Returns (tokens, registration, stats)."""
    if read is None or small_print is None or score is None:
        from vision import ocr
        read = read or ocr.read_region
        small_print = small_print or ocr.read_small_print
        score = score or ocr.score_texts
    t0 = time.perf_counter()
    stats = {"small_print": False, "rounds": 0, "targets": 0, "windows": 0, "found": 0, "inliers_before": reg["inliers"]}
    if not reg.get("localised") and len(tokens) >= SMALL_PRINT_MIN_TOKENS:
        # text was seen but too few labels read to place the photo: the labels may be very small; read the tiles
        # holding that text once more, magnified
        extra = small_print(photo, [t["box"] for t in tokens])
        tokens, n = add_tokens(tokens, extra)
        stats.update(small_print=True, small_print_tokens=n)
        if n:
            reg = rg.register(tokens, kb, photo)
    vocab = Vocab(kb.get("vocabulary") or ())
    tried = set()
    for _ in range(rounds):
        if not reg.get("localised"):
            break
        tgts = targets(kb, reg, photo["size"], photo.get("ignore") or (), tried)
        if not tgts:
            break
        tried |= {t["tag"] for t in tgts}
        wins = _windows(tgts)
        stats["rounds"] += 1
        stats["targets"] += len({t["tag"] for t in tgts})
        stats["windows"] += len(wins)
        with ThreadPoolExecutor(max(1, min(int(workers), len(wins))), thread_name_prefix="ee-guided") as pool:
            results = list(pool.map(lambda w: _read_window(photo, w, vocab, read, score), wins))
        new = []
        for found in results:
            for tag, reads in found.items():
                new += [_token(g) for g in _group(reads)]
        tokens, n = add_tokens(tokens, new)
        stats["found"] += len({t["norm"] for t in new})
        stats["constrained"] = stats.get("constrained", 0) + len({t["norm"] for t in new if t.get("constrained")})
        if not n:
            break
        reg = rg.register(tokens, kb, photo)
    stats.update(inliers_after=reg["inliers"], seconds=round(time.perf_counter() - t0, 2))
    return tokens, reg, stats
