"""OCR benchmark on real cabinet photos: timing, decoded vocabulary tags, unknown tag-like reads, ferrules.

    python -P -E eagle_eye/vision/bench_ocr.py data/emerson/*.jpg --pdf data/emerson/Sanitized_Cabinet_Drawing.pdf
           [--mode FULL|FAST] [--workers N] [--no-cache]

The vocabulary comes from ``kb.drawing_kb.build_kb`` when it is available, else from every tag-shaped word of the
PDF. A debug JPEG with every token boxed (green: vocabulary tag, orange: unknown tag-like read, blue: ferrule,
grey: other text, red: ignore bands) is written to ``config.DATA/ocr_debug``.
"""
import argparse
import glob
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import config  # noqa: E402
from kb.tags import family_of, normalize, tag_sort_key  # noqa: E402
from vision import ocr  # noqa: E402
from vision.decode import Vocab, decode, parse_ferrule  # noqa: E402
from vision.preprocess import load_photo  # noqa: E402

DEBUG_DIR = config.DATA / "ocr_debug"


def pdf_vocabulary(pdf):
    """Every tag-shaped word of the PDF (plus 'FILTER 1' style pairs): a stand-in when no cabinet model exists."""
    import pymupdf
    vocab = set()
    with pymupdf.open(pdf) as doc:
        for page in doc:
            words = [w[4] for w in page.get_text("words")]
            for a, b in zip(words, words[1:] + [""]):
                for cand in (a, a + b if normalize(a) == "FILTER" else ""):
                    n = normalize(cand)
                    if n and family_of(n):
                        vocab.add(n)
    return sorted(vocab, key=tag_sort_key)


def vocabulary(pdf):
    """(tags, source): the cabinet model's vocabulary when drawing_kb works, else the PDF word scan."""
    try:
        from kb import drawing_kb
        kb = drawing_kb.build_kb(pdf)
        if kb.get("vocabulary"):
            return kb["vocabulary"], "drawing_kb"
    except Exception as e:  # noqa: BLE001 - the KB is built by another track and may be unfinished
        print(f"(drawing_kb unavailable: {type(e).__name__}: {e}; using the PDF word scan)")
    return pdf_vocabulary(pdf), "pdf words"


def classify(tokens, vocab):
    """Split tokens into vocabulary tags, unknown tag-like reads and ferrules."""
    tags, unknown, ferrules = {}, {}, {}
    kinds = []
    for t in tokens:
        f = parse_ferrule(t["text"], vocab)
        if f and not f["partial"]:
            ferrules.setdefault(f["norm"], []).append(t)
            kinds.append("ferrule")
            continue
        r = decode(t, vocab)
        if r["tag"]:
            tags.setdefault(r["tag"], []).append((t, r))
            kinds.append("tag")
        elif r["tag_like"]:
            unknown.setdefault(r["tag_like"], []).append((t, r))
            kinds.append("unknown")
        else:
            kinds.append("ferrule" if f else "other")
    return tags, unknown, ferrules, kinds


COLOURS = {"tag": (0, 200, 0), "unknown": (255, 140, 0), "ferrule": (40, 120, 255), "other": (150, 150, 150)}


def debug_image(photo, tokens, kinds, out):
    """Photo with every token boxed and labelled (full resolution JPEG)."""
    im = Image.fromarray(photo["rgb"]).copy()
    d = ImageDraw.Draw(im)
    size = max(14, photo["size"][1] // 160)
    try:
        font = ImageFont.truetype(config.font(), size)
    except OSError:
        font = ImageFont.load_default()
    for b in photo["ignore"]:
        d.rectangle(b, outline=(255, 0, 0), width=6)
    order = sorted(range(len(tokens)), key=lambda i: kinds[i] != "other")      # draw 'other' first
    for i in order:
        t, k = tokens[i], kinds[i]
        c = COLOURS[k]
        d.polygon([tuple(p) for p in t["quad"]], outline=c, width=3 if k != "other" else 1)
        if k != "other":
            label = f"{t['text']} {t['conf']:.2f} x{t['passes']}"
            x, y = t["box"][0], max(0, t["box"][1] - size - 2)
            d.rectangle([x, y, x + d.textlength(label, font=font) + 4, y + size + 2], fill=(0, 0, 0))
            d.text((x + 2, y), label, fill=c, font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    guard = out.parent / ".gitignore"            # the photos are confidential: never let git pick these up
    if not guard.exists():
        guard.write_text("*\n", encoding="utf-8")
    im.save(out, quality=88)


def fmt(items, key=lambda k: k):
    return " ".join(key(k) for k in items) or "-"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--pdf", help="GA drawing PDF (vocabulary)")
    ap.add_argument("--mode", default=ocr.MODE, choices=["FULL", "FAST"])
    ap.add_argument("--workers", type=int, default=ocr.WORKERS)
    ap.add_argument("--no-cache", action="store_true", help="re-run OCR even when a cached result exists")
    ap.add_argument("--no-debug", action="store_true", help="skip the debug JPEGs")
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    if a.no_cache:
        ocr.CACHE = False
    paths = [p for pat in a.photos for p in (sorted(glob.glob(pat)) or [pat])]
    info = ocr.engine_info()
    print(f"engine: {info['engine']} ({info.get('version')}) ok={info['ok']} {info.get('error', '')}")
    vocab_tags, source = vocabulary(a.pdf) if a.pdf else ([], "none")
    vocab = Vocab(vocab_tags)
    print(f"vocabulary: {len(vocab)} tags ({source}); mode {a.mode}, workers {a.workers}, tile {ocr.TILE}, "
          f"upscale {ocr.UPSCALE}, full side {ocr.FULL_SIDE}")
    total = 0.0
    for p in paths:
        t0 = time.perf_counter()
        photo = load_photo(p)
        st = {}
        tokens = ocr.read_photo(photo, mode=a.mode, workers=a.workers, info=st)
        dt = time.perf_counter() - t0
        total += st.get("seconds", dt)
        tags, unknown, ferrules, kinds = classify(tokens, vocab)
        q = photo["quality"]
        print(f"\n{Path(p).name}  {photo['size'][0]}x{photo['size'][1]}  quality {q['score']:.2f} "
              f"(blur {q['blur']:.0f}) {'; '.join(q['issues'])}")
        cached = " (cached)" if st.get("cached") else ""
        print(f"  {st.get('seconds', 0):.1f} s OCR{cached} (full det {st.get('t_full_det', 0)} s, all det "
              f"{st.get('t_det', 0)} s), {len(tokens)} tokens from {st.get('reads', 0)} reads; det jobs "
              f"{st.get('det_jobs')} skipped {st.get('det_skipped')}; rec boxes {st.get('rec_boxes')}")
        print(f"  vocabulary tags ({len(tags)}): "
              + fmt(sorted(tags, key=tag_sort_key),
                    lambda k: f"{k}x{max(t['passes'] for t, _ in tags[k])}"
                              + ("" if all(r['method'] == 'exact' for _, r in tags[k])
                                 else "(" + "/".join(sorted({r['method'] for _, r in tags[k]})) + ")")))
        print(f"  unknown tag-like ({len(unknown)}): "
              + fmt(sorted(unknown, key=tag_sort_key),
                    lambda k: f"{k}x{max(t['passes'] for t, _ in unknown[k])}"
                              + ("" if all(t['norm'] == k for t, _ in unknown[k])
                                 else "[" + "/".join(sorted({t['norm'] for t, _ in unknown[k]})) + "]")))
        print(f"  ferrules ({len(ferrules)}): " + fmt(sorted(ferrules), lambda k: f"{k}x{max(t['passes'] for t in ferrules[k])}"))
        if not a.no_debug:
            out = DEBUG_DIR / f"{Path(p).stem}_{a.mode}.jpg"
            debug_image(photo, tokens, kinds, out)
            print(f"  debug: {out}")
    print(f"\ntotal OCR time {total:.1f} s for {len(paths)} photo(s)")


if __name__ == "__main__":
    main()
