# EAGLE EYE · engine and console

Drawing-anchored control-cabinet QC. Photo + GA drawing + wire list in → filled QC checklist, marked-up photo, expected-vs-found proof and a PDF report out. Overview and screenshots: [../README.md](../README.md).

## Core idea

Don't ask AI "what's wrong in this photo?". Parse the GA drawing (vector PDF) and the wire list into an exact list of expected items, register the photo to the drawing, then answer one narrow question per item at a known location. FAIL only when evidence agrees; otherwise REVIEW (re-photo).

## Commands

```bash
pip install -r requirements.txt      # plus the tesseract binary
python server.py                     # web console on http://127.0.0.1:8000  (--port, --host, --no-browser)
streamlit run app.py                 # Streamlit UI, same engine and run store
python demo.py                       # CLI: inspect -> fix -> re-photo -> re-check, writes out/demo/
python inspector.py <photo.jpg>      # inspect one photo against the demo drawing set
python eval_forge.py 50 200          # Fault Forge self-test: 50 held-out cabinets (seeds 200-249)
python eval_forge.py --summarize     # recompute out/forge/summary.json from results.json
python make_samples.py               # regenerate sample_photos/ + ANSWER_KEY.txt + manifest.json
python spec.py                       # regenerate the demo inputs/ (GA PDF, wire list, checklist)
python -m pytest tests -q            # engine regression, robustness guards, OCR parity, service, REST + cloud API
python export_static.py              # re-record the hosted console's replay runs (web/static-public/demo)
```

| Environment variable | Default | Meaning |
|---|---|---|
| `TESSERACT_CMD` | auto | Path to `tesseract(.exe)`. Otherwise PATH, then the default Windows/Homebrew install folders are searched. |
| `EAGLE_EYE_WORKERS` | CPU cores (2-8) | Parallel OCR lanes. |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Console bind address (Docker uses `0.0.0.0`). |
| `EAGLE_EYE_DATA` | `out/` | Where runs and caches are written (containers: `/tmp/eagle_eye`). |
| `EAGLE_EYE_OCR` | in-process | `cli` forces the tesseract subprocess instead of libtesseract's C API. |
| `TESSERACT_LIB` | auto | Path to `libtesseract` if it is not found automatically. |
| `EAGLE_EYE_CLOUD` | off | `1` = hosted engine container: `/` redirects to the console, `/api/v2` serves it. |

## Pipeline

| Stage | Where | What happens |
|---|---|---|
| 1 Parse | `inspector.parse_ga` | Vector rectangles + words from the GA PDF → devices (tag, type, box, label box), terminals, breaker rails, backplate size and cabinet ID. Cached by file. |
| 2 Register | `inspector.register` | Backplate quad from the photo (coarse homography), then every device label and ferrule read with certainty (closed-vocabulary OCR) becomes an anchor; RANSAC refines the fit. Off-pattern anchors are reported. Weak fits retry 180°/90°/270° (upside-down phone photos). |
| 3 Checks | `@check` classes | `GA` part present (occupancy vs an illumination-aware empty-backplate model + label evidence) · `ORDER` swap-aware rail sequence · `LABEL` tag OCR + voting · `FERRULE` sleeve present + wire-list-constrained OCR · `COLOUR` wire colour after white-balancing on the labels. |
| 4 Consensus | inside each check | FAIL needs agreeing evidence; disagreement is REVIEW. A label whose part is missing is SKIP (root cause reported once). If fewer than 40% of anchors match, the photo probably isn't this cabinet: every would-be FAIL becomes REVIEW (registration guard). Zone guards: when half a terminal strip's sleeves or half a zone's labels come back absent at once, the zone photo is suspect and those absence FAILs become REVIEW. |
| 5 Report | `report.py`, `pdf_report.py` | Numbered boxes on the photo, expected/found/aligned crops, the QC checklist template filled in (plus a Summary sheet), a PDF report, JSON. |
| 6 Re-check | `report.recheck` | Against the previous run: CLOSED (fixed), OPEN (still failing), REGRESSION (was PASS, now FAIL), NEW (newly revealed). Items keep their marker numbers. |

OCR runs in-process through libtesseract's C API (`ocr_capi.py`, one engine per OCR thread) instead of starting a tesseract process per crop: identical text on all 1,668 crops of the parity test, identical self-test, **~0.9 s per cabinet on 4 cores** (was ~4 s) and ~2 s on a single vCPU. It falls back to the CLI automatically when the library is not found.

### Precision under bad photos

The Robustness Lab (and `tests/test_robustness.py`) degrades photos with tilt, keystone, dim light, blur, noise, colour cast, glare and JPEG compression. Four evidence rules keep a bad photo from producing a false FAIL; each was measured on the 50-cabinet self-test (unchanged: 87/87, 0 false alarms) and on 115 degraded photos (false FAILs 22 → 0 on the first 90; 0 on 25 more from the browser stress sweep):

- *Wrong label* needs an agreeing reading shaped like a complete tag (`PS17` for `PS11`), not a fragment (`43`, `J`).
- *No label* is not proven when OCR reads a piece of the expected tag (`B43` at `CB43`): the label is there, just unclear → REVIEW.
- *Missing part* needs occupancy below 35 % (planted missing parts read ≤ 28 %, installed parts ≥ 41 %); 35–60 % without a label is REVIEW.
- *Black vs a dark colour* on a dim wire is REVIEW; *no ferrule* with some sleeve pixels gets a closer OCR look; zone guards (above).

## Adding a check

One class in `inspector.py`; it appears in the checklist, the PDF, the toggles and the Engine page automatically.

```python
@check("EARTH")
class EarthCheck:
    """Earth bar has a conductor on every stud the drawing shows."""
    title = "Earth studs"
    question = "Is every earth stud the drawing shows connected?"

    def run(self, ctx):          # ctx.ga, ctx.rect (photo warped onto the drawing, 4 px/mm), ctx.bpm, ctx.present ...
        out = []
        for d in ctx.ga["devices"]:
            if d["type"] != "earth":
                continue
            occ = occupancy(ctx.rect, ctx.bpm, d["box"])
            r = "PASS" if occ > 0.6 else "REVIEW"            # unsure -> REVIEW, never a guessed FAIL
            out.append(res(f"EARTH-{d['tag']}", "EARTH", d["tag"], "Connected", f"occupancy {occ:.0%}", r, d["box"], occ, []))
        return out
```

Add the item IDs to the QC checklist template if Emerson's sheet should carry them.

## Run store

Every inspection is stored in `out/runs/<run_id>/` (git-ignored): `photo.jpg`, `report.json`, `marked.jpg`, `rectified.jpg`, `ga_overlay.png`, `QC_Checklist_FILLED.xlsx`, `EAGLE_EYE_QC_Report.pdf`, `crops/`, `meta.json`. A re-check run points at its parent; `root` + `version` give the chain v1 → v2 → v3. Clear it from the History page or with `DELETE /api/runs`.

## REST API

Interactive docs at `/docs` while the server runs. `/api` is the local console API (runs stored on this machine); `/api/v2` is the stateless cloud API.

| Method | Path | |
|---|---|---|
| `POST` | `/api/inspect` | multipart: `photo` file or `sample` id; optional `ga`, `wires`, `checklist` files; `checks` CSV; `parent` run id for a re-check → job |
| `GET` | `/api/jobs/{id}?since=n` | status + live stage events, then `run_id` |
| `GET` | `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/chain` | history, one run (items with box in mm and quad in photo px, drawing layout, anchors), its re-check chain |
| `GET` | `/api/runs/{id}/files/{photo,marked,rectified,overlay,pdf,checklist,json}` | artefacts (`?download=1`, `?w=` thumbnails) |
| `GET` | `/api/runs/{id}/items/{item}/{expected,found,aligned}` | proof crops |
| `POST` | `/api/forge` | `{faults, strength, seed, count}`: forge unseen cabinets with hidden faults, inspect, score |
| `GET` | `/api/forge/live`, `/api/forge/selftest` | live tally, saved self-test |
| `GET` | `/api/health`, `/api/checks`, `/api/samples`, `/api/inputs` | status and catalogues |
| `POST` | `/api/runs/{id}/review` | `{item, decision: PASS/FAIL/CLEAR, note, by}`: inspector decision, kept in `meta.reviews` with a timestamp |
| `POST` | `/api/v2/inspect` | same inputs as `/api/inspect` plus `parent` = JSON file `{meta, report}`; streams NDJSON: `event` lines, then one `result` with payload, report and every artefact (base64), nothing stored |
| `POST` | `/api/v2/forge` | `{faults, strength, seed}`: one unseen cabinet, streamed the same way |
| `GET` | `/api/v2/health`, `/api/v2/diag/samples?ids=`, `/api/v2/diag/forge?start=&n=` | health and parity checks against the local engine |

## Hosted console and cloud engine

- **Console** (`web/`, `npm run build:static`, Vercel project root `eagle_eye/web`): the same React app. It talks to the engine at `VITE_ENGINE_URL` (`.env.static`), keeps every run in the browser (IndexedDB) and falls back to the recorded runs in `static-public/demo` when the engine is unreachable or the viewer picks *Instant replay*.
- **Engine** (`Dockerfile.vercel`, Vercel container project root `eagle_eye`): Ubuntu 24.04 (Tesseract 5.3.4, the version the recorded runs and the self-test used), pinned `requirements-engine.txt`, `EAGLE_EYE_CLOUD=1`. Stateless, so any instance serves any request. Run it anywhere: `docker build -f Dockerfile.vercel -t eagle-eye-engine . && docker run -p 8080:8080 -e PORT=8080 eagle-eye-engine`.

## Web console development

```bash
cd web && npm install
npm run dev        # http://localhost:5173, proxies /api to python server.py on :8000
npm run build      # type-check + build into web/dist (committed, served by server.py)
```

React 18 + TypeScript + Vite, framer-motion, lucide icons; fonts are bundled so the console works offline.

## Self-test (synthetic cabinets, held-out seeds 200–249)

87/87 planted faults caught · 0 false alarms over 1,950 correct items · 6 items (0.3%) sent to REVIEW · 14/14 clean cabinets with zero FAIL · ~0.9 s per cabinet on a 4-core CPU. These are generated cabinets; real Emerson photos will be harder. The finale plan swaps in YOLO11 + PaddleOCR and re-runs this harness on Emerson's real samples.

## Tools declared

Python, OpenCV, PyMuPDF, Tesseract OCR, NumPy, openpyxl, ReportLab, FastAPI, React, Streamlit. AI coding assistant used during development. Bundled fonts: DejaVu (license in `assets/fonts/`).
