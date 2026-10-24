"""One-click PDF QC report: verdict, counts, marked-up photo, every finding with expected-vs-found proof,
re-check status and the complete checklist. Built with ReportLab (no external services)."""
import datetime
import os

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

import config

pdfmetrics.registerFont(TTFont("EE", config.font("DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("EE-Bold", config.font("DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("EE-Mono", config.font("DejaVuSansMono.ttf")))

INK = colors.HexColor("#0B1220")
MUTED = colors.HexColor("#5B6577")
LINE = colors.HexColor("#E3E7EE")
BAND = colors.HexColor("#0A1020")
ACCENT = colors.HexColor("#0EA5E9")
TONE = {"PASS": "#059669", "FAIL": "#E11D48", "REVIEW": "#D97706", "SKIP": "#6B7280", "NOT_IN_VIEW": "#64748B",
        "CLOSED": "#059669",
        "OPEN": "#E11D48", "REGRESSION": "#9333EA", "NEW": "#EA580C", "HOLD": "#E11D48"}
SOFT = {"PASS": "#ECFDF5", "FAIL": "#FFF1F2", "REVIEW": "#FFFBEB", "SKIP": "#F3F4F6", "NOT_IN_VIEW": "#F8FAFC",
        "CLOSED": "#ECFDF5",
        "OPEN": "#FFF1F2", "REGRESSION": "#FAF5FF", "NEW": "#FFF7ED", "HOLD": "#FFF1F2"}
CHECK_TITLE = {"GA": "Part present", "MISSING": "Part present", "ORDER": "Rail order", "LABEL": "Device label",
               "UNKNOWN_LABEL": "Unknown label", "FERRULE": "Ferrule text", "COLOUR": "Wire colour"}

S = dict(
    h1=ParagraphStyle("h1", fontName="EE-Bold", fontSize=15, leading=19, textColor=INK, spaceBefore=4, spaceAfter=8),
    h2=ParagraphStyle("h2", fontName="EE-Bold", fontSize=10.5, leading=14, textColor=INK),
    body=ParagraphStyle("body", fontName="EE", fontSize=8.6, leading=12, textColor=INK),
    small=ParagraphStyle("small", fontName="EE", fontSize=7.4, leading=10, textColor=MUTED),
    mono=ParagraphStyle("mono", fontName="EE-Mono", fontSize=7.4, leading=10, textColor=INK),
    cell=ParagraphStyle("cell", fontName="EE", fontSize=7.4, leading=9.4, textColor=INK),
    cellb=ParagraphStyle("cellb", fontName="EE-Bold", fontSize=7.4, leading=9.4, textColor=INK),
    kpi=ParagraphStyle("kpi", fontName="EE-Bold", fontSize=22, leading=24, alignment=TA_CENTER),
    kpil=ParagraphStyle("kpil", fontName="EE-Bold", fontSize=7, leading=9, alignment=TA_CENTER, textColor=MUTED),
    verdict=ParagraphStyle("verdict", fontName="EE-Bold", fontSize=17, leading=21, textColor=colors.white),
    verdict2=ParagraphStyle("verdict2", fontName="EE", fontSize=8.8, leading=12, textColor=colors.white),
)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def img(path, max_w, max_h):
    w, h = PILImage.open(path).size
    k = min(max_w / w, max_h / h)
    return Image(path, width=w * k, height=h * k)


def _chrome(meta, rep):
    cab = rep.get("ga", {}).get("cabinet", "")
    created = meta.get("created", "")

    def first(c, doc):
        W, H = A4
        c.saveState()
        c.setFillColor(BAND); c.rect(0, H - 34 * mm, W, 34 * mm, stroke=0, fill=1)
        c.setFillColor(ACCENT); c.rect(0, H - 34 * mm, W, 0.9 * mm, stroke=0, fill=1)
        # eye mark
        cx, cy = 22 * mm, H - 17 * mm
        c.setStrokeColor(ACCENT); c.setLineWidth(1.6)
        p = c.beginPath(); p.moveTo(cx - 7 * mm, cy); p.curveTo(cx - 3 * mm, cy + 5 * mm, cx + 3 * mm, cy + 5 * mm, cx + 7 * mm, cy)
        p.curveTo(cx + 3 * mm, cy - 5 * mm, cx - 3 * mm, cy - 5 * mm, cx - 7 * mm, cy); c.drawPath(p, stroke=1, fill=0)
        c.setFillColor(ACCENT); c.circle(cx, cy, 2.1 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont("EE-Bold", 17); c.drawString(33 * mm, H - 15.5 * mm, "EAGLE EYE")
        c.setFont("EE", 8.5); c.setFillColor(colors.HexColor("#9FB0C8"))
        c.drawString(33 * mm, H - 21.5 * mm, "Cabinet QC report  ·  drawing-first verification")
        c.setFillColor(colors.white); c.setFont("EE-Bold", 13); c.drawRightString(W - 16 * mm, H - 15 * mm, cab)
        c.setFont("EE", 7.8); c.setFillColor(colors.HexColor("#9FB0C8"))
        c.drawRightString(W - 16 * mm, H - 20.5 * mm, f"Run {meta.get('id', '')}")
        c.drawRightString(W - 16 * mm, H - 25 * mm, created.replace("T", "  "))
        c.restoreState()
        footer(c, doc)

    def footer(c, doc):
        W, _ = A4
        c.saveState()
        c.setStrokeColor(LINE); c.setLineWidth(0.6); c.line(16 * mm, 13 * mm, W - 16 * mm, 13 * mm)
        c.setFont("EE", 7); c.setFillColor(MUTED)
        c.drawString(16 * mm, 9 * mm, f"EAGLE EYE {config.VERSION}  ·  Team ENIGMA  ·  {cab}  ·  FAIL only when evidence agrees; "
                                      "unclear items go to REVIEW")
        c.drawRightString(W - 16 * mm, 9 * mm, f"Page {doc.page}")
        c.restoreState()

    return first, footer


def _kv(rows, widths):
    t = Table([[Paragraph(esc(k), S["small"]), Paragraph(esc(v), S["cell"])] for k, v in rows], colWidths=widths)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return t


def build_pdf(out_pdf, rep, meta, marked_path, crop_paths):
    """``crop_paths(result) -> (expected_png, found_png)`` supplies the proof images for each finding."""
    doc = SimpleDocTemplate(out_pdf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=18 * mm,
                            bottomMargin=19 * mm, title=f"EAGLE EYE QC report {meta.get('id', '')}",
                            author="EAGLE EYE (Team ENIGMA)", subject="Control cabinet QC")
    first, later = _chrome(meta, rep)
    results = rep["results"]
    k = rep.get("counts") or {x: sum(r["result"] == x for r in results) for x in ("PASS", "FAIL", "REVIEW", "SKIP")}
    v = meta.get("verdict", {})
    vkey = v.get("label", "HOLD" if k["FAIL"] else "REVIEW" if k["REVIEW"] else "PASS")
    story = [Spacer(1, 24 * mm)]            # room for the first-page header band

    # verdict + KPIs
    vt = Table([[Paragraph(esc(v.get("headline", vkey)), S["verdict"])], [Paragraph(esc(v.get("detail", "")), S["verdict2"])]],
               colWidths=[178 * mm])
    vt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(TONE.get(vkey, "#059669"))),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (0, 0), 9),
                            ("BOTTOMPADDING", (0, -1), (-1, -1), 9), ("ROUNDEDCORNERS", [6, 6, 6, 6])]))
    story += [vt, Spacer(1, 6)]
    real = rep.get("engine_kind") == "real"
    last = "NOT_IN_VIEW" if real else "SKIP"
    keys = ("PASS", "FAIL", "REVIEW", last)
    cells = [[Paragraph(f"<font color='{TONE[x]}'>{k.get(x, 0)}</font>", S["kpi"]) for x in keys],
             [Paragraph(x, S["kpil"]) for x in ("PASS", "FAIL · FIX BEFORE SHIPPING", "REVIEW · RE-PHOTO ZONE",
                                               "NOT IN VIEW · NOT JUDGED HERE" if real else "SKIP · ROOT CAUSE ELSEWHERE")]]
    kt = Table(cells, colWidths=[44.5 * mm] * 4)
    kt.setStyle(TableStyle([("BOX", (0, 0), (0, -1), 0.6, LINE), ("BOX", (1, 0), (1, -1), 0.6, LINE),
                            ("BOX", (2, 0), (2, -1), 0.6, LINE), ("BOX", (3, 0), (3, -1), 0.6, LINE),
                            ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, -1), (-1, -1), 7)] +
                           [("BACKGROUND", (i, 0), (i, -1), colors.HexColor(SOFT[x])) for i, x in enumerate(keys)]))
    story += [kt, Spacer(1, 10)]

    reg = rep.get("registration", {})
    inputs = meta.get("inputs", {})
    rows = [("Cabinet", rep.get("ga", {}).get("cabinet", "")),
            ("Photo", meta.get("photo_name", os.path.basename(rep["photo"]))),
            ("GA drawing", inputs.get("ga", {}).get("name", "")),
            ("Wire list", inputs.get("wires", {}).get("name", "")),
            ("QC checklist", inputs.get("checklist", {}).get("name", "")),
            ("Checks", " · ".join(rep.get("enabled", []))),
            ("Items checked", f"{len(results)} expected items from the drawing and wire list"),
            ("Registration", f"backplate outline + {reg.get('anchors', 0)} label/ferrule anchors, "
                             f"{reg.get('inliers', 0)} RANSAC inliers" + (f"; off-pattern: {', '.join(reg['outliers'])}" if reg.get("outliers") else "")),
            ("Processing", f"{rep.get('timing', {}).get('total', 0):.1f} s on CPU"),
            ("Engine", f"EAGLE EYE {rep.get('engine', config.VERSION)} · Tesseract OCR · OpenCV · PyMuPDF")]
    if rep.get("engine_kind") == "real":
        cov, ag = rep.get("coverage") or {}, rep.get("agent") or {}
        judged = len(results) - k.get("NOT_IN_VIEW", 0)
        rows[6:] = [("Items checked", f"{judged} judged in this photo, {k.get('NOT_IN_VIEW', 0)} not in view"),
                    ("Coverage", f"{cov.get('verified', 0)} of {cov.get('total', 0)} labelled drawing items verified "
                                 f"(views: {', '.join(rep.get('views') or []) or 'none'})"),
                    ("Registration", f"{reg.get('anchors', 0)} label anchors, {reg.get('inliers', 0)} on the drawing"
                                     + (f"; off-pattern: {', '.join(reg['outliers'])}" if reg.get("outliers") else "")),
                    ("Verifier", (f"Claude ({ag.get('model')}, {ag.get('calls', 0)} calls)" if ag.get("enabled")
                                  else f"off: {ag.get('reason') or 'no API key'}")),
                    ("Processing", f"{rep.get('timing', {}).get('total', 0):.1f} s on CPU"),
                    ("Engine", f"EAGLE EYE {rep.get('engine', config.VERSION)} · PP-OCRv4 · OpenCV · PyMuPDF")]
    if meta.get("parent"):
        rows.insert(2, ("Re-check of", meta["parent"]))
    left = [Paragraph("Inspection details", S["h2"]), Spacer(1, 4), _kv(rows, [24 * mm, 66 * mm]), Spacer(1, 10),
            Paragraph("How to read this report", S["h2"]), Spacer(1, 3),
            Paragraph("Every item is checked one at a time at the spot the GA drawing gives it. An item is <b>FAIL</b> "
                      "only when independent evidence agrees; anything unclear is <b>REVIEW</b> (re-photo that zone) "
                      "instead of a guess. <b>SKIP</b> means the root cause is already reported by another item "
                      "(a missing part is one FAIL, not five)."
                      + (" <b>NOT_IN_VIEW</b> items are outside this photo or too small in it to read: they are "
                         "neither passed nor failed." if rep.get("engine_kind") == "real" else "")
                      + " Numbers match the boxes on the photo.", S["small"])]
    lt = Table([[x] for x in left], colWidths=[92 * mm])
    lt.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
    small = out_pdf + ".marked.jpg"               # ~1100 px is plenty at 84 mm wide; keeps the PDF small
    m = PILImage.open(marked_path).convert("RGB"); m.thumbnail((1100, 1500), PILImage.LANCZOS); m.save(small, quality=85)
    right = img(small, 84 * mm, 118 * mm)
    two = Table([[lt, right]], colWidths=[94 * mm, 84 * mm])
    two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [two, PageBreak()]

    # findings
    status_key = "recheck" if meta.get("parent") else "result"
    issues = [r for r in results if r.get("marker") and (r.get(status_key) or r["result"]) in TONE]
    issues.sort(key=lambda r: r["marker"])
    story.append(Paragraph(f"{'Re-check findings' if meta.get('parent') else 'Findings'} ({len(issues)})", S["h1"]))
    if not issues:
        story.append(Paragraph("No findings: every item the drawing expects was verified on the photo.", S["body"]))
    for r in issues:
        st = r.get(status_key) or r["result"]
        exp_p, found_p = crop_paths(r)
        badge = Table([[Paragraph(f"<font color='white'><b>{r['marker']}</b></font>",
                                  ParagraphStyle("b", fontName="EE-Bold", fontSize=10, alignment=TA_CENTER))]],
                      colWidths=[8 * mm], rowHeights=[8 * mm])
        badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(TONE[st])),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ROUNDEDCORNERS", [4, 4, 4, 4])]))
        head = Table([[badge, Paragraph(f"<b>{esc(r['id'])}</b>  <font color='#5B6577'>{CHECK_TITLE.get(r['check'], r['check'])}</font>", S["h2"]),
                       Paragraph(f"<font color='{TONE[st]}'><b>{st}</b></font>", ParagraphStyle("s", fontName="EE-Bold", fontSize=9, alignment=2))]],
                     colWidths=[11 * mm, 132 * mm, 35 * mm])
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        ev = "; ".join(map(str, r.get("evidence", [])))
        facts = _kv([("Expected (drawing)", r["expected"]), ("Found (photo)", r["found"]), ("Evidence", ev)] +
                    ([("Before re-check", f"{r.get('prev_result')}: {r.get('prev_found')}")] if r.get("prev_result") else []),
                    [30 * mm, 148 * mm])
        pics = Table([[Paragraph("EXPECTED · GA drawing", S["small"]), Paragraph("FOUND · photo", S["small"])],
                      [img(exp_p, 86 * mm, 46 * mm), img(found_p, 86 * mm, 46 * mm)]], colWidths=[89 * mm, 89 * mm])
        pics.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 1), (-1, 1), "CENTER"),
                                  ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F6F8FB")),
                                  ("BOX", (0, 1), (0, 1), 0.5, LINE), ("BOX", (1, 1), (1, 1), 0.5, LINE),
                                  ("TOPPADDING", (0, 1), (-1, 1), 5), ("BOTTOMPADDING", (0, 1), (-1, 1), 5)]))
        story.append(KeepTogether([head, Spacer(1, 4), pics, Spacer(1, 4), facts, Spacer(1, 12)]))

    # re-check
    rc = meta.get("recheck")
    if rc:
        rows = [[Paragraph(f"<b>{x}</b>", S["cellb"]) for x in ("#", "Item", "Before", "Now", "Status")]]
        for r in sorted([r for r in results if r.get("recheck")], key=lambda r: r.get("marker") or 0):
            rows.append([Paragraph(str(r.get("marker", "")), S["cell"]), Paragraph(esc(r["id"]), S["cell"]),
                         Paragraph(esc(f"{r.get('prev_result', '—')}: {r.get('prev_found', '—')}"), S["cell"]),
                         Paragraph(esc(f"{r['result']}: {r['found']}"), S["cell"]),
                         Paragraph(f"<font color='{TONE[r['recheck']]}'><b>{r['recheck']}</b></font>", S["cell"])])
        t = Table(rows, colWidths=[9 * mm, 30 * mm, 55 * mm, 55 * mm, 29 * mm], repeatRows=1)
        t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F5F9")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story += [KeepTogether([Spacer(1, 4), Paragraph("Re-check against the previous inspection", S["h1"]),
                                Paragraph("  ·  ".join(f"{x} {rc.get(x, 0)}" for x in ("CLOSED", "OPEN", "REGRESSION", "NEW")), S["body"]),
                                Spacer(1, 5), t]), Spacer(1, 10)]

    # full checklist
    story += [PageBreak(), Paragraph(f"QC checklist ({len(results)} items)", S["h1"])]
    rows = [[Paragraph(f"<b>{x}</b>", S["cellb"]) for x in ("Item", "Check", "Expected (drawing)", "Found (photo)", "Result")]]
    style = [("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F5F9")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4)]
    for i, r in enumerate(results, start=1):
        rows.append([Paragraph(esc(r["id"]), S["mono"]), Paragraph(CHECK_TITLE.get(r["check"], r["check"]), S["cell"]),
                     Paragraph(esc(r["expected"]), S["cell"]), Paragraph(esc(r["found"]), S["cell"]),
                     Paragraph(f"<font color='{TONE[r['result']]}'><b>{r['result']}</b></font>"
                               + (f" <font color='{TONE[r['recheck']]}'>· {r['recheck']}</font>" if r.get("recheck") else "")
                               + (f" <font color='#5B6577'>#{r['marker']}</font>" if r.get("marker") else ""), S["cell"])])
        style.append(("BACKGROUND", (4, i), (4, i), colors.HexColor(SOFT[r["result"]])))
    t = Table(rows, colWidths=[26 * mm, 21 * mm, 47 * mm, 50 * mm, 34 * mm], repeatRows=1)
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 10),
              Paragraph(f"Generated {datetime.datetime.now().isoformat(timespec='seconds').replace('T', ' ')} by EAGLE EYE. "
                        "Every result is traceable to the drawing item it checks and to the evidence listed above.", S["small"])]
    doc.build(story, onFirstPage=first, onLaterPages=later)
    os.remove(small)
    return out_pdf
