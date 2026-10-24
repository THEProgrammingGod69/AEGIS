# EAGLE EYE 4 — real-cabinet engine: module contracts

Internal design reference for the Grand-Finale engine (brief: Emerson PS#03, cabinet 13GE03331).
It fixes the module layout, the data passed between stages and the rules every stage must respect,
so the stages can be built and tested independently. The legacy synthetic-cabinet engine
(`inspector.py`, demo drawing EE-DEMO-01 + wire list) keeps working unchanged next to it.

## 0. Non-negotiable rules

1. **The drawing is ground truth.** Every check asks "is expected item X here, correct and in the right place?". Nothing is
   hard-coded for 13GE03331: vocabulary, views, positions, groups and connections come from the PDF.
2. **Only judge what is visible.** Items outside the photo's covered area are `NOT_IN_VIEW` (neutral), never REVIEW.
3. **FAIL needs two agreeing independent signals.** With the Claude agent: deterministic (OCR/geometry) AND the agent.
   Without it (the default deployment, no API key): a *strong positive* candidate (wrong/unknown label read identically by
   two independent OCR passes, or a swap read at both spots) FAILs on its own; absence (MISSING) never does and stays
   REVIEW with a precise re-photo hint. `EAGLE_FAIL_WITHOUT_AGENT=0` disables the deterministic FAIL.
4. **Precision over recall**; REVIEW must stay rare (< 5 % of in-view items).
5. **Deterministic first, LLM second.** The agent verifies candidates and resolves unclear crops; it never invents items.
6. Every finding carries evidence (crop box, OCR reads, rule fired, agent answer) and is reproducible (caches keyed by hashes).
7. Photos: EXIF-transpose first; ignore the watermark (bottom-left) and timestamp (bottom-right) bands.

## 1. Layout and imports

`eagle_eye/` is on `sys.path` (server.py, tests and CLIs run from there; `eagle_eye/__init__.py` inserts it for
`python -m eagle_eye.<pkg>.<mod>` from the repo root). Engine modules import each other with **absolute top-level names**:
`import config`, `from kb import drawing_kb`, `from kb.tags import normalize`, `from vision import ocr`, `import consensus`.

```
eagle_eye/kb/tags.py          tag families, normalisation, coerce_to_family()           (shared)
eagle_eye/kb/drawing_kb.py    Phase 1  build_kb(pdf) -> cabinet model (cached by SHA-256), CLI + debug PNGs
eagle_eye/vision/preprocess.py Phase 2 load_photo(): EXIF, ignore-mask, quality score
eagle_eye/vision/decode.py    Phase 2  closed-vocabulary decoding, ferrule parser
eagle_eye/vision/ocr.py       Phase 2  PP-OCRv4 (RapidOCR/ONNX Runtime) multi-pass reader, Tesseract fallback, cache
eagle_eye/vision/register.py  Phase 3  view localisation, RANSAC drawing->photo fit, coverage
eagle_eye/checks/             Phase 4  @check registry + LABEL, UNKNOWN_LABEL, ORDER, MISSING, FERRULE, COLOUR
eagle_eye/agent/              Phase 5  Claude vision verifier (tool use), backends anthropic|replay|mock, cache, audit log
eagle_eye/consensus.py        Phase 6  candidate + decision -> PASS/FAIL/REVIEW/NOT_IN_VIEW/SKIP, root cause, multi-photo merge
eagle_eye/pipeline.py         A..H orchestration for real cabinets (inspect_real); service.py routes to it
eagle_eye/forge_real.py       Phase 8  planted-fault variants of real photos + answer key
eagle_eye/eval_real.py        Phase 8  evaluation on real + forged photos
```

Coordinates: **drawing** = PDF points of the GA page (origin top-left, y down); **photo** = pixels of the EXIF-transposed,
full-resolution photo. Boxes are `[x0, y0, x1, y1]` unless a field says otherwise.

## 2. Tag families (`kb/tags.py`)

```python
FAMILIES: list[tuple[str, str]]   # (family, full-match regex on normalised text), most specific first, e.g.
  CSLS \d{2}CSLS\d{5} · CBP \d{3}CBP\d{2} · RDEW \d{2}RDEW-\d{2}[A-Z]\d{3}[A-Z]{1,2} · TERM TERM\d[FR] · RCCB RCCB\d
  SPD SPD\d · REC REC\d · FILTER FILTER ?\d · XFSW (X|ALM)-[A-Z]+\d* (X-ALM, X-FSW1, ALM-FSW2) · FSW FSW\d
  CB CB\d{1,3} · PS PS\d{1,3} · DS DS\d{1,3} · D D\d{2} · SB SB\d{2} · TS TS\d · CF CF\d · CL CL\d
  X X[A-Z]?\d{1,3} (X1, X11, XP11, XS21, XG11, XU1) · EARTH IPE|IE|ISE|ISG|DCG
normalize(s) -> str          # upper-case, strip spaces/quotes, keep A-Z 0-9 - / ; 'FILTER 1' -> 'FILTER1'
family_of(tag) -> str|None
coerce_to_family(s) -> list[(family, coerced)]   # fix OCR confusions by the family's expected char class per position
                                                  # (e.g. '334C8P06' -> ('CBP','334CBP06'), 'OS21' -> ('DS','DS21'))
```

## 3. Cabinet model (`kb/drawing_kb.py` → `cabinet_model.json`, schema `eagle-eye-kb/1`)

```jsonc
{
  "schema": "eagle-eye-kb/1", "kb_version": "1.0", "pdf_sha256": "…", "pdf_name": "…",
  "cabinet": "13GE03331",
  "pages": [{"page": 5, "kind": "ga", "title": "INTERNAL GENERAL ARRANGEMENT - FRONT AND SIDE VIEW - 13GE03331",
             "size": [1191, 842], "vector": true, "views": ["left", "front", "right"]}],
  // page kinds: legend, abbreviations, outline, top_view, ga, bom, power, network, grounding, earthing, nameplate, other
  "views": {
    "front": {
      "page": 5, "title": "FRONT INSIDE VIEW", "bbox": [x0, y0, x1, y1],   // the cabinet outline of this view (pt)
      "tags": [{
        "tag": "PS11", "family": "PS",
        "center": [x, y],                         // mean of the in-drawing instances (pt)
        "instances": [{"bbox": [..], "center": [x, y], "rot": 0, "size_pt": 1.6}],   // rot in {0, 90, 180, 270}
        "device_bbox": [..] | null,               // smallest enclosing rectangle when one exists
        "label": {"w_mm": 20, "h_mm": 10, "qty": 2} | null   // from the nameplate list
      }],
      "callouts": [{"tag": "PS11", "bbox": [..]}]   // large leader-list text outside the outline: membership only, no position
    },
    "rear": {…}, "left": {…}, "right": {…}
  },
  "vocabulary": ["13CSLS03331", "…"],   // nameplate list ∪ GA in-drawing tags ∪ device tags on power/grounding pages
  "nameplates": [{"tag": "PS11", "type": "ADHESIVE LABEL", "size": "20MM X 10MM", "w_mm": 20, "h_mm": 10, "letter": "6MM",
                  "qty": 2, "page": 16}],
  "devices": {"PS11": {"family": "PS", "views": ["front"], "pages": [5, 9], "nameplate": true}},
  "groups": [{"id": "front-PS-1", "view": "front", "family": "PS", "axis": "x", "order": ["PS11", "PS21", "PS12", "PS22"]}],
  "connections": [{"from": "CB12-2", "to": "PS12-L", "from_device": "CB12", "to_device": "PS12", "page": 9,
                   "confidence": 0.6}],
  "device_links": [["CB12", "PS12"]],     // undirected device-level adjacency derived from connections
  "wire_colours": {"230VAC": ["BK", "BN", "GN/YE"], "24VDC": ["BK", "WH", "GN"], "ALARM": ["OR", "WH", "BK"]},
  "stats": {…}
}
```

* In-drawing instances are the small text placed on the device (nameplate size ≈ 1–3 pt on this set); callouts are the big
  leader-list text (≈ 6–7 pt) beside the view. Decide by size relative to the page's distribution, not a fixed constant.
* A page can hold several views side by side (page 5: LEFT / FRONT / RIGHT INSIDE VIEW). Assign tags to the view whose title
  column contains them (nearest title centre in x, below the title).
* Groups: same family + same view + aligned (1-D clustering on the perpendicular coordinate); `axis` = direction of larger
  spread; `order` sorted along it (x: left→right, y: top→bottom). ≥ 2 members.
* API: `build_kb(pdf_path, cache_dir=None, use_vlm_fallback=True) -> dict` (cached by SHA-256 under `config.DATA/cache/kb/`),
  `view_tags(kb, view) -> dict[tag, tagrec]`, `is_real_drawing(pdf_path) -> bool` (True when a GA page is found),
  `render_page(pdf, page, dpi) -> PIL.Image`, `drawing_crop(kb, pdf, view, tag|bbox, margin_pt, dpi) -> PIL.Image`.
* Raster/unparseable GA page → optional Claude extraction (`agent.extract_drawing_tags`) with `source: "vlm"`; off when no key.

## 4. Photo + perception

```python
# vision/preprocess.py
load_photo(path) -> Photo  # dict: rgb (np.uint8 HxWx3, EXIF-transposed), sha (sha256 of file bytes)[:16], size [w, h],
                           #       exif_orientation, ignore [[x0,y0,x1,y1], …] watermark/timestamp bands,
                           #       quality {blur, brightness, glare, score 0..1, issues [str]}

# vision/ocr.py
Token = {"text": raw, "norm": normalize(raw), "box": [x0,y0,x1,y1], "quad": [[x,y]×4], "conf": 0..1,
         "rot": 0|90|270, "pass": "full"|"tile"|"zoom", "passes": int, "support": [pass ids]}
read_photo(photo, mode="FULL"|"FAST", workers=None) -> list[Token]    # cached by (sha, mode, params) under DATA/cache/ocr
read_region(photo, box, rotations=(0, 90, 270), scale=3.0) -> list[Token]   # targeted zoom (MISSING, agent tool)
engine_info() -> {"engine": "PP-OCRv4 (RapidOCR / ONNX Runtime)", "version": …, "ok": bool, "fallback": "tesseract"|None}

# vision/decode.py
Vocab(vocabulary)                          # indexes exact, confusion-canonical and length buckets
decode(token_or_text, vocab) -> Read       # {"tag": str|None, "method": "exact"|"confusion"|"edit1"|"partial"|None,
                                           #  "raw", "norm", "candidates": [..], "ambiguous": bool, "family": str|None,
                                           #  "tag_like": str|None  (coerced family-shaped string when not in vocab)}
parse_ferrule(text) -> {"raw", "from": {"device", "pin"}, "to": {"device", "pin"}} | None   # A-n/B-m, X-FSW1-3, SPD1-UNPR-L
```
Multi-pass: full image at native resolution; ~900 px tiles, 20 % overlap, upscaled ×2; FULL adds 90°/270° tile passes
(vertical CHARM labels). Merge by IoU + same normalised text (NMS); `passes` counts independent passes that agree. Tokens whose
centre falls in an ignore band are dropped. Thread-pool over tiles (thread-local ONNX sessions, 1 intra-op thread each).
Target ≤ 30 s per 4096×3072 photo on 2 vCPU in FULL (`EAGLE_OCR_MODE`, `EAGLE_OCR_WORKERS`).

## 5. Registration (`vision/register.py`)

```python
register(reads, kb, photo) -> Registration
Registration = {
  "localised": bool, "hint": str|None,                  # hint: ONE line when not localised
  "fits": [{                                            # primary view first; a second view only with ≥ 3 own inliers
     "view": "front", "page": 5, "model": "similarity"|"homography",
     "H": 3x3 drawing(pt) -> photo(px), "Hinv": 3x3,
     "inliers": [{"tag", "photo": [x, y], "drawing": [x, y], "residual_px"}],
     "outliers": [{"tag", "photo": [x, y], "drawing": [x, y], "predicted": [x, y], "residual_px"}],
     "coverage_drawing": [[x, y], …],                   // expanded hull of inliers ∩ photo frame, drawing pt
     "coverage_photo": [[x, y], …],
     "scale_px_per_pt": float, "rms_px": float}],
  "candidates": [{"view", "matches", "inliers"}],
  "in_view": {"PS11": {"view": "front", "predicted": [x, y], "margin_px": d}},   // tags inside a fit's coverage
  "not_in_view": ["…"]
}
project(fit, xy_drawing) -> xy_photo;   unproject(fit, xy_photo) -> xy_drawing
```
Similarity first (RANSAC, ≥ 3 inliers), homography only with ≥ 6 well-spread inliers and a sane condition number.
Outliers are candidate misplaced/mislabelled parts, not noise. < 3 inliers → `localised: false`: positions are not judged,
per-label checks still run on what was read, one re-photo hint.

## 6. Checks (`checks/`, plug-in registry)

```python
from checks import check, CHECKS, Context, finding
@check("LABEL")
class LabelCheck:
    title = "Device label"; question = "Does the label at this device read exactly the drawing tag?"
    def run(self, ctx: Context) -> list[dict]: ...
```
`Context`: `kb, pdf, photo, tokens, reads (decoded, located), ferrules, reg (Registration), in_view, wires|None,
checklist|None, ocr_region(box, rotations, scale) -> tokens, facts: dict, cfg`.

**Finding** (candidate, before consensus):
```jsonc
{ "id": "LBL-PS11", "check": "LABEL", "target": "PS11", "view": "front",
  "expected": "PS11", "found": "PS11",
  "status": "OK" | "CANDIDATE_FAULT" | "UNCERTAIN" | "NOT_IN_VIEW" | "SKIP",
  "strength": "strong" | "weak" | null,          // for CANDIDATE_FAULT
  "box": [x0, y0, x1, y1],                       // photo px: where the item is / should be (proof crop centre)
  "drawing": {"page": 5, "view": "front", "bbox": [..]} | null,
  "conf": 0..1, "rule": "LABEL.read_at_predicted",
  "evidence": ["read 'PS11' ×2 passes (conf 0.97)", "…"],
  "reads": [{"raw", "tag", "conf", "passes", "box", "method"}],
  "question": "Does the white label in this crop read PS11?",   // narrow question for the agent
  "hint": "Re-photo the PS11 label from 30 cm, straight on" | null,
  "root_cause": "MISS-PS11" | null }
```
IDs: `LBL-<tag>`, `UNK-<text>`, `ORD-<view>-<family>-<n>`, `MISS-<tag>`, `FER-<ferrule>`, `COL-<terminal>`.
Rules: only items inside a fit's coverage are judged; a missing item suppresses its label/ferrule items (`SKIP`, `root_cause`);
partial reads at the predicted spot that only one vocabulary tag explains count as support (no REVIEW noise).

| Check | OK | CANDIDATE_FAULT |
|---|---|---|
| LABEL | expected tag read at/near its predicted spot (either of its labels) | tag read far from prediction and not explained by ORDER |
| UNKNOWN_LABEL | — | tag-shaped read (≥ 2 passes or exact) not in the vocabulary, or belonging only to another view while inside coverage |
| ORDER | group order along the drawing axis matches | swap / wrong position, named ("CB13 ↔ CB14 swapped") |
| MISSING | read after a targeted zoom re-read | predicted well inside coverage, nothing read even after zoom (device or label missing: agent decides) |
| FERRULE | both devices in vocabulary, one end near the ferrule, link in drawing (when extracted) | unknown device / neither end nearby / link contradicts drawing |
| COLOUR | only with a wire list (legacy logic) | — |

## 7. Agent (`agent/`)

Anthropic Python SDK, manual tool-use loop, strict tool schemas, Pydantic-validated decisions.
* Env: `ANTHROPIC_API_KEY`, `EAGLE_AGENT_ENABLED` (default on when credentials exist), `EAGLE_AGENT_MODEL`
  (default `auto` → `claude-fable-5-1` if the key can use it, else `claude-opus-5-5`), `EAGLE_AGENT_FAST_MODEL`
  (default `claude-opus-5-5`, bulk per-finding verification), `EAGLE_AGENT_MAX_CALLS` (25 per photo), `EAGLE_AGENT_TIMEOUT`
  (60 s), `EAGLE_AGENT_BACKEND` (`anthropic`|`replay`|`mock`), `EAGLE_AGENT_REPLAY` (recorded decisions JSON).
* Tools (deterministic Python): `get_expected_items(view, region?)`, `zoom(region_xyxy, scale)` (image), `ocr_region(region_xyxy,
  rotations)`, `project_tag(tag)`, `drawing_crop(tag)` (image), `record_decision(finding_id, verdict, confidence, reason,
  evidence_boxes, rephoto_hint)` — the only output channel. Verdicts: `CONFIRMED_OK | CONFIRMED_FAULT | UNCLEAR`.
* Loop per photo: overview call (downscaled photo + in-view expected tags + candidates, cached prefix) → per-candidate calls in
  parallel (zoom crop + drawing crop + OCR reads + narrow question) → summary. Hard caps on calls/tokens; unclear or
  disagreeing fast-model answers may escalate once to the main model.
* API: `status() -> {"enabled", "backend", "model", "fast_model", "reason"}`;
  `verify(findings, ctx, run_dir=None) -> {"decisions": {finding_id: Decision}, "calls", "usage", "cost_usd", "summary"}`.
  `Decision = {"finding_id", "verdict", "confidence", "reason", "evidence_boxes", "rephoto_hint", "model", "cached"}`.
* Cache by (photo sha, finding id, crop sha) under `DATA/cache/agent`; transcript `agent_transcript.jsonl` in the run folder
  (text + image hashes only, keys redacted). Only crops and a downscaled photo leave the machine; never the whole PDF.

## 8. Consensus (`consensus.py`)

| Deterministic | Agent | Final |
|---|---|---|
| CANDIDATE_FAULT strong | CONFIRMED_FAULT | **FAIL** |
| CANDIDATE_FAULT weak | CONFIRMED_FAULT (confidence ≥ 0.85) | **FAIL**, else REVIEW |
| CANDIDATE_FAULT | CONFIRMED_OK | PASS (note "agent overturned") |
| CANDIDATE_FAULT | UNCLEAR / agent off | REVIEW + specific re-photo hint |
| UNCERTAIN | CONFIRMED_OK | PASS (agent-read) |
| UNCERTAIN | other / off | REVIEW + hint |
| OK | not asked | PASS |
| NOT_IN_VIEW / SKIP | — | NOT_IN_VIEW / SKIP |

`decide(findings, decisions, agent_on) -> results`; `merge_photos(reports) -> cabinet summary` (per tag: best evidence wins;
FAIL vs PASS across photos → REVIEW unless the agent re-check resolves it); `coverage = verified tags / tags on the GA views`.

## 9. Report item (what the console, PDF and checklist read)

Legacy-compatible: `id, check, target, expected, found, result, box, conf, evidence` plus `marker`, `recheck`, `root_cause`.
For real runs `box` is `[x, y, w, h]` in **photo pixels** and the report carries `H = diag(R, R, 1)` (R = inspector.R), so
`report.to_photo(box, H)` returns the box corners unchanged and every legacy renderer works. Added fields:
`result` may be `NOT_IN_VIEW`; `view`, `drawing`, `hint`, `rule`, `reads`, `strength`,
`agent: {decision, confidence, reason, model, cached, crops}`, `verified_by: ["OCR", "geometry", "Claude"]`.
Report top level adds `engine: "real"`, `coverage {in_view, verified, total, by_view}`, `views`, `kb {cabinet, sha, version}`,
`agent {enabled, backend, model, calls, cost_usd}`, `ocr {engine, tokens, seconds}`, `quality`.

## 10. Pipeline + API

`pipeline.inspect_real(photo_paths, ga_pdf, wires=None, checklist=None, enabled=None, on_event=None, agent=None,
run_dir=None) -> list[(rep, ctx)]` emits stage events `kb, ocr, register, checks, agent, consensus, report` (`start`/`done`,
`t` seconds, stats). `service.run_inspection` routes: legacy engine when the GA is the single-page demo format with a wire list,
real engine otherwise (`engine=auto|legacy|real` override). `/api/v2/inspect` accepts several `photos`, streams one run per
photo plus a `session` summary (coverage across photos). A QC checklist is generated from the KB when none is supplied.
