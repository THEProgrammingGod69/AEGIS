# Deploying EAGLE EYE

Two pieces:

| Piece | Where | Why |
|---|---|---|
| **Console** (`eagle_eye/web`, React) | Vercel (`eagle-eye-enigma.vercel.app`), static build | Fast, free, keeps the recorded-replay fallback so the demo never dies |
| **Engine** (`eagle_eye/Dockerfile.engine`, FastAPI + PP-OCRv4 + Claude agent) | Google Cloud Run / Render / Fly.io / Railway (2 vCPU, 2-4 GB, request timeout ≥ 300 s, min instances 1 for the demo) | A real photo takes 20-60 s of CPU: too long and too large for Vercel serverless functions |

The console talks to the engine at `VITE_ENGINE_URL` (`eagle_eye/web/.env.static`). Secrets live only in the engine's
environment; nothing secret is ever shipped to the browser.

## Engine environment

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | Listen port (Cloud Run / Render set it) |
| `EAGLE_EYE_CLOUD` | `1` in the image | `1` = stateless `/api/v2` only (hosted console); `0` = also serve the console (on-prem) |
| `EAGLE_EYE_DATA` | `/tmp/eagle_eye` | Writable run store and caches (KB, OCR, agent) |
| `EAGLE_EYE_REAL_DATA` | `/app/data/emerson` | Folder with a real drawing set + photos for the "Emerson 13GE03331" preset (mounted, never baked) |
| `EAGLE_CORS_ORIGINS` | console URL + localhost | Comma-separated allowed origins |
| `EAGLE_OCR_MODE` / `EAGLE_OCR_WORKERS` | `FULL` / `2` | OCR passes and parallel lanes (match the vCPUs) |
| `ANTHROPIC_API_KEY` | unset | Enables the Claude vision agent. Unset = deterministic engine only (uncertain items go to REVIEW) |
| `EAGLE_AGENT_ENABLED` | `1` | `0` switches the agent off even with a key |
| `EAGLE_AGENT_MODEL` | `auto` | Main model: `claude-fable-5-1` when the key can use it, else `claude-opus-5-5` |
| `EAGLE_AGENT_FAST_MODEL` | `claude-opus-5-5` | Per-finding verification model |
| `EAGLE_AGENT_MAX_CALLS` | `25` | API requests per photo (hard cap) |
| `EAGLE_AGENT_TIMEOUT` | `60` | Seconds per API request |
| `EAGLE_FAIL_WITHOUT_AGENT` | `0` | `1` lets a *strong* deterministic candidate FAIL when the agent is off (on-prem, no-cloud mode) |
| `EAGLE_MAX_PHOTO_MB` / `EAGLE_MAX_PDF_MB` | `25` / `30` | Upload limits |
| `EAGLE_RATE_PER_MIN` | `6` | Inspections per client IP per minute |

## Google Cloud Run

```bash
IMG="$REGION-docker.pkg.dev/$PROJECT/eagle/engine:finale"
gcloud builds submit eagle_eye --config eagle_eye/cloudbuild.yaml --substitutions _IMAGE="$IMG"
printf '%s' "$ANTHROPIC_API_KEY" | gcloud secrets create anthropic-api-key --data-file=-
gcloud run deploy eagle-eye-engine --image "$IMG" --region "$REGION" \
  --cpu 2 --memory 4Gi --timeout 300 --min-instances 1 --max-instances 3 --concurrency 2 --allow-unauthenticated \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest \
  --set-env-vars EAGLE_CORS_ORIGINS=https://eagle-eye-enigma.vercel.app,EAGLE_OCR_WORKERS=2
# optional: the real drawing set from a private bucket, mounted read-only
gcloud run services update eagle-eye-engine --region "$REGION" \
  --add-volume name=emerson,type=cloud-storage,bucket="$PRIVATE_BUCKET",readonly=true \
  --add-volume-mount volume=emerson,mount-path=/app/data/emerson
```

## Render / Fly.io / Railway

* **Render**: `render.yaml` at the repository root is a ready Blueprint (Docker runtime, 2 vCPU plan, health check, optional
  disk for the real data). Set `ANTHROPIC_API_KEY` in the dashboard.
* **Fly.io**: `fly launch --dockerfile eagle_eye/Dockerfile.engine` from `eagle_eye/`, then `fly scale vm shared-cpu-2x
  --memory 4096`, `fly secrets set ANTHROPIC_API_KEY=...`, optional `fly volumes create emerson` mounted at `/app/data/emerson`.
* **Railway**: new service from the repo, root directory `eagle_eye`, Dockerfile path `Dockerfile.engine`, variables as above.

## Console on Vercel

Project root `eagle_eye/web` (already configured by `vercel.json`). Set `VITE_ENGINE_URL` to the engine URL in
`eagle_eye/web/.env.static` (or as a Vercel environment variable) and redeploy. When the engine cannot be reached the console
falls back to the recorded demo runs automatically.

## On-prem / local ("drawings never leave the plant")

```bash
docker compose up --build          # console + engine on http://localhost:8000, data/emerson mounted read-only
```

Leave `ANTHROPIC_API_KEY` empty to keep every byte on site (deterministic engine; anything uncertain becomes REVIEW with a
re-photo hint), or set `ANTHROPIC_BASE_URL` to an approved gateway. Only cropped regions and a downscaled photo are ever sent to
the agent; the drawing PDF never leaves the machine unless a GA page is a raster scan and the VLM fallback is enabled.

Without Docker: `cd eagle_eye && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt` (plus
`pip install --no-deps rapidocr-onnxruntime==1.4.4`), then `python server.py`.

## Smoke test

```bash
curl -s "$ENGINE/api/v2/health" | python -m json.tool      # ocr.ok, agent.enabled, kb cache, version
```
Then open the console, pick the "Emerson 13GE03331" preset (or upload the PDF + photos), and check the live stages, the
coverage bar, proof crops with agent reasons, the PDF report, the filled checklist and the work order.
