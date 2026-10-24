"""Agent tools: strict JSON-schema definitions and the deterministic Python that executes them.

The tools run against an *AgentContext* the pipeline provides (``SimpleContext`` below is a ready-made one):

    ctx.photo                         vision.preprocess.load_photo() dict: rgb (HxWx3 uint8), sha, size [w, h], ignore
    ctx.kb                            cabinet model (kb.drawing_kb.build_kb) or None
    ctx.pdf_path                      GA drawing path or None
    ctx.findings                      {finding_id: finding}
    ctx.expected_items(view, region_xyxy|None) -> [{"tag", "family", "view", "predicted": [x, y]|None, ...}]
    ctx.project_tag(tag) -> [x, y] | None
    ctx.ocr_region(box, rotations, scale) -> [Token]
    ctx.drawing_crop(tag) -> PIL.Image | None

``record_decision`` is the only output channel of the agent: its input is validated with ``schema.Decision`` and checked
against the findings of this photo, so the agent can never return a verdict for an item that does not exist.
"""
import base64
import hashlib
import io
import json
import math
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

import numpy as np
from PIL import Image
from pydantic import ValidationError

from agent.schema import VERDICTS, Decision, errors_text
from kb.tags import coerce_to_family, family_of, normalize, tag_sort_key

GREY = (128, 128, 128)
MIN_ZOOM_SIDE = 384           # zoom crops are upscaled to at least this long side
MAX_ZOOMS = 10                # zoom images per finding conversation


def _nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


_BOX = {"type": "array", "items": {"type": "number"},
        "description": "[x0, y0, x1, y1]: exactly 4 numbers, full-resolution photo pixels"}

TOOLS = [
    {
        "name": "get_expected_items",
        "description": "List the items the GA drawing expects in this photo (tag, family, view and predicted photo "
                       "position). Optionally filter by drawing view and/or a photo region.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "view": _nullable({"type": "string", "description": "drawing view (front, rear, left, right)"}),
                "region_xyxy": _nullable(_BOX),
            },
            "required": ["view", "region_xyxy"],
            "additionalProperties": False,
        },
    },
    {
        "name": "zoom",
        "description": "Return a JPEG crop of the ORIGINAL full-resolution photo. Use it to read small labels. scale "
                       "is the magnification (1-6); the output is capped at 1568 px per side.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"region_xyxy": _BOX, "scale": {"type": "number", "description": "magnification, 1-6"}},
            "required": ["region_xyxy", "scale"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ocr_region",
        "description": "Run the engine's OCR on a photo region at the given rotations (90/270 read vertical labels). "
                       "Returns the text tokens with confidence and photo boxes.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "region_xyxy": _BOX,
                "rotations": {"type": "array", "items": {"type": "integer", "enum": [0, 90, 270]},
                              "description": "rotations to read, e.g. [0, 90, 270]"},
            },
            "required": ["region_xyxy", "rotations"],
            "additionalProperties": False,
        },
    },
    {
        "name": "project_tag",
        "description": "Predicted photo position [x, y] of a drawing tag (null when the photo was not placed on the "
                       "drawing or the tag is outside it). Only drawing tags are accepted.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
            "additionalProperties": False,
        },
    },
    {
        "name": "drawing_crop",
        "description": "Image of the GA drawing around a tag (ground truth: device shape, label position, "
                       "neighbours). Only drawing tags are accepted.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"tag": {"type": "string"}},
            "required": ["tag"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_decision",
        "description": "Record your verdict on the finding you are verifying. This is the ONLY way to answer. Call it "
                       "exactly once. CONFIRMED_OK / CONFIRMED_FAULT need at least one evidence box; UNCLEAR needs a "
                       "rephoto_hint.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "finding_id": {"type": "string", "description": "id of the finding you were given"},
                "verdict": {"type": "string", "enum": list(VERDICTS)},
                "confidence": {"type": "number", "description": "probability the verdict is right, 0..1"},
                "reason": {"type": "string", "description": "one or two sentences: what you read and where"},
                "evidence_boxes": {"type": "array", "items": _BOX,
                                   "description": "photo-pixel boxes of the crops/regions you used"},
                "rephoto_hint": _nullable({"type": "string",
                                           "description": "for UNCLEAR: which new photo would settle it"}),
            },
            "required": ["finding_id", "verdict", "confidence", "reason", "evidence_boxes", "rephoto_hint"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = tuple(t["name"] for t in TOOLS)


@runtime_checkable
class AgentContext(Protocol):
    photo: dict
    kb: object
    pdf_path: object
    findings: dict

    def expected_items(self, view, region_xyxy): ...

    def project_tag(self, tag): ...

    def ocr_region(self, box, rotations, scale): ...

    def drawing_crop(self, tag): ...


class ToolError(Exception):
    """A tool call the agent can fix (bad region, unknown tag ...): returned as an is_error tool_result."""


@dataclass
class ToolOutcome:
    content: object                    # str or list of content blocks
    is_error: bool = False
    decision: Optional[Decision] = None
    error: Optional[str] = None


# ------------------------------------------------------------------ images
def photo_size(photo):
    if photo.get("size"):
        return int(photo["size"][0]), int(photo["size"][1])
    h, w = photo["rgb"].shape[:2]
    return w, h


def _rgb(arr):
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    elif arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return np.ascontiguousarray(arr, dtype=np.uint8)


def region_pixels(photo, box):
    """Pixels of a clamped photo region with the ignore bands (watermark, time stamp) greyed out (a copy)."""
    x0, y0, x1, y1 = box
    region = _rgb(photo["rgb"][y0:y1, x0:x1]).copy()
    for b in photo.get("ignore") or []:
        ix0, iy0 = max(x0, int(b[0])), max(y0, int(b[1]))
        ix1, iy1 = min(x1, int(math.ceil(b[2]))), min(y1, int(math.ceil(b[3])))
        if ix1 > ix0 and iy1 > iy0:
            region[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = GREY
    return region


def to_pil(arr, out_size=None):
    img = Image.fromarray(_rgb(arr))
    if out_size and tuple(out_size) != img.size:
        img = img.resize(tuple(out_size), Image.Resampling.LANCZOS, reducing_gap=2.0)
    return img


def fit_size(w, h, max_side, factor=1.0):
    f = factor * w, factor * h
    k = min(1.0, max_side / max(f))
    return max(1, round(f[0] * k)), max(1, round(f[1] * k))


def encode_image(img, max_side=1568, quality=88, cache=False):
    """PIL image -> (base64 JPEG image block, meta {sha, size, bytes}); downscaled to max_side."""
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img = img.resize(fit_size(*img.size, max_side), Image.Resampling.LANCZOS, reducing_gap=2.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    data = buf.getvalue()
    block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(data).decode("ascii")}}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block, {"sha": hashlib.sha256(data).hexdigest()[:16], "size": list(img.size), "bytes": len(data)}


def overview_image(photo, max_side=1568):
    """Whole photo, ignore bands greyed, downscaled for the overview / cached prefix."""
    w, h = photo_size(photo)
    return to_pil(region_pixels(photo, (0, 0, w, h)), fit_size(w, h, max_side))


def evidence_region(photo, box, min_side=256):
    """Region around a finding box used for the first evidence crop (and the decision cache key)."""
    w, h = photo_size(photo)
    if not box:
        return 0, 0, w, h
    x0, y0, x1, y1 = [float(v) for v in box]
    pad = max(48.0, 0.6 * max(x1 - x0, y1 - y0))
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = max((x1 - x0) / 2, min_side / 2), max((y1 - y0) / 2, min_side / 2)
    return clamp_box([cx - hw, cy - hh, cx + hw, cy + hh], (w, h))


def clamp_box(box, size, min_px=4):
    """Validate and clamp a photo box; ToolError when it is malformed or (almost) empty inside the photo."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ToolError("region must be [x0, y0, x1, y1] (4 numbers, photo pixels)")
    try:
        v = [float(x) for x in box]
    except (TypeError, ValueError):
        raise ToolError("region must contain numbers") from None
    if not all(math.isfinite(x) for x in v):
        raise ToolError("region must contain finite numbers")
    w, h = size
    x0, x1 = sorted((v[0], v[2]))
    y0, y1 = sorted((v[1], v[3]))
    x0, y0 = max(0, int(math.floor(x0))), max(0, int(math.floor(y0)))
    x1, y1 = min(w, int(math.ceil(x1))), min(h, int(math.ceil(y1)))
    if x1 - x0 < min_px or y1 - y0 < min_px:
        raise ToolError(f"region {list(box)} is empty or outside the photo (photo is {w} x {h} px)")
    return x0, y0, x1, y1


def pixels_sha(arr, box):
    return hashlib.sha256(np.ascontiguousarray(arr).tobytes() + repr(tuple(box)).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ context helpers
def findings_map(ctx, extra=()):
    """{finding_id: finding} of ctx.findings (dict or list) plus ``extra`` findings."""
    f = getattr(ctx, "findings", None) or {}
    out = dict(f) if isinstance(f, dict) else {x["id"]: x for x in f}
    out.update({x["id"]: x for x in extra if x["id"] not in out})
    return out


def _kb_view_tags(kb, view):
    rec = ((kb or {}).get("views") or {}).get(view) or {}
    tags = rec.get("tags") or []
    if isinstance(tags, dict):
        return tags
    return {t["tag"]: t for t in tags if isinstance(t, dict) and t.get("tag")}


def allowed_tags(ctx, findings=None):
    """Every tag the agent may name: drawing vocabulary, view tags, expected items and the findings' own targets."""
    kb = getattr(ctx, "kb", None) or {}
    out = {normalize(t) for t in kb.get("vocabulary") or []}
    for view in (kb.get("views") or {}):
        out |= {normalize(t) for t in _kb_view_tags(kb, view)}
    try:
        out |= {normalize(it["tag"]) for it in ctx.expected_items(None, None) or [] if it.get("tag")}
    except Exception:  # noqa: BLE001 - a context without positions still has the vocabulary
        pass
    for f in (findings or {}).values():
        if f.get("check") == "UNKNOWN_LABEL":           # its text is by definition not a drawing tag
            continue
        for k in ("target", "expected"):
            v = f.get(k)
            if isinstance(v, str) and family_of(v):
                out.add(normalize(v))
    out.discard("")
    return out


def result_block(tool_use_id, outcome):
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": outcome.content}
    if outcome.is_error:
        block["is_error"] = True
    return block


def _r(v, nd=1):
    return round(float(v), nd)


# ------------------------------------------------------------------ runner
class ToolRunner:
    """Executes the agent's tool calls for one conversation (one finding, or the per-photo overview)."""

    def __init__(self, ctx, finding_id=None, findings=None, image_max=1568, allow_decision=True):
        self.ctx = ctx
        self.finding_id = finding_id
        self.findings = findings if findings is not None else findings_map(ctx)
        self.image_max = image_max
        self.allow_decision = allow_decision
        self.size = photo_size(ctx.photo)
        self.crops = []                  # meta of every image shown in this conversation (report evidence)
        self._vocab = None
        self._zooms = 0

    @property
    def vocab(self):
        if self._vocab is None:
            self._vocab = allowed_tags(self.ctx, self.findings)
        return self._vocab

    def run(self, name, args):
        """Execute one tool call; never raises (errors become is_error results the model can react to)."""
        if name not in TOOL_NAMES:
            return ToolOutcome(f"unknown tool '{name}'; available: {', '.join(TOOL_NAMES)}", is_error=True)
        if not isinstance(args, dict):
            return ToolOutcome("tool input must be a JSON object", is_error=True)
        try:
            return getattr(self, "_t_" + name)(args)
        except ToolError as e:
            return ToolOutcome(str(e), is_error=True, error=str(e))
        except Exception as e:  # noqa: BLE001 - a failing tool must not end the conversation
            return ToolOutcome(f"tool {name} failed: {type(e).__name__}: {e}"[:500], is_error=True,
                               error=type(e).__name__)

    def _tag(self, args):
        tag = normalize(args.get("tag") or "")
        if not tag or tag not in self.vocab:
            raise ToolError(f"'{args.get('tag')}' is not a tag of this drawing; never invent tags "
                            "(get_expected_items lists them)")
        return tag

    def _t_get_expected_items(self, args):
        view, region = args.get("view"), args.get("region_xyxy")
        views = list(((self.ctx.kb or {}).get("views") or {}).keys())
        if view is not None and views and view not in views:
            raise ToolError(f"unknown view '{view}'; views of this drawing: {', '.join(views)}")
        box = clamp_box(region, self.size) if region is not None else None
        items = self.ctx.expected_items(view, list(box) if box else None) or []
        items = sorted(items, key=lambda it: tag_sort_key(it.get("tag", "")))
        out = [{"tag": it.get("tag"), "family": it.get("family") or family_of(it.get("tag", "")),
                "view": it.get("view"),
                "predicted": [_r(p) for p in it["predicted"]] if it.get("predicted") else None}
               for it in items[:120]]
        return ToolOutcome(json.dumps({"count": len(items), "items": out, "truncated": len(items) > 120}))

    def _t_zoom(self, args):
        if self._zooms >= MAX_ZOOMS:
            raise ToolError(f"zoom limit ({MAX_ZOOMS}) reached for this finding: decide with what you have")
        box = clamp_box(args.get("region_xyxy"), self.size, min_px=8)
        try:
            scale = float(args.get("scale") or 1.0)
        except (TypeError, ValueError):
            scale = 1.0
        scale = min(6.0, max(1.0, scale if math.isfinite(scale) else 1.0))
        rw, rh = box[2] - box[0], box[3] - box[1]
        if max(rw, rh) * scale < MIN_ZOOM_SIDE:
            scale = min(8.0, MIN_ZOOM_SIDE / max(rw, rh))
        out = fit_size(rw, rh, self.image_max, scale)
        block, meta = encode_image(to_pil(region_pixels(self.ctx.photo, box), out), self.image_max)
        self._zooms += 1
        self.crops.append({"kind": "zoom", "box": list(box), **meta})
        ow, oh = meta["size"]
        caption = (f"zoom of photo region {list(box)} ({rw} x {rh} px) shown at {ow} x {oh} px "
                   f"(x{ow / rw:.2f}); image sha {meta['sha']}")
        return ToolOutcome([{"type": "text", "text": caption}, block])

    def _t_ocr_region(self, args):
        box = clamp_box(args.get("region_xyxy"), self.size, min_px=8)
        rots = tuple(sorted({int(r) for r in (args.get("rotations") or []) if int(r) in (0, 90, 270)})) or (0, 90, 270)
        tokens = self.ctx.ocr_region(list(box), rots, 3.0) or []
        out = []
        for t in sorted(tokens, key=lambda t: (t.get("box") or [0, 0])[1::-1])[:40]:
            norm = t.get("norm") or normalize(t.get("text", ""))
            rec = {"text": str(t.get("text", ""))[:64], "norm": norm[:64], "conf": _r(t.get("conf") or 0, 2),
                   "box": [round(v) for v in t["box"]] if t.get("box") else None, "rot": t.get("rot", 0)}
            fam = family_of(norm)
            if fam:
                rec["family"] = fam
            else:
                fixed = coerce_to_family(norm)
                if fixed:
                    rec["repaired"] = fixed[0][1]
            out.append(rec)
        return ToolOutcome(json.dumps({"region": list(box), "rotations": list(rots), "tokens": out,
                                       "truncated": len(tokens) > 40}))

    def _t_project_tag(self, args):
        tag = self._tag(args)
        p = self.ctx.project_tag(tag)
        w, h = self.size
        inside = bool(p) and 0 <= p[0] < w and 0 <= p[1] < h
        return ToolOutcome(json.dumps({"tag": tag, "predicted": [_r(p[0]), _r(p[1])] if p else None,
                                       "in_photo": inside}))

    def _t_drawing_crop(self, args):
        tag = self._tag(args)
        img = self.ctx.drawing_crop(tag)
        if img is None:
            return ToolOutcome(f"no drawing crop available for {tag}")
        block, meta = encode_image(img, self.image_max)
        self.crops.append({"kind": "drawing", "tag": tag, **meta})
        return ToolOutcome([{"type": "text", "text": f"GA drawing around {tag} (ground truth, not the photo); "
                                                     f"image sha {meta['sha']}"}, block])

    def _t_record_decision(self, args):
        if not self.allow_decision:
            raise ToolError("record_decision is not available in the overview: reply with plain text notes")
        fid = args.get("finding_id")
        if fid not in self.findings:
            raise ToolError(f"finding_id '{fid}' is not a finding of this inspection; never invent ids")
        if self.finding_id and fid != self.finding_id:
            raise ToolError(f"you are verifying {self.finding_id}: record the decision for that id only")
        try:
            d = Decision.model_validate(args)
        except ValidationError as e:
            raise ToolError(f"invalid record_decision: {errors_text(e)}") from None
        w, h = self.size
        boxes = []
        for b in d.evidence_boxes:
            c = [max(0.0, min(w, b[0])), max(0.0, min(h, b[1])), max(0.0, min(w, b[2])), max(0.0, min(h, b[3]))]
            if c[2] - c[0] >= 1 and c[3] - c[1] >= 1:
                boxes.append(c)
        if d.evidence_boxes and not boxes:
            raise ToolError(f"invalid record_decision: every evidence box is outside the photo ({w} x {h} px)")
        if d.verdict != "UNCLEAR" and not boxes:
            raise ToolError("invalid record_decision: CONFIRMED_OK / CONFIRMED_FAULT need at least one evidence box "
                            "(copy it from an image caption)")
        if d.verdict == "UNCLEAR" and not d.rephoto_hint:
            raise ToolError("invalid record_decision: UNCLEAR needs a rephoto_hint (which photo would settle it)")
        d = d.model_copy(update={"evidence_boxes": boxes})
        return ToolOutcome("decision recorded", decision=d)


# ------------------------------------------------------------------ a ready-made context
class SimpleContext:
    """AgentContext built from the pipeline's objects.

    photo: load_photo() dict; kb: cabinet model; reg: vision.register Registration (``in_view``, ``fits``);
    findings: list or dict; ocr_region(box, rotations, scale) and drawing_crop(tag) override the defaults
    (vision.ocr.read_region and kb.drawing_kb.drawing_crop, imported lazily).
    """

    def __init__(self, photo, kb=None, pdf_path=None, findings=(), reg=None, ocr_region=None, drawing_crop=None,
                 crop_dpi=300, crop_margin_pt=36):
        self.photo = photo
        self.kb = kb or {}
        self.pdf_path = pdf_path
        self.findings = dict(findings) if isinstance(findings, dict) else {f["id"]: f for f in findings}
        self.reg = reg or {}
        self._ocr = ocr_region
        self._crop = drawing_crop
        self._dpi, self._margin = crop_dpi, crop_margin_pt

    def _view_of(self, tag):
        rec = (self.reg.get("in_view") or {}).get(tag)
        if rec and rec.get("view"):
            return rec["view"]
        return next((v for v in (self.kb.get("views") or {}) if tag in _kb_view_tags(self.kb, v)), None)

    def expected_items(self, view=None, region_xyxy=None):
        """Drawing tags inside the registered coverage (with predicted positions), else the view's tags."""
        items = []
        in_view = self.reg.get("in_view") or {}
        for tag, rec in in_view.items():
            if view and rec.get("view") != view:
                continue
            p = rec.get("predicted")
            if region_xyxy and (not p or not (region_xyxy[0] <= p[0] <= region_xyxy[2]
                                              and region_xyxy[1] <= p[1] <= region_xyxy[3])):
                continue
            items.append({"tag": tag, "family": family_of(tag), "view": rec.get("view"), "predicted": p})
        if not in_view and view and not region_xyxy:
            items = [{"tag": t, "family": family_of(t), "view": view, "predicted": None}
                     for t in _kb_view_tags(self.kb, view)]
        return sorted(items, key=lambda it: tag_sort_key(it["tag"]))

    def project_tag(self, tag):
        rec = (self.reg.get("in_view") or {}).get(tag)
        if rec and rec.get("predicted"):
            return list(rec["predicted"])
        w, h = photo_size(self.photo)
        for fit in self.reg.get("fits") or []:
            t = _kb_view_tags(self.kb, fit.get("view")).get(tag)
            if not t or not t.get("center") or fit.get("H") is None:
                continue
            x, y, s = np.asarray(fit["H"], float) @ np.array([t["center"][0], t["center"][1], 1.0])
            if abs(s) > 1e-9 and 0 <= x / s < w and 0 <= y / s < h:
                return [float(x / s), float(y / s)]
        return None

    def ocr_region(self, box, rotations=(0, 90, 270), scale=3.0):
        if self._ocr is not None:
            return self._ocr(box, rotations, scale)
        from vision import ocr
        return ocr.read_region(self.photo, box, rotations=rotations, scale=scale)

    def drawing_crop(self, tag):
        if self._crop is not None:
            return self._crop(tag)
        if not (self.kb and self.pdf_path):
            return None
        try:
            from kb import drawing_kb
            return drawing_kb.drawing_crop(self.kb, self.pdf_path, self._view_of(tag), tag, self._margin, self._dpi)
        except Exception:  # noqa: BLE001 - a missing drawing crop only weakens the evidence
            return None
