# Round 2 run-sheet (presenter: Arnav)

Five minutes, one browser window, every claim shown live. The console's pages follow the jury flow: **Overview → Inspect → Fault Forge**.

## 30 minutes before the slot

1. Start the console: double-click `eagle_eye\run.bat` (first run installs everything, ~5 min). It opens http://127.0.0.1:8000.
2. Check the top-right pill says **Engine ready**. If it says *Tesseract missing*, install the UB-Mannheim build and restart.
3. Press **Run the live demo** once so the first live run is warm, then **History → Clear** for a clean slate (or keep that run as a backup).
4. Browser full screen (F11), zoom 100%. Close heavy apps: OCR uses every core.
5. Backups open in other tabs: a screen recording of a good run, one downloaded PDF report, and `streamlit run app.py` in case the console fails.

## The five minutes

| Time | Show | Click | Say |
|---|---|---|---|
| 0:00–0:30 | **Problem** | Overview, scroll to *The problem* | "A control cabinet has hundreds of parts, labels and wire sleeves. Today an inspector checks it by eye against the drawing. Emerson's definition of done: find the faults, **no false alarms**, proof for every FAIL, a working re-check, and it must work on a cabinet it has never seen." |
| 0:30–1:30 | **Our idea** | Scroll to *Ask a vision model vs EAGLE EYE*, then *Six ideas* | "Most teams will send the photo to a vision model. It invents faults, which breaks the no-false-alarm rule. We read the drawing with code, line the photo up using the labels as anchors, and ask one narrow yes/no question per item. A FAIL needs agreeing evidence; anything unclear goes to REVIEW." |
| 1:30–3:30 | **Live demo** | **Run the live demo** | While the pipeline fills in: "Parse the drawing, register the photo with 16 anchors, run the five plug-in checks." |
| | 4 FAIL with proof | Click issue **#2 ORD-RAIL-1** | "Expected from the drawing on the left, found in the photo on the right. Read along the rail: CB43 and CB44 are swapped, exactly how Emerson's own sheet words it." |
| | Registration | Toggle **Drawing** + **Anchors** | "This is the drawing laid onto the photo. Green anchors fit; the two red ones are the swapped breakers: anchors that don't fit point to misplaced parts." |
| | Root cause | Point at **1 SKIP** | "PS12 is missing, so its label check is skipped: one fault, one FAIL, not five." |
| | Report | **PDF report** (opens/downloads) | "The tool fills Emerson's Excel checklist and writes this PDF end to end." |
| | Re-check | **Re-check** → sample **05** | "The technician fixed three things. New photo: 3 CLOSED, 1 OPEN, history kept." Drag the before/after slider. |
| 3:30–4:30 | **Proof** | **Fault Forge → Forge & inspect** | "A cabinet nobody has seen, random faults, random camera angle and light." Ask the jury to guess, then **Reveal**. Scroll to the self-test: "87 of 87 planted faults, zero false alarms over 1,950 correct items, about 4 seconds per cabinet on a laptop CPU. These are generated cabinets; we say that plainly." |
| 4:30–5:00 | **Finale plan** | Overview → *What we build next* | "With Emerson's real data in the 24 hours: adapt the parser to their drawings, fine-tune a YOLO11 detector and PaddleOCR on their photos, then re-run this exact self-test on real cabinets." |

## Likely questions

| Question | Answer |
|---|---|
| Why not just use GPT-4V / Gemini? | It invents faults, and Emerson requires zero false alarms. We use the drawing as ground truth and only ask narrow yes/no questions. Same photo, same report, every time. |
| Will it work on real photos? | Not proven yet: our numbers are synthetic. At the finale we fine-tune the detector on Emerson's samples and re-run the same self-test. |
| Blurry photo or unreadable label? | The item goes to REVIEW with "re-photo this zone", never a guessed FAIL. |
| What if someone uploads the wrong cabinet, or the photo is upside down? | Upside down or sideways: it re-registers in the right orientation automatically. Wrong cabinet: too few labels match the drawing, so nothing is called FAIL and the whole photo goes to REVIEW. |
| A cabinet you've never seen? | No per-cabinet training. The cabinet's GA PDF defines what to expect. Fault Forge shows it live. |
| How do you add new checks? | One plug-in class with `@check("NAME")` in `inspector.py`. Show the **Engine** page. |
| How fast is it? | About 4 seconds per cabinet on a 4-core laptop CPU: OCR runs in parallel, no GPU, no cloud. |
| Which AI tools did you use? | Tesseract OCR, OpenCV, PyMuPDF; an AI coding assistant helped write code (declared, as the rules ask). |

## If something breaks

- **Inspection error toast**: press **Run the live demo** again (sample photos always work).
- **Console won't start / port busy**: the message says which port; run `python server.py --port 8001`.
- **Browser issue**: `streamlit run app.py` gives the same engine, same re-check, same PDF.
- **Laptop issue**: play the screen recording and walk through the downloaded PDF.
