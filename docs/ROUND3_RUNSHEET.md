# Round 3 run-sheet: the full prototype, live

**Link:** https://eagle-eye-enigma.vercel.app · works on any laptop or phone, nothing to install.
The console talks to the real Python engine in the cloud (`eagle-eye-engine.vercel.app`, ~2 s per cabinet). If the engine is ever unreachable it switches to *instant replay* of runs recorded from the same engine, so the demo cannot break.

## 30 minutes before the slot

1. Open the link in Chrome, full screen (F11), zoom 100%. The pill at the top right must say **Live cloud engine** (green). Click it to see the engine details; *Check again* if it says *Waking*.
2. Press **Run the live demo** once (warms the container), then open **History → Clear** for a clean slate. The Review queue keeps three recorded harsh-camera cabinets so it is never empty.
3. Turn on **Presenter mode** (Overview button, or `Ctrl K` → *Start presenter mode*). It shows the script below with talking points; a presentation clicker's **PgDn** goes to the next step *and performs it*.
4. Backups: the local engine (`eagle_eye\run.bat`, same console at http://127.0.0.1:8000), a downloaded PDF report and work order, and a screen recording.
5. Phone check (optional, impressive): open the link on a phone, **Inspect → Capture with camera**.

## The script (≈ 8 minutes, 10 presenter steps)

| # | Step | Do | Say |
|---|---|---|---|
| 1 | The idea | Overview hero | "A person compares a cabinet with its GA drawing and wire list, item by item. We don't ask AI 'what's wrong?'. We read the drawing with code and check every expected item at its known spot. FAIL only when evidence agrees." |
| 2 | Live inspection | **Run the live demo** | "This is the real engine in the cloud: parse the drawing, register the photo with ~16 label and ferrule anchors, five plug-in checks, consensus. About two seconds on one CPU core, no GPU." |
| 3 | Proof | Click issue **#2 ORD-RAIL-1**; toggle **Drawing** and **Anchors** | "Drawing on the left, photo on the right: CB43 and CB44 are swapped. The anchors that don't fit the drawing are exactly the swapped breakers." Type a note and press **FAIL** in *Inspector decision*: "a person confirms; it's logged." |
| 4 | Work order | **Work order** button | "Every FAIL becomes a numbered fix with location, proof and a time estimate, printable with sign-off. 4 fixes, about 33 minutes." |
| 5 | Re-check | Back → **Re-check** → **05** | "The technician fixed three things. New photo: 3 CLOSED, 1 OPEN, history v1 → v2." Drag the before/after slider. |
| 6 | Human in the loop | **Review** | "When the engine is unsure it says REVIEW, never a guessed FAIL. These come from a harsh camera; the inspector decides with the proof on screen (keys P / F), every decision is in the audit trail." |
| 7 | Unseen cabinet | **Fault Forge → Forge & inspect** | "A cabinet nobody has seen, random faults, random camera." Ask the jury to guess, **Reveal**. "Self-test: 87 of 87 planted faults, zero false alarms over 1,950 correct items." |
| 8 | Bad photos | **Robustness → Stress sweep** | "Clean, mild, moderate, hard, extreme. Watch the false-alarm count: it stays at zero. As the photo gets worse, findings move to REVIEW; a photo that doesn't register can't produce a FAIL at all." |
| 9 | QC analytics | **Analytics** | "Everything rolls up: first-pass yield, fix closure, inspector agreement, time saved. The heatmap shows where faults cluster on the cabinet, so the fix goes upstream to the station that causes it." |
| 10 | Under the hood | **Engine** | "Plug-in checks: a new check is one class. A new cabinet needs its GA drawing, no training. Honest limits: our test cabinets are generated; next is a detector and PaddleOCR fine-tuned on Emerson's photos." |

## Numbers to quote

| | |
|---|---|
| Self-test, 50 unseen cabinets | **87 / 87** planted faults caught, **0** false alarms over 1,950 correct items, 6 items (0.3%) to REVIEW |
| Degraded photos (tilt, keystone, blur, glare, noise, colour cast, JPEG) | **0** false FAILs on 115 degraded photos (90 scripted + 25 browser stress-sweep runs; 22 false FAILs on the first 90 before the Round 3 evidence rules); findings move to REVIEW instead |
| Speed | **0.9 s** per cabinet on a 4-core laptop, **~2 s** on the 1-vCPU cloud container (was 4 s / 18 s): OCR now runs in-process, identical text on all 1,668 test crops |
| Cloud | Stateless engine: nothing stored on the server; runs stay in the viewer's browser |

## Likely questions

| Question | Answer |
|---|---|
| Is the hosted version real or a recording? | Real: the pill says *Live cloud engine*; upload any photo or drawing set, or toggle checks. *Instant replay* is only the fallback (or a choice in the pill). |
| Why not GPT-4V / Gemini? | It invents faults; Emerson requires zero false alarms. The drawing is the ground truth; we ask narrow yes/no questions. Same photo, same report. |
| What happens with a bad photo? | The capture assistant scores it before the run (sharpness, exposure, glare). If it is still bad, unclear zones go to REVIEW; if it doesn't match the drawing at all, nothing can be FAIL. Show the Robustness Lab. |
| Where is the data stored? | Cloud runs: in the browser (IndexedDB). Local engine: `out/runs/`. The cloud engine keeps nothing. |
| How do people fit in? | Review station: confirm or overturn with proof, note, name, time. Overturned FAILs drop out of the work order; the agreement rate is in Analytics. |
| How do you add checks? | One `@check("NAME")` class in `inspector.py`: it appears in the checklist, PDF, toggles and Engine page. |
| Will it work on real cabinets? | Not proven yet: the numbers are on generated cabinets that copy Emerson's layout. With their samples: adapt the parser, fine-tune YOLO11 + PaddleOCR, re-run the same self-test and robustness sweep. |
| Which AI tools? | Tesseract OCR, OpenCV, PyMuPDF; an AI coding assistant helped write code (declared). |

## If something breaks

- **Pill red (engine offline)**: keep going. Samples, re-checks and Fault Forge replay recorded engine runs automatically; say so. *Check again* in the pill retries.
- **Upload rejected**: JPG/PNG only, phone photos are resized automatically; use a sample instead.
- **Browser problem**: the local engine (`run.bat`) serves the same console; `streamlit run app.py` is the last fallback.
