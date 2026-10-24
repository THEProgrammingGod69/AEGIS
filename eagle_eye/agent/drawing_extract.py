"""Claude extraction of device tags from a raster (or unparseable) GA drawing page, with structured outputs.

Used by kb.drawing_kb only when the PDF page has no usable vector text. The page is split into a few overlapping tiles
(tiny 1-3 pt tags need the resolution), each tile is one request whose answer is constrained by
``output_config.format`` (JSON schema), and the tiles are merged back into page-normalised boxes. Returns [] whenever
the agent is disabled, so the drawing parser never depends on it.

Two call shapes: ``extract_drawing_tags(page_image, page_no, vocabulary_hint)`` with a PIL image, or
``extract_drawing_tags(pdf_path, page_no, clip)`` (what kb.drawing_kb calls) where the page (1-based) is rendered here
and ``clip`` is the view outline in PDF points; with a clip every tag also gets ``bbox`` in PDF points.
"""
import hashlib
import json
import math
import numbers
import os
import threading

from PIL import Image

from agent import backends, prompts, tools
from agent import config as acfg
from agent.schema import DRAWING_JSON_SCHEMA, DrawingTag, DrawingTags
from kb.tags import family_of, normalize, tag_sort_key

_LOCK = threading.Lock()


def _tiles(w, h, tile_px, max_tiles):
    """Grid of overlapping page tiles (pixel boxes) whose sides are about tile_px, at most max_tiles of them."""
    nx, ny = max(1, math.ceil(w / tile_px)), max(1, math.ceil(h / tile_px))
    while nx * ny > max_tiles:
        if nx >= ny and nx > 1:
            nx -= 1
        elif ny > 1:
            ny -= 1
        else:
            break
    ov = 0.08
    tw, th = w / (nx - (nx - 1) * ov), h / (ny - (ny - 1) * ov)
    out = []
    for j in range(ny):
        for i in range(nx):
            x0, y0 = i * tw * (1 - ov), j * th * (1 - ov)
            out.append((round(x0), round(y0), min(w, round(x0 + tw)), min(h, round(y0 + th))))
    return out


def _merge(tags):
    """Drop duplicates from overlapping tiles: same tag with nearby centres keeps the most confident box."""
    out = []
    for t in sorted(tags, key=lambda t: -t["confidence"]):
        c = ((t["bbox_norm"][0] + t["bbox_norm"][2]) / 2, (t["bbox_norm"][1] + t["bbox_norm"][3]) / 2)
        dup = False
        for o in out:
            if o["tag"] != t["tag"]:
                continue
            oc = ((o["bbox_norm"][0] + o["bbox_norm"][2]) / 2, (o["bbox_norm"][1] + o["bbox_norm"][3]) / 2)
            if abs(oc[0] - c[0]) < 0.015 and abs(oc[1] - c[1]) < 0.015:
                dup = True
                break
        if not dup:
            out.append(t)
    return sorted(out, key=lambda t: (tag_sort_key(t["tag"]), t["bbox_norm"][1], t["bbox_norm"][0]))


def _is_box(v):
    return (isinstance(v, (list, tuple)) and len(v) == 4 and all(isinstance(x, numbers.Real) for x in v)
            and v[2] > v[0] and v[3] > v[1])


def _render(pdf_path, page_no, clip=None, dpi=None):
    """(PIL image, clip in PDF points) of a 1-based page, rendered so the clip's long side is ~3600 px."""
    import pymupdf
    with pymupdf.open(str(pdf_path)) as doc:
        page = doc[int(page_no) - 1]
        rect = page.rect if clip is None else pymupdf.Rect(*clip) & page.rect
        dpi = dpi or max(100, min(400, round(72 * 3600 / max(rect.width, rect.height, 1))))
        pix = page.get_pixmap(dpi=dpi, clip=rect, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return img, [rect.x0, rect.y0, rect.x1, rect.y1]


def extract_drawing_tags(page_image, page_no, vocabulary_hint=None, backend=None, clip=None, dpi=None):
    """Device tags on a drawing page image (or on page ``page_no`` of the PDF at ``page_image``, inside ``clip``).

    Returns [{"tag", "bbox_norm": [x0, y0, x1, y1] (0..1 of the image), "bbox" (PDF points, when the clip is known),
    "view", "confidence", "source": "vlm", "page", "in_vocabulary"}]; [] when the agent is disabled (no key), on the
    replay / mock backends, or on errors. Only tag-shaped strings (kb.tags families) or members of ``vocabulary_hint``
    are kept: no invented items.
    """
    if clip is None and _is_box(vocabulary_hint):        # kb.drawing_kb passes the view clip third
        clip, vocabulary_hint = list(vocabulary_hint), None
    s = acfg.load()
    if backend is None:
        backend, _ = backends.get_backend(s)
    if backend is None or backend.kind != "llm" or backend.name == "mock":
        return []
    if isinstance(page_image, (str, os.PathLike)):
        page_image, clip = _render(page_image, page_no, clip, dpi)
    img = page_image.convert("RGB")
    hint = sorted({normalize(t) for t in vocabulary_hint or [] if normalize(t)}, key=tag_sort_key)
    meta = repr((img.size, page_no, hint, clip, acfg.PROMPT_VERSION)).encode()
    key = hashlib.sha256(img.tobytes() + meta).hexdigest()
    cache = s.cache_dir / "drawing" / f"{key}.json"
    if s.cache:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    from agent.verifier import resolve_models
    model, _ = resolve_models(backend, s)
    w, h = img.size
    found, failed = [], 0
    for box in _tiles(w, h, int(s.image_max * 0.95), s.drawing_tiles):
        tile_norm = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
        block, _ = tools.encode_image(img.crop(box), s.image_max, quality=92)
        params = dict(model=model, max_tokens=s.max_tokens, system=prompts.DRAWING_SYSTEM,
                      messages=[{"role": "user", "content": [
                          block, {"type": "text", "text": prompts.drawing_message(page_no, tile_norm, hint)}]}],
                      output_config={"effort": s.effort,
                                     "format": {"type": "json_schema", "schema": DRAWING_JSON_SCHEMA}})
        try:
            resp = backend.create(params)
            if getattr(resp, "stop_reason", None) in ("refusal", "max_tokens"):
                failed += 1
                continue
            text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
            raw = json.loads(text)
            page = DrawingTags.model_validate({"page_notes": raw.get("page_notes", ""), "tags": []})
        except Exception:  # noqa: BLE001 - one bad tile only loses that tile
            failed += 1
            continue
        for item in raw.get("tags") or []:
            try:                                           # one malformed entry only loses that entry
                page.tags.append(DrawingTag.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
        tx0, ty0, tx1, ty1 = tile_norm
        for t in page.tags:
            tag = normalize(t.tag)
            in_vocab = tag in hint
            if not tag or not (in_vocab or family_of(tag)):
                continue
            b = t.bbox_norm
            bn = [round(tx0 + b[0] * (tx1 - tx0), 5), round(ty0 + b[1] * (ty1 - ty0), 5),
                  round(tx0 + b[2] * (tx1 - tx0), 5), round(ty0 + b[3] * (ty1 - ty0), 5)]
            rec = {"tag": tag, "view": (t.view or None) and t.view.strip().lower(), "bbox_norm": bn,
                   "confidence": round(float(t.confidence), 3), "source": "vlm", "page": page_no,
                   "in_vocabulary": in_vocab if hint else None}
            if clip:
                cw, ch = clip[2] - clip[0], clip[3] - clip[1]
                rec["bbox"] = [round(clip[0] + bn[0] * cw, 2), round(clip[1] + bn[1] * ch, 2),
                               round(clip[0] + bn[2] * cw, 2), round(clip[1] + bn[3] * ch, 2)]
            found.append(rec)
    out = _merge(found)
    if s.cache and not failed:
        with _LOCK:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                tmp = cache.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(out), encoding="utf-8")
                os.replace(tmp, cache)
            except OSError:
                pass
    return out
