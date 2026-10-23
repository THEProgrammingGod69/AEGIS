"""Shared paths and runtime configuration.

Every module resolves files relative to this folder, so the tools work no matter which directory they
are launched from (``streamlit run eagle_eye/app.py`` from the repo root, ``python server.py`` from
inside ``eagle_eye``, Streamlit Cloud, Docker ...).
"""
import os
import shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent
INPUTS = BASE / "inputs"
OUT = BASE / "out"                       # shipped results (demo outputs, Fault Forge self-test)
# Where runs and caches are written. Containers (Vercel, Docker) only allow writes under /tmp.
DATA = Path(os.environ.get("EAGLE_EYE_DATA") or OUT)
RUNS = DATA / "runs"
SAMPLES = BASE / "sample_photos"
FONTS = BASE / "assets" / "fonts"
WEB_DIST = BASE / "web" / "dist"

DEMO_GA = INPUTS / "GA_EE-DEMO-01.pdf"
DEMO_WIRES = INPUTS / "WireList_EE-DEMO-01.xlsx"
DEMO_CHECKLIST = INPUTS / "QC_Checklist_EE-DEMO-01.xlsx"
DEMO_PHOTO = OUT / "demo" / "photo_v1.jpg"

VERSION = "3.0.0"

# One tesseract process per core is the sweet spot; each process is kept single-threaded so that
# parallel OCR calls do not fight each other for cores (Tesseract's own OpenMP threads oversubscribe).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
WORKERS = max(2, min(8, int(os.environ.get("EAGLE_EYE_WORKERS", os.cpu_count() or 2))))


def font(name="DejaVuSans-Bold.ttf"):
    """Path of a bundled font (identical glyphs on Windows, macOS and Linux)."""
    p = FONTS / name
    if p.exists():
        return str(p)
    for d in ("/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts"):
        q = Path(d) / name
        if q.exists():
            return str(q)
    return str(p)


def find_tesseract():
    """Locate the tesseract binary: $TESSERACT_CMD, PATH, then the default install folders."""
    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
    ]
    return next((c for c in candidates if Path(c).exists()), None)


for _d in (DATA, RUNS):
    _d.mkdir(parents=True, exist_ok=True)
