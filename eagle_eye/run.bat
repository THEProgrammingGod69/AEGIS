@echo off
REM EAGLE EYE one-click launcher for Windows: double-click this file.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.10+ is not installed. Get it from https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -c "import fastapi, cv2, pymupdf, pytesseract, reportlab, rapidocr_onnxruntime" 2>nul || (
  echo Installing dependencies, this takes a few minutes the first time...
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt || (pause & exit /b 1)
  pip install --no-deps rapidocr-onnxruntime==1.4.4 || (pause & exit /b 1)
)
if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
  where tesseract >nul 2>nul || echo WARNING: Tesseract OCR not found. Install it from https://github.com/UB-Mannheim/tesseract/wiki
)
python server.py %*
pause
