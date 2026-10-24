"""Built-in checks of the real-cabinet engine: MISSING, ORDER, LABEL, UNKNOWN_LABEL, FERRULE, COLOUR (spec section 6).

Rules shared by every check: only items inside a fit's coverage are judged; a label too small in the photo to be read
(expected letter height < MIN_TEXT_PX) or at the very edge of the covered area is NOT_IN_VIEW, never a fault; a missing
part suppresses its label and ferrule items (SKIP + root_cause); a partial read at the predicted spot that only one
vocabulary tag explains counts as support.
"""
import re

from checks import box_around, check, dist, finding, union
from kb.tags import family_of, normalize, tag_sort_key
from vision.decode import Vocab, classify_tokens, partial_candidates
from vision.register import MIN_TEXT_PX, layout_consistent, unproject, view_of_point

NEAR = 1.5          # x fit tolerance: read "at" its predicted spot
FAR = 3.0           # x fit tolerance: beyond this a read is somewhere else on the cabinet
STRONG_TEXT_PX = 14.0


def _vocab(ctx):
    v = ctx.facts.get("_vocab")
    if v is None:
        v = ctx.facts["_vocab"] = Vocab(ctx.kb.get("vocabulary") or ())
    return v


def _rd(r):
    """Compact read record for a finding."""
    return {"raw": r.get("raw"), "tag": r.get("tag") or r.get("tag_like"), "conf": round(float(r.get("conf", 0)), 3),
            "passes": r.get("passes", 1), "box": [round(v, 1) for v in r["box"]], "method": r.get("method")}


def _read_text(r):
    return f"read '{r.get('raw')}' x{r.get('passes', 1)} pass{'es' if r.get('passes', 1) != 1 else ''} " \
           f"(conf {float(r.get('conf', 0)):.2f})"


def _drawing_ref(ctx, tag):
    iv = ctx.in_view.get(tag)
    rec = ctx.tag_rec(tag)
    if not (iv and rec):
        return None
    boxes = [i["bbox"] for i in rec.get("instances") or []]
    b = union(boxes) or rec.get("device_bbox")
    return {"page": ctx.kb["views"][iv["view"]]["page"], "view": iv["view"], "bbox": b}


def _tol(ctx, view):
    f = ctx.fit(view)
    return float(f["tol_px"]) if f else 40.0


def _skeleton(s):
    """Letters kept, digits as 9: 'CB18' -> 'CB99', '334CBP06' -> '999CBP99', 'XC60' -> 'XC99'."""
    return re.sub(r"\d", "9", normalize(s))


def _verbatim(raw, device):
    """The device name appears literally in the raw OCR text (no confusion repair, no dropped characters)."""
    return device in re.sub(r"\s+", "", str(raw or "").upper())


def _strong_read(r):
    return r.get("passes", 1) >= 2 and float(r.get("conf", 0)) >= 0.9


def _verified_read(r):
    """Literal complete text with usable OCR support; vocabulary repairs are suggestions, never verification."""
    exact = r.get("method") == "exact" and normalize(r.get("raw", "")) == r.get("tag")
    conf = float(r.get("conf", 0))
    return exact and (conf >= 0.85 or (r.get("passes", 1) >= 2 and conf >= 0.75))


def _best_read(reads):
    return max(reads, key=lambda r: (_verified_read(r), r.get("passes", 1), r.get("conf", 0)))


# ------------------------------------------------------------------ MISSING
@check("MISSING")
class MissingCheck:
    """Every labelled device the drawing places inside the photo's covered area is there: its label is read at the
    predicted spot, or after a targeted zoom re-read. Nothing readable even zoomed in -> candidate missing part/label."""
    title = "Part present"
    question = "Is the device the drawing places here installed, with its label?"

    def run(self, ctx):
        vocab = _vocab(ctx)
        presence = ctx.facts.setdefault("presence", {})
        zoom_reads = ctx.facts.setdefault("zoom_reads", {})
        wrong = ctx.facts.setdefault("wrong_reads", {})
        out, todo = [], []
        for tag in sorted(ctx.in_view, key=tag_sort_key):
            iv = ctx.in_view[tag]
            if not ctx.label_expected(tag):
                continue
            tol = _tol(ctx, iv["view"])
            box = ctx.label_box(tag)
            fid = f"MISS-{tag}"
            reads = [r for r in ctx.reads_of(tag) if r.get("dist_px") is not None]
            near = [r for r in reads if r["dist_px"] <= NEAR * tol]
            common = dict(view=iv["view"], drawing=_drawing_ref(ctx, tag))
            if near:
                best = _best_read(near)
                certain = _verified_read(best)
                presence[tag] = "read" if certain else "partial"
                out.append(finding(fid, "MISSING", tag, "Installed", "Present" if certain else "Label read is uncertain",
                                   "OK" if certain else "UNCERTAIN", box, conf=best["conf"],
                                   rule="MISSING.read_at_predicted" if certain else "MISSING.uncertain_read",
                                   evidence=[_read_text(best) + " at its drawn spot"],
                                   hint=None if certain else f"Capture the full {tag} label sharply without obstructions",
                                   reads=[_rd(r) for r in near], **common))
                continue
            if reads and (iv.get("off_fit") or not iv.get("anchored", True)):
                best = _best_read(reads)
                presence[tag] = "far"
                out.append(finding(fid, "MISSING", tag, "Installed", "Present" if _verified_read(best) else "Label read is uncertain",
                                   "OK" if _verified_read(best) else "UNCERTAIN", box, conf=best["conf"],
                                   rule="MISSING.read_off_fit", reads=[_rd(r) for r in reads],
                                   evidence=[_read_text(best) + "; the label check judges its position"], **common))
                continue
            if reads:
                presence[tag] = "far"
                d = min(r["dist_px"] for r in reads)
                out.append(finding(fid, "MISSING", tag, "Installed", f"Label read {d:.0f} px away", "SKIP", box,
                                   rule="MISSING.read_elsewhere", root_cause=f"LBL-{tag}",
                                   evidence=[f"{tag} was read elsewhere on the photo; the label check judges where"],
                                   reads=[_rd(r) for r in reads], **common))
                continue
            wr = self._wrong_in(ctx, tag, box, ctx.unknown + [r for r in ctx.reads if r["tag"] != tag])
            if wr:
                presence[tag], wrong[tag] = "wrong", wr
                out.append(finding(fid, "MISSING", tag, "Installed", "Present (label differs)", "OK", box,
                                   conf=wr["conf"], rule="MISSING.other_label", evidence=[
                                       f"a label is there: {_read_text(wr)}; the label check compares the text"],
                                   reads=[_rd(wr)], **common))
                continue
            th = ctx.text_px(tag)
            if th < MIN_TEXT_PX:
                presence[tag] = "unjudged"
                out.append(finding(fid, "MISSING", tag, "Installed", "Too small to read in this photo", "NOT_IN_VIEW",
                                   box, rule="MISSING.too_small", evidence=[
                                       f"its letters would be ~{th:.0f} px high here; at least {MIN_TEXT_PX:.0f} px are "
                                       f"needed to judge a label"],
                                   hint=f"Re-photo the {tag} area closer (30-60 cm) to verify it", **common))
                continue
            if iv["margin_px"] < max(tol, 2.5 * th) or any(ctx.in_ignore(p) for p in iv["instances"]):
                presence[tag] = "unjudged"
                out.append(finding(fid, "MISSING", tag, "Installed", "At the edge of the covered area", "NOT_IN_VIEW",
                                   box, rule="MISSING.edge", evidence=["too close to the edge of what this photo shows"],
                                   **common))
                continue
            if not iv.get("anchored", True):
                # absence is judged only between labels actually read: beyond them the drawing is extrapolated, and
                # where the drawing is not to scale (or the photo is at a steep angle) the predicted spot is unreliable
                presence[tag] = "unjudged"
                out.append(finding(fid, "MISSING", tag, "Installed", "Outside the area anchored by read labels",
                                   "NOT_IN_VIEW", box, rule="MISSING.not_anchored",
                                   evidence=["the drawing places it beyond the labels this photo could read, so its "
                                             "position here is extrapolated, not measured"],
                                   hint=f"Photograph the {tag} area so that labels around it are readable", **common))
                continue
            todo.append(tag)

        out += self._other_view_reads(ctx, presence)
        for tag, (status, rec, z) in zip(todo, ctx.pmap(lambda t: self._zoom(ctx, vocab, t), todo)):
            iv = ctx.in_view[tag]
            box = ctx.label_box(tag)
            fid = f"MISS-{tag}"
            common = dict(view=iv["view"], drawing=_drawing_ref(ctx, tag))
            if status in ("zoom", "partial"):
                presence[tag] = status
                zoom_reads.setdefault(tag, []).append(rec)
                txt = "zoom re-read" if status == "zoom" else "partial zoom read only this tag explains"
                certain = status == "zoom" and _verified_read(rec)
                out.append(finding(fid, "MISSING", tag, "Installed", "Present" if certain else "Partial label reading",
                                   "OK" if certain else "UNCERTAIN", box, conf=rec["conf"],
                                   rule=f"MISSING.{status}", evidence=[f"{txt}: {_read_text(rec)}"], reads=[_rd(rec)],
                                   hint=None if certain else f"Capture the complete {tag} label so every character is readable",
                                   **common))
            elif status == "wrong":
                presence[tag], wrong[tag] = "wrong", rec
                out.append(finding(fid, "MISSING", tag, "Installed", "Present (label differs)", "OK", box,
                                   conf=rec["conf"], rule="MISSING.other_label",
                                   evidence=[f"zoom re-read found a label: {_read_text(rec)}"], reads=[_rd(rec)],
                                   **common))
            else:
                presence[tag] = "absent"
                th = ctx.text_px(tag)
                tol = _tol(ctx, iv["view"])
                q = float((ctx.photo.get("quality") or {}).get("score", 1.0))
                strong = th >= STRONG_TEXT_PX and iv["margin_px"] >= 2 * tol and q >= 0.6
                ev = [f"the drawing places {tag} here (inside the covered area, {iv['margin_px']:.0f} px from its edge)",
                      f"no read of {tag} anywhere in the photo; zoomed re-read x{z['scale']:.1f} at 0/90/270 deg "
                      f"found {z['tokens']} text token(s), none of them {tag}"]
                out.append(finding(fid, "MISSING", tag, "Installed", "Not found", "CANDIDATE_FAULT", box,
                                   strength="strong" if strong else "weak", conf=0.75 if strong else 0.55,
                                   rule="MISSING.absent_after_zoom", evidence=ev, root_cause=None,
                                   question=f"The drawing places device {tag} with a label reading '{tag}' at the "
                                            f"marked spot. Is that device and its label there?",
                                   hint=f"Re-photo the {tag} area from 30-40 cm, straight on, so its label is sharp",
                                   **common))
        return out

    @staticmethod
    def _other_view_reads(ctx, presence):
        """Per-label items for certain reads of tags whose view is not placed on this photo (or when the photo is not
        placed at all): the label is there and reads right; where it sits is not judged."""
        out, seen = [], set()
        for r in ctx.reads:
            t = r["tag"]
            if t in ctx.in_view or t in seen or not r.get("anchor") or not (r["passes"] >= 2 or r["conf"] >= 0.95):
                continue
            rec = next((v[t] for v in ctx.views.values() if t in v), None)
            if rec is None or not rec.get("label_expected", True):
                continue
            seen.add(t)
            rs = [x for x in ctx.reads_of(t) if x.get("anchor")]
            view = r.get("view")
            presence[t] = "read_unplaced"
            ctx.facts.setdefault("unplaced", {})[t] = rs
            out.append(finding(f"MISS-{t}", "MISSING", t, "Installed", "Label read; position unverified", "UNCERTAIN", union([x["box"] for x in rs]),
                               view=view, conf=r["conf"], rule="MISSING.read_view_not_placed", reads=[_rd(x) for x in rs],
                               evidence=[_read_text(r), f"its {view} view is not placed on this photo: position not judged"],
                               hint=f"Include surrounding labels to locate the {view} view against the matching drawing"))
        # Emit explicit coverage gaps. Omitting unseen expected tags made a partial photo look like a complete check.
        for view, tags in ctx.views.items():
            for t, rec in sorted(tags.items(), key=lambda kv: tag_sort_key(kv[0])):
                if t in ctx.in_view or t in seen or not rec.get("label_expected", True):
                    continue
                seen.add(t)
                presence[t] = "unjudged"
                out.append(finding(f"MISS-{t}", "MISSING", t, "Installed", "Outside the verified photo coverage",
                                   "NOT_IN_VIEW", view=view, rule="MISSING.not_in_view",
                                   evidence=["this drawing region has no reliable photo coverage"],
                                   hint=f"Capture the {t} area with surrounding readable labels"))
        return out

    @staticmethod
    def _wrong_in(ctx, tag, box, cands):
        """A same-family label read inside this tag's label box whose own drawn spot is elsewhere (wrong label)."""
        fam = family_of(tag)
        best = None
        for r in cands:
            t = r.get("tag") or r.get("tag_like")
            if not t or family_of(t) != fam or not (box[0] <= r["center"][0] <= box[2] and box[1] <= r["center"][1] <= box[3]):
                continue
            if r.get("tag"):                                         # another drawing tag: only if it belongs elsewhere
                other = ctx.in_view.get(r["tag"])
                if other is None or min(dist(r["center"], p) for p in other["instances"]) <= FAR * _tol(ctx, other["view"]):
                    continue
            if best is None or (r["passes"], r["conf"]) > (best["passes"], best["conf"]):
                best = r
        return best

    @staticmethod
    def _zoom(ctx, vocab, tag):
        """(status, read, info) of a zoomed re-read around the tag's label: zoom | partial | wrong | absent."""
        box = ctx.label_box(tag)
        th = max(ctx.text_px(tag), 4.0)
        pad = 2.0 * th
        region = [max(0.0, box[0] - pad), max(0.0, box[1] - pad), min(float(ctx.photo["size"][0]), box[2] + pad),
                  min(float(ctx.photo["size"][1]), box[3] + pad)]
        scale = max(1.5, min(4.0, 40.0 / th))
        toks = ctx.ocr_region(region, (0, 90, 270), scale)
        info = {"scale": scale, "tokens": len(toks), "region": region}
        cls = classify_tokens(toks, vocab)
        hit = [r for r in cls["reads"] if r["tag"] == tag]
        if hit:
            best = _best_read(hit)
            return "zoom" if _verified_read(best) else "partial", best, info
        wr = MissingCheck._wrong_in(ctx, tag, box, cls["unknown"] + [r for r in cls["reads"] if r["tag"] != tag])
        if wr:
            return "wrong", wr, info
        for t in toks:                                   # partial read only this tag explains
            c = [(t["box"][0] + t["box"][2]) / 2, (t["box"][1] + t["box"][3]) / 2]
            if not (box[0] <= c[0] <= box[2] and box[1] <= c[1] <= box[3]) or len(t.get("norm", "")) < 3:
                continue
            cands = [p for p in partial_candidates(t["norm"], vocab) if p["dist"] <= 1 or p["contains"]]
            near = [p for p in cands if p["tag"] in ctx.in_view and
                    min(dist(c, q) for q in ctx.in_view[p["tag"]]["instances"]) <= NEAR * _tol(ctx, ctx.in_view[p["tag"]]["view"])]
            if len(near) == 1 and near[0]["tag"] == tag:
                rec = {"raw": t.get("text"), "tag": tag, "conf": t.get("conf", 0), "passes": 1, "box": t["box"],
                       "center": c, "method": "partial"}
                return "partial", rec, info
        return "absent", None, info


# ------------------------------------------------------------------ ORDER
@check("ORDER")
class OrderCheck:
    """Devices of one aligned group (same family, same rail/row) appear in the drawing's order; a swap is named."""
    title = "Right order"
    question = "Are the devices of this group in the order the drawing shows?"

    def run(self, ctx):
        out = []
        explained = ctx.facts.setdefault("order_explained", {})
        zoom = ctx.facts.get("zoom_reads", {})
        for g in ctx.kb.get("groups") or []:
            required = [t for t in g["order"] if ctx.label_expected(t)]
            if len(required) < 2:
                continue
            fid = f"ORD-{g['id']}"
            required_seq = " · ".join(required)
            fit = ctx.fit(g["view"])
            if not fit:
                out.append(finding(fid, "ORDER", g["id"], required_seq, "Drawing view not located in this photo",
                                   "NOT_IN_VIEW", view=g["view"], rule="ORDER.not_in_view"))
                continue
            members = [t for t in required if t in ctx.in_view]
            if len(members) < 2:
                out.append(finding(fid, "ORDER", g["id"], required_seq, "Too little of the group is in view",
                                   "NOT_IN_VIEW", view=g["view"], rule="ORDER.partial_view"))
                continue
            placed = {}
            for t in members:
                rs = [r for r in ctx.reads_of(t) if r.get("dist_px") is not None] + zoom.get(t, [])
                if rs:
                    pred = ctx.in_view[t]["predicted"]
                    placed[t] = min(rs, key=lambda r: dist(r["center"], pred))
            if len(placed) < 2:
                out.append(finding(fid, "ORDER", g["id"], required_seq, "Too few complete labels could be read",
                                   "UNCERTAIN", view=g["view"], rule="ORDER.unreadable",
                                   hint=f"Capture the {g['family']} group so every label is readable"))
                continue
            a = 0 if g["axis"] == "x" else 1
            coord = {t: unproject(fit, placed[t]["center"])[a] for t in placed}
            expected = [t for t in g["order"] if t in placed]
            observed = sorted(placed, key=lambda t: coord[t])
            box = union([box_around(placed[t]["center"], 3 * max(ctx.text_px(t), 6), 2 * max(ctx.text_px(t), 6),
                                    ctx.photo["size"]) for t in placed])
            drawing = {"page": ctx.kb["views"][g["view"]]["page"], "view": g["view"],
                       "bbox": union([b for t in placed for b in [i["bbox"] for i in (ctx.tag_rec(t) or {}).get("instances", [])]])}
            reads = [_rd(placed[t]) for t in expected]
            seq = " · ".join(expected)
            if observed == expected:
                full = len(placed) == len(required)
                literal = all(_verified_read(p) for p in placed.values())
                status = "OK" if full and literal else "NOT_IN_VIEW" if len(members) < len(required) else "UNCERTAIN"
                out.append(finding(fid, "ORDER", g["id"], required_seq, seq, status, box, view=g["view"], drawing=drawing,
                                   conf=min(p["conf"] for p in placed.values()), rule="ORDER.matches", reads=reads,
                                   evidence=[f"{len(placed)} of {len(members)} {g['family']} labels read, in the "
                                             f"drawing's {'left-to-right' if a == 0 else 'top-to-bottom'} order"],
                                   hint=None if status == "OK" else f"Capture the full {g['family']} group with every label readable"))
                continue
            pitch = float(g.get("pitch_pt") or 0) or 5.0
            ambiguous = all(abs(coord[x] - coord[y]) < 0.35 * pitch
                            for x, y in zip(observed, observed[1:]) if expected.index(x) > expected.index(y))
            pairs = self._swaps(expected, observed)
            names = ", ".join(f"{x} <-> {y} swapped" for x, y in pairs) if pairs else "wrong order"
            if ambiguous:
                out.append(finding(fid, "ORDER", g["id"], required_seq, " · ".join(observed), "UNCERTAIN", box, view=g["view"],
                                   drawing=drawing, conf=0.6, rule="ORDER.ambiguous", reads=reads,
                                   evidence=["labels sit too close along the rail to tell the order apart"],
                                   hint=f"Capture the {g['family']} group straight on so positions can be distinguished"))
                continue
            involved = sorted({t for p in pairs for t in p} or set(observed), key=tag_sort_key)
            strong = all(placed[t].get("anchor") and _verified_read(placed[t]) and _strong_read(placed[t]) for t in involved) and all(
                min(dist(placed[t]["center"], p) for p in ctx.in_view[t]["instances"]) >= 0.5 * pitch * fit["scale_px_per_pt"]
                for t in involved)
            for t in involved:
                explained[t] = fid
            out.append(finding(fid, "ORDER", g["id"], seq, " · ".join(observed), "CANDIDATE_FAULT", box, view=g["view"],
                               drawing=drawing, strength="strong" if strong else "weak", conf=0.8 if strong else 0.6,
                               rule="ORDER.swap" if pairs else "ORDER.mismatch", reads=reads, swaps=pairs,
                               evidence=[f"drawing order: {seq}", f"photo order: {' · '.join(observed)}", names],
                               question=f"The drawing orders these {g['family']} devices as {seq}. In the photo the "
                                        f"labels read {' · '.join(observed)}. Are they really in the wrong order?",
                               hint=f"Re-photo the {g['family']} group straight on so every label is sharp"))
        return out

    @staticmethod
    def _swaps(expected, observed):
        """Transpositions turning ``expected`` into ``observed`` when the difference is pure pair swaps."""
        pos = {t: i for i, t in enumerate(observed)}
        seen, pairs = set(), []
        for i, t in enumerate(expected):
            if t in seen or observed[i] == t:
                continue
            j = pos[t]
            if expected[j] == observed[i] and observed[j] == t:
                pairs.append((observed[i], t) if tag_sort_key(observed[i]) < tag_sort_key(t) else (t, observed[i]))
                seen |= {t, observed[i]}
            else:
                return []
        return pairs


def _layout_refs(ctx, view, tag):
    """(photo xy, drawing xy, same group) references for the layout rule: the fit's anchored labels, plus every label
    of the tag's own ordered group read with certainty (a swapped neighbour must count). Off-fit labels of other groups
    are left out: they may be misplaced themselves."""
    fit = ctx.fit(view)
    group = set()
    for g in ctx.kb.get("groups") or []:
        if g["view"] == view and tag in g["order"]:
            group |= set(g["order"])
    vt = ctx.views.get(view, {})
    refs, seen = [], {tag}
    for a in (fit or {}).get("inliers") or []:
        if a["tag"] not in seen and vt.get(a["tag"], {}).get("center"):
            seen.add(a["tag"])
            refs.append((a["photo"], vt[a["tag"]]["center"], a["tag"] in group))
    for r in sorted(ctx.reads, key=lambda r: (-r["passes"], -r["conf"])):
        t = r["tag"]
        if t in seen or t not in group or not r.get("anchor") or not vt.get(t, {}).get("center"):
            continue
        seen.add(t)
        refs.append((r["center"], vt[t]["center"], True))
    return refs


def _other_family_pt(ctx, view):
    """Drawing distance that clearly separates labels of different device families (~2.5 % of the view): a label
    sits anywhere on its device, so two device types' labels a few points apart on the drawing may swap sides."""
    b = ctx.kb["views"][view].get("bbox") or ctx.kb["views"][view].get("region")
    return 0.025 * max(b[2] - b[0], b[3] - b[1])


# ------------------------------------------------------------------ LABEL
@check("LABEL")
class LabelCheck:
    """The label at each device reads exactly the drawing tag (either of its labels), at the place the drawing shows."""
    title = "Device label"
    question = "Does the label at this device read exactly the drawing tag?"

    def run(self, ctx):
        out = []
        presence = ctx.facts.get("presence", {})
        wrong = ctx.facts.get("wrong_reads", {})
        zoom = ctx.facts.get("zoom_reads", {})
        explained = ctx.facts.get("order_explained", {})
        for tag, rs in sorted(ctx.facts.get("unplaced", {}).items(), key=lambda kv: tag_sort_key(kv[0])):
            best = _best_read(rs)
            out.append(finding(f"LBL-{tag}", "LABEL", tag, tag, tag, "UNCERTAIN", union([r["box"] for r in rs]),
                               view=best.get("view"), conf=best["conf"], rule="LABEL.read_view_not_placed",
                               reads=[_rd(r) for r in rs], evidence=[_read_text(best) + " (position not judged)"],
                               hint="Capture surrounding labels to locate this device against the matching drawing"))
        unplaced = ctx.facts.get("unplaced", {})
        seen = set()
        for view, tags in ctx.views.items():
            for tag, rec in sorted(tags.items(), key=lambda kv: tag_sort_key(kv[0])):
                if tag in ctx.in_view or tag in unplaced or tag in seen or not rec.get("label_expected", True):
                    continue
                seen.add(tag)
                out.append(finding(f"LBL-{tag}", "LABEL", tag, tag, "Outside the verified photo coverage",
                                   "NOT_IN_VIEW", view=view, rule="LABEL.not_in_view",
                                   hint=f"Capture the {tag} area with surrounding readable labels"))
        for tag in sorted(ctx.in_view, key=tag_sort_key):
            if not ctx.label_expected(tag):
                continue
            iv = ctx.in_view[tag]
            tol = _tol(ctx, iv["view"])
            box = ctx.label_box(tag)
            fid = f"LBL-{tag}"
            common = dict(view=iv["view"], drawing=_drawing_ref(ctx, tag))
            p = presence.get(tag)
            if p == "absent":
                out.append(finding(fid, "LABEL", tag, tag, "-", "SKIP", box, rule="LABEL.part_missing",
                                   root_cause=f"MISS-{tag}", evidence=[f"root cause: MISS-{tag}"], **common))
                continue
            if p in (None, "unjudged"):
                out.append(finding(fid, "LABEL", tag, tag, "Not verifiable in this photo", "NOT_IN_VIEW", box,
                                   rule="LABEL.not_judged", evidence=["see the presence check"], **common))
                continue
            if p in ("read", "zoom", "partial"):
                rs = [r for r in ctx.reads_of(tag) if r.get("dist_px") is not None and r["dist_px"] <= NEAR * tol]
                rs = rs or zoom.get(tag, [])
                best = _best_read(rs)
                partial = not _verified_read(best)
                out.append(finding(fid, "LABEL", tag, tag, tag if not partial else best.get("raw", "Incomplete label"),
                                   "UNCERTAIN" if partial else "OK", box, conf=best["conf"] * (0.85 if partial else 1),
                                   rule="LABEL.partial_support" if partial else "LABEL.read_at_predicted",
                                   evidence=[_read_text(best) + (" (partial; only this tag fits here)" if partial else "")],
                                   hint=f"Capture the complete {tag} label so every character is readable" if partial else None,
                                   reads=[_rd(r) for r in rs], **common))
                continue
            if p == "wrong":
                wr = wrong[tag]
                txt = wr.get("tag") or wr.get("tag_like")
                if txt in explained or tag in explained:
                    rc = explained.get(tag) or explained.get(txt)
                    out.append(finding(fid, "LABEL", tag, tag, txt, "SKIP", box, rule="LABEL.explained_by_order",
                                       root_cause=rc, reads=[_rd(wr)], evidence=[f"root cause: {rc}"], **common))
                    continue
                strong = _strong_read(wr) and normalize(wr.get("raw", "")) == txt
                out.append(finding(fid, "LABEL", tag, tag, txt, "CANDIDATE_FAULT", box,
                                   strength="strong" if strong else "weak", conf=0.8 if strong else 0.6,
                                   rule="LABEL.wrong_text", reads=[_rd(wr)],
                                   evidence=[f"the drawing expects '{tag}' here", _read_text(wr) + " at that spot"],
                                   question=f"Does the label at the marked spot read '{tag}' (the drawing) or "
                                            f"'{txt}' (what OCR read)?",
                                   hint=f"Re-photo the {tag} label from 30 cm, straight on", **common))
                continue
            # p == "far": read, but not where the drawing puts it
            rs = [r for r in ctx.reads_of(tag) if r.get("dist_px") is not None]
            best = min(rs, key=lambda r: (not _verified_read(r), r["dist_px"]))
            d = best["dist_px"]
            fit = ctx.fit(iv["view"])
            scale = fit["scale_px_per_pt"]
            if not _verified_read(best):
                out.append(finding(fid, "LABEL", tag, tag, best.get("raw", "Incomplete label"), "UNCERTAIN", box,
                                   conf=best["conf"], rule="LABEL.uncertain_read", reads=[_rd(r) for r in rs],
                                   evidence=[_read_text(best), "a vocabulary repair does not verify the literal label"],
                                   hint=f"Capture the full {tag} label sharply", **common))
                continue
            if d <= FAR * tol:
                out.append(finding(fid, "LABEL", tag, tag, tag, "OK", box, conf=best["conf"] * 0.9,
                                       rule="LABEL.read_offset", reads=[_rd(r) for r in rs],
                                   evidence=[_read_text(best) + f", {d:.0f} px from its drawn spot (within tolerance)"],
                                   **common))
                continue
            if tag in explained:
                out.append(finding(fid, "LABEL", tag, tag, tag, "SKIP", box, rule="LABEL.explained_by_order",
                                   root_cause=explained[tag], reads=[_rd(best)],
                                   evidence=[f"root cause: {explained[tag]}"], **common))
                continue
            if not iv.get("anchored", True) and not iv.get("off_fit"):
                out.append(finding(fid, "LABEL", tag, tag, tag, "UNCERTAIN", box, conf=best["conf"] * 0.85,
                                   rule="LABEL.read_not_anchored", reads=[_rd(r) for r in rs],
                                   evidence=[_read_text(best), "its drawn spot lies beyond the labels this photo could "
                                             "anchor, so its position is not judged"],
                                   hint=f"Capture {tag} with nearby readable labels to verify its drawing position",
                                   **common))
                continue
            dpt = (ctx.tag_rec(tag) or {}).get("center")
            refs = _layout_refs(ctx, iv["view"], tag)
            other = _other_family_pt(ctx, iv["view"])
            checks_ = [layout_consistent(fit, r["center"], dpt, refs, min_pt_other=other)
                       for r in rs if r.get("anchor")] if dpt else []
            good = [c for c in checks_ if c[0]]
            if good:
                out.append(finding(fid, "LABEL", tag, tag, tag, "OK", box, conf=best["conf"] * 0.85,
                                   rule="LABEL.layout_consistent", reads=[_rd(r) for r in rs],
                                   evidence=[_read_text(best), f"away from the scaled drawing position, but on the same side "
                                             f"of every other certainly read label as on the drawing ({good[0][1]} "
                                             f"comparisons): the drawing is not to scale here or the photo is taken at "
                                             f"an angle"], **common))
                continue
            fbox = [best["box"][0], best["box"][1], best["box"][2], best["box"][3]]
            out.append(finding(fid, "LABEL", tag, f"{tag} at its drawn position", f"{tag} found elsewhere",
                               "CANDIDATE_FAULT", union([box, fbox]), strength="weak", conf=0.55,
                               rule="LABEL.misplaced", reads=[_rd(r) for r in rs], found_box=fbox,
                               evidence=[_read_text(best) + f" {d:.0f} px (~{d / max(scale, 1e-6):.0f} pt on the drawing) "
                                         f"from where the drawing places it", "no swap in its group explains it"],
                               question=f"The drawing places {tag} at the first marked spot, but its label was read at "
                                        f"the second. Is {tag} installed in a different place than drawn?",
                               hint=f"Re-photo the area between the drawn and the found position of {tag}", **common))
        return out


# ------------------------------------------------------------------ UNKNOWN_LABEL
@check("UNKNOWN_LABEL")
class UnknownLabelCheck:
    """A clearly read, tag-shaped label that the drawing set does not list at all (an extra or wrongly named part)."""
    title = "Unknown label"
    question = "Is there a labelled part the drawing does not list?"

    def run(self, ctx):
        vocab = _vocab(ctx)
        shapes = {}
        for t in vocab:
            shapes.setdefault(family_of(t), set()).add(_skeleton(t))
        wrong_ids = {id(r) for r in ctx.facts.get("wrong_reads", {}).values()}
        wrong_text = {(r.get("tag") or r.get("tag_like")): tag for tag, r in ctx.facts.get("wrong_reads", {}).items()}
        groups = {}
        for u in ctx.unknown:
            if _skeleton(u["tag_like"]) not in shapes.get(u["family"], ()):
                continue                      # not the letter pattern of any drawing tag (model numbers, ratings ...)
            if not (u["passes"] >= 2 or (u["norm"] == u["tag_like"] and u["conf"] >= 0.9)):
                continue
            if self._misread_of_known(ctx, u):
                continue
            groups.setdefault(u["tag_like"], []).append(u)
        out = []
        for text, us in sorted(groups.items(), key=lambda kv: tag_sort_key(kv[0])):
            best = max(us, key=lambda r: (r["passes"], r["conf"]))
            box = union([u["box"] for u in us])
            fid = f"UNK-{text}"
            f = view_of_point(ctx.reg, best["center"])
            view = f["view"] if f else None
            if any(id(u) in wrong_ids for u in us) or text in wrong_text:
                tag = wrong_text.get(text)
                out.append(finding(fid, "UNKNOWN_LABEL", text, "-", text, "SKIP", box, view=view,
                                   rule="UNKNOWN_LABEL.at_expected_device", root_cause=f"LBL-{tag}",
                                   reads=[_rd(u) for u in us], evidence=[f"read where {tag} should be: root cause LBL-{tag}"]))
                continue
            strong = _strong_read(best) and normalize(best["raw"]) == text
            near = ", ".join(best["candidates"][:4])
            out.append(finding(fid, "UNKNOWN_LABEL", text, "Only drawing tags", text, "CANDIDATE_FAULT", box, view=view,
                               strength="strong" if strong else "weak", conf=0.8 if strong else 0.6,
                               rule="UNKNOWN_LABEL.not_in_drawing", reads=[_rd(u) for u in us],
                               evidence=[_read_text(best), f"'{text}' is not in the drawing set's "
                                                           f"{len(vocab)} tags" + (f" (closest: {near})" if near else "")],
                               question=f"Does the label at the marked spot read '{text}'? (That tag is not in the "
                                        f"drawing set.)",
                               hint=f"Re-photo the {text} label from 30 cm to confirm the text"))
        return out

    @staticmethod
    def _misread_of_known(ctx, u):
        """The same label also read as a drawing tag with at least as much support: a misread, not a new label."""
        for r in ctx.reads:
            b, a = r["box"], u["box"]
            ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
            small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
            if ix / small >= 0.3 and r["passes"] >= u["passes"]:
                return True
        return False


# ------------------------------------------------------------------ FERRULE
@check("FERRULE")
class FerruleCheck:
    """Wire markers name two devices of the drawing that the drawing connects (when its wiring could be extracted)."""
    title = "Wire ferrule"
    question = "Does the ferrule name a connection the drawing contains?"

    def run(self, ctx):
        links = {tuple(sorted(l)) for l in ctx.kb.get("device_links") or []}
        wired = {d for l in links for d in l}
        presence = ctx.facts.get("presence", {})
        groups = {}
        for f in ctx.ferrules:
            if not f["from"]["device"] or not f["to"]["device"]:
                continue
            groups.setdefault(f["norm"], []).append(f)
        out = []
        for norm, fs in sorted(groups.items()):
            best = max(fs, key=lambda r: (r["passes"], r["conf"]))
            a, b = best["from"]["device"], best["to"]["device"]
            fid = f"FER-{norm}"
            box = union([f["box"] for f in fs])
            fit = view_of_point(ctx.reg, best["center"])
            view = fit["view"] if fit else None
            reads = [_rd(dict(f, tag=f["norm"])) for f in fs]
            unknown = [d for d, e in ((a, best["from"]), (b, best["to"])) if not e["known"]]
            missing = [d for d in (a, b) if presence.get(d) == "absent"]
            linked = tuple(sorted((a, b))) in links or a == b
            # a ferrule can only contradict the drawing on a certain read: both names printed verbatim, two passes
            certain = _verbatim(best["raw"], a) and _verbatim(best["raw"], b) and (best["passes"] >= 2 or best["conf"] >= 0.97)
            if (unknown or (links and not linked)) and not certain:
                continue                          # a garbled read is no evidence either way
            own = None
            if unknown:
                own = finding(fid, "FERRULE", norm, "Devices of the drawing", norm, "CANDIDATE_FAULT", box, view=view,
                              strength="weak", conf=0.55, rule="FERRULE.unknown_device", reads=reads,
                              evidence=[_read_text(best), f"{', '.join(unknown)} is not in the drawing set"],
                              question=f"Does the wire marker at the marked spot read '{norm}'?",
                              hint="Re-photo the ferrule from 20-30 cm so its print is sharp")
            elif not links:
                own = finding(fid, "FERRULE", norm, "Connection in the drawing", norm, "SKIP", box, view=view,
                              rule="FERRULE.no_wiring", reads=reads,
                              evidence=["no wiring could be extracted from this drawing set; ferrule not judged"])
            elif linked:
                own = finding(fid, "FERRULE", norm, f"{a} - {b} in the drawing", norm, "OK" if certain else "UNCERTAIN", box, view=view,
                              conf=best["conf"], rule="FERRULE.link_in_drawing", reads=reads,
                              evidence=[_read_text(best), f"the drawing connects {a} and {b}"],
                              hint=None if certain else "Capture the complete wire marker sharply without obstructions")
            elif a in wired and b in wired:
                own = finding(fid, "FERRULE", norm, "Connection in the drawing", f"{a} - {b}", "CANDIDATE_FAULT", box,
                              view=view, strength="weak", conf=0.55, rule="FERRULE.link_not_in_drawing", reads=reads,
                              evidence=[_read_text(best), f"the drawing has no wire between {a} and {b}"],
                              question=f"Does the wire marker at the marked spot read '{norm}'? The drawing has no "
                                       f"connection between {a} and {b}.",
                              hint="Re-photo the ferrule from 20-30 cm so its print is sharp")
            else:
                own = finding(fid, "FERRULE", norm, "Connection in the drawing", norm, "SKIP", box, view=view,
                              rule="FERRULE.not_extracted", reads=reads,
                              evidence=[f"the drawing's extracted wiring does not cover {a if a not in wired else b}; "
                                        f"not judged"])
            if missing and own["status"] != "SKIP":
                rc = f"MISS-{missing[0]}"
                out.append(dict(own, status="SKIP", strength=None, root_cause=rc, own_status=own["status"],
                                own_strength=own["strength"], evidence=own["evidence"] + [f"root cause: {rc}"]))
            else:
                out.append(own)
        return out


# ------------------------------------------------------------------ COLOUR
COLOUR_MIN_CONF = 0.6       # a wire colour measured less surely than this is not judged


def wire_list_requirement():
    """The uploaded wire list as an open document requirement: its terminal positions are not verified automatically."""
    return finding("DOC-WIRELIST", "COLOUR", "Uploaded wire list", "Wire-list requirements verified",
                   "Wire-list terminal positions need manual verification", "UNCERTAIN", conf=0.0,
                   rule="COLOUR.unsupported_input",
                   evidence=["Drawing-derived device links and wire colours by circuit class are checked separately; "
                             "they do not verify every terminal, pin or colour in the uploaded wire list"],
                   hint="Compare the uploaded wire list with terminal close-ups and record a manual inspection")


@check("COLOUR")
class ColourCheck:
    """Wire colours by circuit class, next to every wire ferrule read. The colour rule comes from the cabinet's own drawing
    legend or a profile chosen for the project, never from an assumed standard (wire_rules.py); the circuit class of a
    wire from the drawing's power schematics via the two ends its ferrule names; the colour from the photo next to the
    sleeve (vision/wire_colour.py). Green-and-yellow on anything but protective earth is checked under every rule.
    A wire whose colour cannot be measured, or whose circuit the rule does not cover, gets no item: the report's wire
    rule note counts them."""
    title = "Wire colour"
    question = "Is the wire the colour its circuit class requires?"

    def run(self, ctx):
        import wire_rules
        from vision import wire_colour

        rule = wire_rules.rules(ctx.kb, None, ctx.cfg.get("colour_profile"))
        cc = wire_rules.circuit_classes(ctx.kb)
        info = wire_rules.describe(rule, cc)
        tally = {"ferrules": 0, "judged": 0, "not_measured": 0, "no_rule": 0}
        out = [wire_list_requirement()] if ctx.wires else []
        groups = {}
        for f in ctx.ferrules:
            if f["from"]["device"] and f["to"]["device"]:
                groups.setdefault(f["norm"], []).append(f)
        rgb = ctx.photo.get("rgb")
        for norm, fs in sorted(groups.items()):
            tally["ferrules"] += 1
            best = max(fs, key=lambda r: (r["passes"], r["conf"]))
            col = wire_colour.classify(rgb, best["box"], best.get("rot", 0), best.get("quad")) if rgb is not None else None
            if not col or col["conf"] < COLOUR_MIN_CONF:
                tally["not_measured"] += 1
                continue
            certain = best["from"]["known"] and best["to"]["known"] and (best["passes"] >= 2 or best["conf"] >= 0.9)
            cls, why = wire_rules.wire_class([best["from"], best["to"]], cc) if certain else (None, "ferrule not read with certainty")
            item = self._judge(norm, best, col, cls, why, rule, certain)
            if item is None:
                tally["no_rule"] += 1
                continue
            tally["judged"] += 1
            fit = view_of_point(ctx.reg, best["center"])
            box = union([best["box"]] + col["boxes"])
            out.append(dict(item, box=[round(float(v), 1) for v in box], view=fit["view"] if fit else None,
                            reads=[_rd(dict(r, tag=r["norm"])) for r in fs]))
        info.update(tally)
        ctx.facts["wire_rule"] = info
        src = rule.get("source") or "no wire-colour rule (universal green-and-yellow rule only)"
        ctx.facts["colour_note"] = (f"Wire colours: {tally['judged']} of {tally['ferrules']} ferrule wire(s) judged against "
                                    f"{src}" + (f"; {tally['not_measured']} not measurable in this photo"
                                                if tally["not_measured"] else ""))
        return out

    @staticmethod
    def _judge(norm, best, col, cls, why, rule, certain):
        """The finding for one measured wire colour, or None when the rule does not decide it."""
        import wire_rules
        from vision.wire_colour import name

        c, conf = col["code"], col["conf"]
        src = rule.get("source")
        seen = f"{name(c)} ({c}): {col['reason']}"
        ev = [f"wire colour {seen}; white reference: {col['white']}"]
        common = dict(conf=conf, swatch=col["swatch"], colour=c, wire_class=cls, rule_source=src,
                      sample_boxes=col["boxes"])
        ends = f"{best['from']['device']} and {best['to']['device']}"

        def item(expected, status, rule_id, evidence, allowed=(), strength=None, question=None, hint=None):
            return finding(f"COL-{norm}", "COLOUR", norm, expected, f"{c} ({name(c)})", status, strength=strength,
                           rule=rule_id, evidence=ev + evidence, question=question, hint=hint, allowed=list(allowed),
                           **common)

        if c == "GN/YE":
            if cls == "PE":
                return item("GN/YE (protective earth)", "OK", "COLOUR.earth_green_yellow", [why],
                            wire_rules.allowed(rule, "PE"))
            if cls or (certain and not any(wire_rules._kind(e["device"], e["pin"]) == "EARTH"
                                          for e in (best["from"], best["to"]))):
                where = why if cls else f"neither {ends} is an earth point"
                return item("Not green-and-yellow" + (f" ({wire_rules.CLASS_NAME[cls]})" if cls else ""),
                            "CANDIDATE_FAULT", "COLOUR.reserved_green_yellow",
                            ["green-and-yellow identifies the protective conductor only, under every standard", where],
                            wire_rules.allowed(rule, cls) if cls else (),
                            strength="strong" if cls and conf >= 0.85 else "weak",
                            question=f"Is the wire with ferrule '{norm}' green-and-yellow? It connects {ends}, which is "
                                     f"not protective earth.",
                            hint="Re-photo the ferrule with a few cm of wire on both sides, in neutral light")
            return None
        if cls == "PE":
            ok = wire_rules.allowed(rule, "PE")
            if c in ok:
                return item("/".join(ok) + " (protective earth)", "OK", "COLOUR.earth_green", [why], ok)
            return item("/".join(ok) + " (protective earth)", "CANDIDATE_FAULT", "COLOUR.earth_not_green",
                        [why, f"protective earth is identified by {' or '.join(name(x) for x in ok)}"
                              + (f" ({src})" if src else " (universal rule)")], ok, strength="weak",
                        question=f"Is the earth wire with ferrule '{norm}' {name(c)} rather than green-and-yellow?",
                        hint="Re-photo the ferrule with a few cm of wire on both sides, in neutral light")
        if not src:
            return None                                       # no rule chosen: only the universal rule applies
        if cls:
            ok = wire_rules.allowed(rule, cls)
            if not ok:
                return None                                   # the rule sets no colour for this circuit class
            label = f"{'/'.join(ok)} ({wire_rules.CLASS_NAME[cls]})"
            if c in ok:
                return item(label, "OK", "COLOUR.allowed", [why, f"{c} is allowed for {wire_rules.CLASS_NAME[cls]} ({src})"],
                            ok)
            return item(label, "CANDIDATE_FAULT", "COLOUR.not_allowed",
                        [why, f"{src} allows {', '.join(name(x) for x in ok)} for {wire_rules.CLASS_NAME[cls]}"], ok,
                        strength="weak",
                        question=f"Is the wire with ferrule '{norm}' {name(c)}? It is on the "
                                 f"{wire_rules.CLASS_NAME[cls]} side, where {src} allows {', '.join(ok)}.",
                        hint="Re-photo the ferrule with a few cm of wire on both sides, in neutral light")
        used = sorted({x for k in wire_rules.CLASSES for x in wire_rules.allowed(rule, k)})
        if certain and c not in used:
            return item("A colour of the wire rule", "CANDIDATE_FAULT", "COLOUR.not_in_rule",
                        [why, f"{name(c)} is not a colour {src} uses for any circuit ({', '.join(used)})"], used,
                        strength="weak",
                        question=f"Is the wire with ferrule '{norm}' {name(c)}? {src} uses no such colour.",
                        hint="Re-photo the ferrule with a few cm of wire on both sides, in neutral light")
        return None
