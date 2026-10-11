# EAGLE EYE — Team ENIGMA (VIT Code_Apex 3.0, Track 1 · Emerson)

Drawing-anchored control-cabinet QC. Photo + GA drawing + wire list in → filled QC checklist, marked-up photo and expected-vs-found snippets out.

## Core idea
Don't ask AI "what's wrong in this photo?". Parse the GA drawing (vector PDF) and wire list into an exact list of expected items, register the photo to the drawing, then answer narrow questions per item at a known location. FAIL only when evidence agrees; otherwise REVIEW (re-photo).

## Files
| File | What it does |
|---|---|
| `spec.py` | Generates the synthetic test cabinet inputs (GA PDF, wire list, QC checklist) copying Emerson's example layout |
| `render.py` | Photo renderer + **Fault Forge** (plants faults, adds camera angle / light / colour cast / blur / noise / JPEG) |
| `inspector.py` | Engine: GA parser, backplate + label/ferrule-anchored registration (RANSAC), plug-in checks (GA, ORDER, LABEL, FERRULE, COLOUR), consensus, root-cause skip |
| `report.py` | Marked-up photo, snippets, filled Excel checklist, re-check (CLOSED / OPEN / REGRESSION), history |
| `demo.py` | End-to-end demo: inspect → fix → re-photo → re-check |
| `eval_forge.py` | Self-test: `python3 eval_forge.py 50 200` (50 held-out cabinets, seeds 200–249) |
| `app.py` | Streamlit UI: `streamlit run app.py` |

## Setup
```
pip install pymupdf pytesseract opencv-python-headless reportlab openpyxl streamlit pandas
# plus the tesseract binary (apt install tesseract-ocr / brew install tesseract)
python3 spec.py && python3 demo.py
```

## Self-test result (synthetic cabinets, held-out seeds 200–249)
87/87 planted faults caught · 0 false alarms over 1,950 correct items · 6 items (0.3%) sent to REVIEW · ~23 s per cabinet on a 2-core CPU.
These are generated cabinets; real Emerson photos will be harder. The finale plan swaps in YOLO11 + PaddleOCR and re-runs this harness on Emerson's real samples.

## Tools declared
Python, OpenCV, PyMuPDF, Tesseract OCR, NumPy, openpyxl, ReportLab, Streamlit. AI coding assistant used during development.
