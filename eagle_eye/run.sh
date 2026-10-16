#!/usr/bin/env bash
# EAGLE EYE one-click launcher for macOS / Linux:  ./run.sh
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.10+ is required"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
python -c "import fastapi, cv2, pymupdf, pytesseract, reportlab" 2>/dev/null || pip install -r requirements.txt
command -v tesseract >/dev/null || echo "WARNING: Tesseract OCR not found (brew install tesseract / sudo apt install tesseract-ocr)"
exec python server.py "$@"
