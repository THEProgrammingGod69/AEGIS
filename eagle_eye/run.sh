#!/usr/bin/env bash
# EAGLE EYE one-click launcher for macOS / Linux:  ./run.sh
set -e
cd "$(dirname "$0")"
EAGLE_PYTHON=python3
command -v python3.12 >/dev/null && EAGLE_PYTHON=python3.12
"$EAGLE_PYTHON" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,13)' 2>/dev/null || {
  echo "Python 3.11 through 3.12 is required. Install Python 3.12 and rerun."; exit 1;
}
[ -d .venv ] || "$EAGLE_PYTHON" -m venv .venv
. .venv/bin/activate
python -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,13)' 2>/dev/null || {
  echo "This .venv uses an unsupported Python. Rename it and rerun with Python 3.12 installed."; exit 1;
}
python -c "import fastapi, cv2, pymupdf, pytesseract, reportlab, rapidocr_onnxruntime" 2>/dev/null || {
  python -m pip install -r requirements-engine.txt && python -m pip install --no-deps rapidocr-onnxruntime==1.4.4
}
command -v tesseract >/dev/null || echo "WARNING: Tesseract OCR not found (brew install tesseract / sudo apt install tesseract-ocr)"
exec python server.py "$@"
