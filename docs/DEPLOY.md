# Running and deploying EAGLE EYE

The React console sends inspection requests to your own FastAPI engine. OCR models load once in that server process;
the browser does not download a language model. Drawing parsing, OCR, alignment and evidence checks run on CPU.
Hosted AI inference is disabled in code, even if old API credentials remain in the environment. No AI API key is required.
The optional private preset store is storage, not an inference service; use a local folder for a fully on-prem setup.

## Local deployment

From the repository root:

```bash
docker compose up --build
```

Open `http://localhost:8000`. The compose service mounts private cabinet files from `data/emerson/` read-only and
persists run metadata in a Docker volume. Keep the supplied photos and drawing PDFs out of Git.
Install/build dependencies before an offline demo; dependency installation uses package repositories.

Without Docker, install **Python 3.11–3.12 (3.12 recommended)** and Tesseract OCR, then use `eagle_eye/run.bat`
on Windows or `./eagle_eye/run.sh` on macOS/Linux. The pinned RapidOCR dependency does not support Python 3.13.
The launcher creates a virtual environment and installs dependencies. A manual engine setup is:

```bash
cd eagle_eye
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements-engine.txt
python -m pip install --no-deps rapidocr-onnxruntime==1.4.4
python server.py --host 127.0.0.1 --port 8000
```

On Windows, the normal Tesseract install location is detected. For a portable installation, set `TESSERACT_CMD`
to the absolute path of `tesseract.exe`. Tesseract must include its English language data and runtime libraries.
An NVIDIA GPU is not required. Real, full-resolution phone photos cost more CPU time than the synthetic demo;
measure latency on the hardware and photo sizes you will actually demonstrate.

## Real inputs and inspection decisions

In **Inspect → Real cabinet**, upload a photo and the **matching vector GA PDF**, or choose the real preset.
An uploaded photo takes precedence over a preset's sample photo. A real upload without its drawing is rejected;
the synthetic demo drawing is only used in explicit demo mode. A scanned or unfamiliar drawing format may require
parser work; an LLM is not used to invent its structure.

Place the matching private PDF and photos in `data/emerson/` to enable the local real preset. Having photos alone
does not provide enough information to verify drawing compliance. Do not substitute the synthetic demo PDF.

If the engine cannot align the photo with the drawing, it reports one registration REVIEW and suppresses spatial
PASS/FAIL judgments. Unreadable labels need human review or a closer photo. Components outside the captured area
are NOT IN VIEW. Required views and checks must be covered before the report can allow approval. A REVIEW is a
referral, not a confirmed defect and not evidence that a cabinet is safe to ship.

## Hosted console and your engine

The static console builds from `eagle_eye/web` with `npm ci && npm run build:static`. Set `VITE_ENGINE_URL` to your
engine URL before building. Its clearly labelled synthetic replays are for demonstration, not real inspection results.
For an on-prem installation, use the local build (`npm run build`) or the bundled `web/dist` served by FastAPI.

`Dockerfile.engine` builds from `eagle_eye/` for a container host. `render.yaml` defines a Render service;
`Dockerfile.vercel` is the existing hosted engine image. Deploy only after verifying the configured origin, storage
and resource limits. An engine release must accompany the console release: rebuilding only the UI cannot repair
old backend judgments. Existing downloaded reports remain historical records; rerun affected real inspections.

| Variable | Default / purpose |
|---|---|
| `PORT` | `8080` in the engine image; compose uses `8000` |
| `EAGLE_EYE_CLOUD` | `1` serves stateless `/api/v2`; `0` also serves the local console |
| `EAGLE_EYE_DATA` | Writable metadata/cache directory; `/tmp/eagle_eye` in the engine image |
| `EAGLE_EYE_REAL_DATA` | Local private preset folder; `/app/data/emerson` in compose |
| `EAGLE_CORS_ORIGINS` | Allowed console origins, comma-separated |
| `EAGLE_OCR_WORKERS` | `2` in the image; tune to available CPU and memory |
| `EAGLE_OCR_GATE` | Keep `0` for full coverage; `1` can skip small-label tiles |
| `EAGLE_AGENT_ENABLED` | Set to `0`; external inference is also blocked independently in code |
| `EAGLE_FAIL_WITHOUT_AGENT` | `1`: strong, agreeing local evidence can confirm label/order defects; absence stays REVIEW |
| `EAGLE_MAX_PHOTO_MB` / `EAGLE_MAX_PDF_MB` | `25` / `30`; uploads are validated before inspection |
| `EAGLE_RATE_PER_MIN` | `6` inspections per client IP per minute |
| `EAGLE_PRESET_BLOB` | Optional private Vercel Blob preset prefix; requires storage credentials |
| `EAGLE_ADMIN_TOKEN` | Optional preset upload authorization; unset when not in use |

The stateless API reads a photo once, retaining fingerprints, OCR, quality metadata, a bounded preview and proof
crops rather than the original full-resolution upload. JSON responses may contain that preview and proof images.
The console keeps a local preview in IndexedDB. Drawings are cached by content hash. Review the storage policy before
using confidential data on any hosted service. Selecting the local compose deployment keeps inspection processing local.

## Validation and real versus synthetic evaluation

From `eagle_eye/` with the environment activated:

```bash
python -m pip install pytest httpx
python -m pytest tests -q
python eval_forge.py 50 200
python eval_real.py
# Optional: plant controlled defects into private real photos, then evaluate them separately.
python forge_real.py
python eval_real.py --forged
```

Real evaluation requires the private matching drawing, photos and annotated ground truth. It cannot be reproduced
from six unlabelled images alone. Hold out original photos by cabinet/session before making synthetic variations;
crops or augmentations of one original must not appear in both training and evaluation splits.

**Fault Forge → Real vs synthetic** displays the evaluation catalogue. Missing measurements stay “Not measured”.
Older summaries are labelled historical and are not presented as measurements of the current engine.
Confirmed recall counts actual FAILs on known defects. Referral rate counts REVIEW separately; an incorrect PASS
on a known defect is reported separately too. Synthetic performance does not establish real-cabinet accuracy.

For a smoke test, request `/api/v2/health` and verify OCR readiness, disabled external inference and the intended preset.
Then inspect a synthetic sample in demo mode and a real photo with its matching drawing. Check coverage, proof crops,
PDF/checklist export and recheck behavior. The automated suite does not certify zero errors or factory shipping safety.
