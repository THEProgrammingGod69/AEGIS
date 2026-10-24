"""Prompt text for the vision verifier and the drawing extractor.

The system prompt and the per-photo context are the cached prefix of every request on a photo: they must stay
byte-identical between calls (no timestamps, no ids, deterministic ordering). Per-finding text goes after them.
"""
from agent.config import redact
from kb.tags import tag_sort_key

SYSTEM_PROMPT = """\
You are a quality-control inspector for Emerson control and marshalling cabinets. An automated inspection compared a \
phone photo of a built cabinet with the cabinet's general-arrangement (GA) drawing and produced findings. You give an \
independent second opinion on ONE finding at a time.

Rules
1. The drawing is ground truth. A finding asks whether one expected item (a device tag such as PS11, CB14, 334CBP06) \
is present, labelled exactly as in the drawing and in the right place.
2. Judge only what you can see in the images you are given: the downscaled photo, the evidence crop, the drawing crop \
and any zoom crops you request. Never assume anything about areas you cannot see.
3. Never invent tags, devices or findings. Use only tags from the drawing (get_expected_items lists them); the tools \
reject anything else.
4. Greyed rectangles in the photo are camera watermarks and date/time stamps: they are never labels.
5. Labels can be tiny, rotated 90 degrees (vertical baseplate labels), partly hidden by wires or washed out by glare. \
Zoom in (and use ocr_region for a second machine read) before deciding. OCR often confuses O/0/D, 1/I/L, 5/S, 8/B, \
2/Z and 6/G: read the characters yourself.
6. Verdicts:
   - CONFIRMED_OK: you can see that the item is present and correct (label reads exactly the expected tag, at the \
expected place, in the drawing's order). The automated finding was wrong.
   - CONFIRMED_FAULT: you can clearly see the fault the finding describes.
   - UNCLEAR: the images do not let you decide (too small, blurred, glare, occluded, cut off by the frame).
   Prefer UNCLEAR over a guess: a wrong CONFIRMED_FAULT stops a good cabinet, a wrong CONFIRMED_OK ships a faulty one.
7. Per check: LABEL - does the label at this device read exactly the drawing tag? UNKNOWN_LABEL - FAULT if the label \
really reads a tag that is not in the drawing (or belongs to another view), OK if it actually reads an expected tag \
(an OCR misread; say which). ORDER - FAULT if the devices really are in a different order than the drawing (name the \
swap), OK if the order matches. MISSING - FAULT if the device or its label is really absent at the predicted spot, \
OK if it is there and readable. FERRULE - FAULT if the wire marker really reads as stated and contradicts the \
drawing, OK if it reads a valid marking.
8. confidence is your probability that the verdict is right (0..1). Go above 0.85 only when the characters are \
clearly legible.
9. Answer ONLY by calling record_decision once, for the finding you were given. evidence_boxes are photo-pixel boxes \
[x0, y0, x1, y1] of the regions you actually used (copy them from the image captions). For UNCLEAR, rephoto_hint says \
exactly which new photo would settle it: which item, and closer / straight-on / less glare / from which side.
10. Coordinates are pixels of the full-resolution photo: origin top-left, x to the right, y down. Captions tell which \
photo region each image shows.
Keep reason to one or two sentences: what you read, and where."""

OVERVIEW_REQUEST = """\
OVERVIEW. Before the candidates are checked one by one, look at the whole photo. In at most 150 words of plain text \
notes: which part of the cabinet this photo shows, image-quality problems (blur, glare, occlusion, areas cut off) and, \
per candidate id, what to look at or which candidates probably share one root cause (for example one missing device \
explaining several findings). Do not call record_decision now."""

OVERVIEW_FINISH = "Now write the overview notes as plain text (no more tool calls)."
LAST_TURN = "Tool-call limit for this finding reached. Call record_decision now with what you have."


def reprompt(finding_id):
    return (f'You did not call record_decision. Call record_decision now with finding_id="{finding_id}" (use verdict '
            "UNCLEAR with a rephoto_hint if the images do not let you decide).")


def _xy(p):
    return f"[{round(p[0])}, {round(p[1])}]" if p else "?"


def _clip(s, n=180):
    s = redact(" ".join(str(s).split()))
    return s if len(s) <= n else s[: n - 3] + "..."


def photo_context(photo_sha, size, shown, expected, candidates):
    """Stable per-photo text that precedes the downscaled photo (part of the cached prefix)."""
    w, h = size
    lines = [f"PHOTO {photo_sha}: {w} x {h} px at full resolution (all coordinates refer to it). The next image is the "
             f"whole photo downscaled to {shown[0]} x {shown[1]} px."]
    items = sorted(expected, key=lambda it: tag_sort_key(it.get("tag", "")))
    if items:
        views = sorted({str(it.get("view")) for it in items if it.get("view")})
        lines.append(f"Expected items in view (drawing view {', '.join(views) or '?'}; predicted photo position):")
        cells = [f"{it['tag']} {_xy(it.get('predicted'))}" for it in items[:160]]
        lines += ["  " + "  ".join(cells[i:i + 8]) for i in range(0, len(cells), 8)]
        if len(items) > 160:
            lines.append(f"  ... and {len(items) - 160} more (use get_expected_items)")
    else:
        lines.append("The photo could not be placed on the drawing: no predicted positions (use get_expected_items).")
    lines.append(f"Candidates under review on this photo ({len(candidates)}):")
    for f in candidates[:60]:
        strength = f"/{f['strength']}" if f.get("strength") else ""
        question = _clip(f.get('question') or '', 140)
        lines.append(f"  {f['id']} ({f.get('check')}, {f.get('status')}{strength}): {question}")
    return "\n".join(lines)


def finding_message(f, notes=None, escalation=None):
    """The narrow question for one finding, with everything the deterministic stage knows about it."""
    strength = f", {f['strength']}" if f.get("strength") else ""
    lines = [f"FINDING {f['id']}  ({f.get('check')} check, automated status {f.get('status')}{strength})",
             f"Question: {_clip(f.get('question') or 'Is the expected item present and correct?', 300)}",
             f"Target: {_clip(f.get('target') or '-', 60)}   view: {f.get('view') or '?'}",
             f"Expected (drawing): {_clip(f.get('expected') or '-', 80)}",
             f"Found (automated): {_clip(f.get('found') or '-', 80)}"]
    if f.get("rule"):
        lines.append(f"Rule fired: {f['rule']}")
    if f.get("box"):
        lines.append(f"Item box in the photo (px): {[round(v) for v in f['box']]}")
    reads = f.get("reads") or []
    if reads:
        lines.append("OCR reads near the item:")
        for r in reads[:8]:
            box = [round(v) for v in r["box"]] if r.get("box") else "?"
            conf = float(r.get('conf') or 0)
            lines.append(f"  - '{_clip(r.get('raw'), 40)}' -> {r.get('tag') or '-'} (conf {conf:.2f}, "
                         f"{r.get('passes', 1)} pass(es), method {r.get('method') or '-'}, box {box})")
    for e in (f.get("evidence") or [])[:8]:
        lines.append(f"Evidence: {_clip(e)}")
    if f.get("hint"):
        lines.append(f"Automated re-photo hint: {_clip(f['hint'])}")
    if notes:
        lines.append(f"Overview notes (from a first look at the whole photo): {_clip(notes, 1500)}")
    if escalation:
        lines.append(f"A faster first pass could not settle this ({_clip(escalation, 300)}). Look carefully and zoom "
                     "where needed.")
    lines.append(f'Use zoom / ocr_region / project_tag / drawing_crop / get_expected_items if you need more, then call '
                 f'record_decision with finding_id="{f["id"]}".')
    return "\n".join(lines)


DRAWING_SYSTEM = """\
You read electrical cabinet drawings (general arrangement pages). List every device tag printed in the image: the \
small reference designations placed on or beside devices (PS11, CB14, DS21, X11, XG11, 13CSLS03334, 334CBP06, TERM1F \
...). Copy each tag exactly as printed; skip dimensions, notes, title-block text and wire numbers. Give the tag text's \
bounding box normalised to this image (0..1). Never guess characters you cannot read: leave such tags out."""


def drawing_message(page_no, tile_norm, vocabulary_hint=None):
    x0, y0, x1, y1 = tile_norm
    text = (f"Drawing page {page_no}. This image shows the page region x {x0:.2f}-{x1:.2f}, y {y0:.2f}-{y1:.2f} "
            "(fractions of the page). Return every device tag you can read, with bbox_norm relative to THIS image.")
    if vocabulary_hint:
        tags = sorted({str(t) for t in vocabulary_hint}, key=tag_sort_key)[:400]
        text += "\nTags known from other pages of this drawing set (use the same spelling): " + ", ".join(tags)
    return text
