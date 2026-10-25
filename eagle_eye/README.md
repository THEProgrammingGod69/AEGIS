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
python calibration.py --reuse        # refit the confidence calibration (out/forge/calibration.json)
python eval_angle.py                 # angle sweep of the real-cabinet registration (out/forge/angle_sweep.json)
python showcase.py                   # add the showcase cases (clean + planted anomalies) to History
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
| `EAGLE_OCR_SMALL_UPSCALE` | `4.0` | Tile magnification of the small-print read (only for photos the regular read could not place). |
| `EAGLE_COLOUR_PROFILE` | none | Wire-colour profile for drawing sets without their own colour legend (`iec-60204-1`, `nfpa-79`, `iec-60445`, `is-732-legacy`, `as-nzs-3000-legacy`; see `wire_profiles.json`). Never a default. |

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

### Wire colour by circuit class (real cabinets)

Colour codes are not universal: black is a phase under IEC 60445 but the neutral in India's legacy scheme, white is the
neutral under NFPA 79, and panel builders add house rules. `wire_rules.py` therefore takes the rule from the cabinet's
own documents and never assumes one: the drawing set's wire-colour legend first (read rotation-aware from any sheet by
`kb/drawing_kb.py`), else a profile chosen for the project (`EAGLE_COLOUR_PROFILE`, `wire_profiles.json`, each naming
the edition to check), else only the universal rule that green-and-yellow is protective earth. A wire's circuit class
(AC, DC, alarm, earth) comes from the drawing's power schematics, never from its colour: pin names seed it (L/N, +/-,
PE, breaker contacts 91-98), it spreads along wires, buses and breaker poles, power supplies and earth points are
boundaries, and conflicting circuits stay unclassified. `vision/wire_colour.py` measures the insulation beside each
ferrule along the sleeve's own axis (OCR's text quadrilateral), white-balanced on the sleeve, and refuses to judge a
colour that does not stand out from its surroundings. Colour findings go to REVIEW, never FAIL on their own.

### Photos taken at an angle (real cabinets)

A photo from the side is not a scaled copy of the drawing. When the flat (similarity) fit leaves read labels
unexplained, `vision/register.py` searches the perspective directly (seeded 4-point RANSAC, sanity-checked) and keeps
it when it explains clearly more labels, or the same labels clearly better. The fitted perspective gives the camera's
viewing angle (reported, with a re-photo warning above 50°) and each label's local scale, so letter sizes follow the
foreshortening. The console lays the drawing on through that perspective and can show the photo straightened. Angle
sweep on GA-drawing renders of the real cabinet (4 views, turned left and right; `python eval_angle.py`):

| Turned | Read labels placed: flat → perspective | Labels verified (PASS) | Angle measured | False FAILs |
|---|---|---|---|---|
| 0° | 117 → 117 of 175 | 268 → 268 | 2.2° | 0 |
| 20° | 231 → 233 of 361 | 536 → 536 | 16.5° | 0 |
| 35° | 173 → 232 of 357 | 507 → 530 | 35.0° | 0 |
| 50° | 130 → 199 of 302 | 413 → 445 | 47.4° | 0 |

### Small labels: drawing-guided reading (real cabinets)

A whole-cabinet photo leaves small labels a few pixels high: the regular OCR passes read them partly or not at all,
which left them REVIEW or NOT_IN_VIEW. `vision/guided.py` uses the drawing the way an inspector leans in: after a first
registration, every label of a placed view that is predicted inside the photo without a certain read is read again in
a window around its predicted spot, magnified so its letters are about 34 px high, at two magnifications, by the same
neural reader (PP-OCRv4). Only an exact read of that label's own tag is taken; at a few pixels per letter, a look-alike
read ('C871' for CB71) is taken only when the recognizer itself rates the drawing's tag at least half as likely as its
own reading and clearly likelier than any neighbouring tag (lexicon-constrained CTC scoring, `vision.ocr.score_texts`),
with both magnifications agreeing. The photo is registered again with the new reads and the next round looks for the
rest; a photo that cannot be placed at all gets one more magnified read of the tiles that hold text. Nothing is
invented: what still cannot be read stays REVIEW or NOT_IN_VIEW, and a missing label is never inferred. Labels of the
photographed view on GA-drawing renders of the real cabinet (4 views, 122 labels per size):

| Photo size (letters) | Verified (PASS) | REVIEW | NOT_IN_VIEW | False FAILs |
|---|---|---|---|---|
| 100 % (12 px) | 121 → 121 | 1 → 1 | 0 → 0 | 0 |
| 60 % (7 px) | 91 → 112 | 23 → 10 | 8 → 0 | 0 |
| 40 % (5 px) | 53 → 62 | 5 → 14 | 64 → 46 | 0 |

Planted faults on the forged renders are unchanged: 12 of 12 flagged, 0 incorrect PASS, 0 false FAIL. At 5 px per
letter B and 8 are genuinely ambiguous to the recognizer, so those labels ask for a closer photo instead of a guess.

### Showcase cases

`python showcase.py` (or History → Load showcase cases) adds saved inspections for a demo: seven on the generated demo
cabinet (a clean cabinet, Emerson's four faults, ferrule and wire colour, wrong label and missing breaker, the re-check
chain, a bad photo, hidden Fault Forge faults) and, where `data/emerson_render/` exists, seven on renders of the real
cabinet (clean, wrong label, swap, removed label, a photo from 35°, small labels, a green-and-yellow wire on an AC
circuit). Each case records what was planted and what to look at, and checks its own outcome. The hosted History leads
with the demo-cabinet cases (`export_static.py`); the real-cabinet cases are never published.

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

React 18 + TypeScript + Vite, GSAP 3.13 (all plugins, free for commercial use) with `@gsap/react`, Lenis (Overview
scroll only), framer-motion for modals and toasts, lucide icons; fonts are bundled so the console works offline.

**Design and motion (UI & Motion Guide v2, "Daylight Signal").** A light theme in Emerson's colours (Emerson Blue type,
Electric Azure actions, an aurora gradient for energy) with dark "device" panels for photo viewers, logs and the
presenter. Tokens live in `src/styles/base.css` (`.device` flips the same names to the dark scope); motion lives in
`src/lib/gsap.ts`, `src/lib/interactions.ts`, `src/lib/transition.ts` and `src/components/motion.tsx`. Highlights: the
eye-open preloader (first visit), the eye-blink route transition, a 3D device running the registration sequence on a
recorded inspection, a pinned exploded inspection, a horizontal pinned pipeline, a draggable X-ray lens, Flip checklist
and Lab migration, swipe review cards, a sign-off stamp with confetti, presenter slides, and a WebGL lightning band.

- **Command bar** (`src/components/TopBar.tsx`, `src/styles/topbar.css`): numbered destinations with viewfinder
  focus brackets that hunt and lock onto the active page, a logo eye that follows the pointer and blinks with each
  route change, a jump field for the Ctrl K palette, an engine signal meter, and a drawing ruler along the bottom edge
  that fills with the aurora as the page scrolls (the reading progress).
- **Page-wide flair** (`src/styles/flair.css`): cards rise in, page heads drift back and KPI tiles catch a sheen as
  they scroll, all with CSS scroll-driven animations (no JavaScript; browsers without them just show the page), an
  ambient glow trails the pointer, primary buttons pull gently towards it, and the footer wordmark fills as the page
  ends.
- **Colour roles**: status colours set `--c` (text), `--cf` (fills, tints, glows) and `--ci` (ink on a fill) together
  through `tone()` in `src/lib/format.ts`, so REVIEW reads in a dark amber but fills bars and markers in the bright one.

- **Calm mode** (Ctrl K → *Motion: Calm*, `?calm`, or the OS reduced-motion setting): every animation shows its final
  frame, nothing pins, the preloader and blink are skipped. Use it if a projector stutters; it is stored per device.
- **Press X** anywhere (outside inputs) for X-ray mode: every photo shows its GA drawing overlay.
- **Install as an app**: on Android open the hosted console in Chrome, then ⋮ → *Install app* (iPhone: Safari → Share →
  *Add to Home Screen*). It opens full-screen from its own icon, with shortcuts to the demo, Review, Analytics and Fault
  Forge on a long press. The hosted build registers `static-public/sw.js`: pages and data stay network-first (a new
  deploy shows at once), build files are cache-first, and whatever has been opened, plus every recorded run's data,
  still opens offline. The local console (`python server.py`) gets the manifest and icons but no service worker.
- Budget: transform / opacity / clip-path / SVG strokes only; ambient loops pause off-screen; cursor, tilt, magnetic,
  spotlight and ambient-glow effects run for mouse and trackpad only; pages other than the Overview load on demand.
  A CSS transition never shares a property with a GSAP tween (it would stall the tween part-way).

## Self-test (synthetic cabinets, held-out seeds 200–249)

87/87 planted faults caught · 0 false alarms over 1,950 correct items · 6 items (0.3%) sent to REVIEW · 14/14 clean cabinets with zero FAIL · ~0.9 s per cabinet on a 4-core CPU. These are generated cabinets; real Emerson photos will be harder. The finale plan swaps in YOLO11 + PaddleOCR and re-runs this harness on Emerson's real samples.

## Tools declared

Python, OpenCV, PyMuPDF, Tesseract OCR, NumPy, openpyxl, ReportLab, FastAPI, React, GSAP, Lenis, Streamlit. AI coding assistant used during development. Bundled fonts: DejaVu (license in `assets/fonts/`).
