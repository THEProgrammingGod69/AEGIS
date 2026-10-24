@echo off
REM EAGLE EYE one-click launcher for Windows: double-click this file.
cd /d "%~dp0"
set "EAGLE_PYTHON=python"
py -3.12 -c "import sys" >nul 2>nul && set "EAGLE_PYTHON=py -3.12"
%EAGLE_PYTHON% -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,13)" >nul 2>nul || (
  echo Python 3.11 through 3.12 is required. Install Python 3.12 from https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist .venv (
  echo Creating virtual environment...
  %EAGLE_PYTHON% -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -c "import sys; assert (3,11) <= sys.version_info[:2] < (3,13)" >nul 2>nul || (
  echo This .venv uses an unsupported Python. Rename it and rerun with Python 3.12 installed.
  pause
  exit /b 1
)
python -c "import fastapi, cv2, pymupdf, pytesseract, reportlab, rapidocr_onnxruntime" 2>nul || (
  echo Installing dependencies, this takes a few minutes the first time...
  python -m pip install --upgrade pip >nul
  python -m pip install -r requirements-engine.txt || (pause & exit /b 1)
  pip install --no-deps rapidocr-onnxruntime==1.4.4 || (pause & exit /b 1)
)
if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
  where tesseract >nul 2>nul || echo WARNING: Tesseract OCR not found. Install it from https://github.com/UB-Mannheim/tesseract/wiki
)
python server.py %*
pause
