"""Report generation: marked-up photo, zoomed snippets (expected vs found), filled Excel checklist,
PDF report, and re-check (before vs after) with issue history."""
import json, datetime, os
import numpy as np, cv2, pymupdf
from PIL import Image, ImageDraw, ImageFont
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from inspector import R

F = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
COL = {"FAIL": (220, 38, 38), "REVIEW": (245, 158, 11), "PASS": (22, 163, 74), "SKIP": (120, 120, 120),
       "CLOSED": (22, 163, 74), "OPEN": (220, 38, 38), "REGRESSION": (147, 51, 234)}

def to_photo(box, H):
    x, y, w, h = box
    pts = np.float32([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]) * R
    p = cv2.perspectiveTransform(pts[None], np.linalg.inv(np.array(H)))[0]
    return p

def numbered(results):
    k = 0
    for r in results:
        if r["result"] in ("FAIL", "REVIEW"):
            k += 1; r["marker"] = k
    return results

def markup(photo_path, rep, out_path, status_key="result"):
    im = Image.open(photo_path).convert("RGB"); d = ImageDraw.Draw(im)
    f = ImageFont.truetype(F, 46)
    for r in rep["results"]:
        st = r.get(status_key, r["result"])
        if st not in ("FAIL", "REVIEW", "CLOSED", "OPEN", "REGRESSION") or "marker" not in r:
            continue
        p = to_photo(r["box"], rep["H"]); c = COL[st]
        pad = 10
        x0, y0 = p[:, 0].min() - pad, p[:, 1].min() - pad
        x1, y1 = p[:, 0].max() + pad, p[:, 1].max() + pad
        d.rectangle([x0, y0, x1, y1], outline=c, width=9)
        cx, cy = x1 + 4, y0 - 34
        d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=c, outline=(255, 255, 255), width=5)
        t = str(r["marker"]); tw = d.textlength(t, font=f)
        d.text((cx - tw / 2, cy - 28), t, fill=(255, 255, 255), font=f)
    im.save(out_path, quality=90)
    return out_path

def snippet(photo_path, rep, r, ga_png, ga_scale, out_path):
    """Found (zoomed photo crop) next to Expected (crop of the GA drawing)."""
    ph = Image.open(photo_path).convert("RGB")
    p = to_photo(r["box"], rep["H"]); m = 60
    found = ph.crop((int(p[:, 0].min() - m), int(p[:, 1].min() - m), int(p[:, 0].max() + m), int(p[:, 1].max() + m)))
    ga = Image.open(ga_png).convert("RGB")
    x, y, w, h = r["box"]; s = ga_scale
    exp = ga.crop((int(s["ox"] + (x - 15) * s["k"]), int(s["oy"] + (y - 15) * s["k"]),
                   int(s["ox"] + (x + w + 15) * s["k"]), int(s["oy"] + (y + h + 15) * s["k"])))
    Ht = 300
    found = found.resize((max(1, int(found.width * Ht / found.height)), Ht))
    exp = exp.resize((max(1, int(exp.width * Ht / exp.height)), Ht))
    W_ = found.width + exp.width + 30
    canvas = Image.new("RGB", (W_, Ht + 64), (255, 255, 255)); dd = ImageDraw.Draw(canvas)
    fnt = ImageFont.truetype(F, 22)
    canvas.paste(exp, (0, 50)); canvas.paste(found, (exp.width + 30, 50))
    dd.text((4, 14), "EXPECTED (GA)", fill=(31, 79, 168), font=fnt)
    dd.text((exp.width + 34, 14), "FOUND (photo)", fill=COL[r["result"]], font=fnt)
    canvas.save(out_path)
    return out_path

def ga_png(ga_pdf, out_png, dpi=150):
    page = pymupdf.open(ga_pdf)[0]
    page.get_pixmap(dpi=dpi).save(out_png)
    rects = [pymupdf.Rect(it[1]) for dr in page.get_drawings() for it in dr["items"] if it[0] == "re"]
    bp = max(rects, key=lambda r: r.width * r.height)
    z = dpi / 72
    return dict(ox=bp.x0 * z, oy=bp.y0 * z, k=bp.width * z / 600)

def fill_checklist(template_xlsx, rep, out_xlsx):
    wb = load_workbook(template_xlsx); ws = wb.active
    by = {r["id"]: r for r in rep["results"]}
    fills = {"PASS": "DCFCE7", "FAIL": "FECACA", "REVIEW": "FEF3C7", "SKIP": "E5E7EB"}
    for row in ws.iter_rows(min_row=2):
        r = by.get(row[0].value)
        if not r:
            continue
        row[3].value = r["expected"]; row[4].value = r["found"]; row[5].value = r["result"]
        row[6].value = (f"Marker #{r['marker']} | " if "marker" in r else "") + "; ".join(map(str, r["evidence"]))[:200]
        row[5].fill = PatternFill("solid", fgColor=fills[r["result"]]); row[5].font = Font(bold=True)
    for c, wdt in zip("ABCDEFG", [16, 10, 34, 22, 34, 10, 60]):
        ws.column_dimensions[c].width = wdt
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="0F2742")
    wb.save(out_xlsx)

def recheck(prev, new):
    """Close fixed items, keep open ones, flag regressions (was PASS, now FAIL)."""
    pb = {r["id"]: r for r in prev["results"]}
    for r in new["results"]:
        p = pb.get(r["id"])
        if p and p["result"] in ("FAIL", "REVIEW"):
            r["recheck"] = "CLOSED" if r["result"] == "PASS" else "OPEN"
            r["marker"] = p.get("marker")
        elif p and p["result"] == "PASS" and r["result"] == "FAIL":
            r["recheck"] = "REGRESSION"
    return new

def history_append(path, rep, label):
    h = json.load(open(path)) if os.path.exists(path) else []
    h.append(dict(time=datetime.datetime.now().isoformat(timespec="seconds"), run=label, photo=os.path.basename(rep["photo"]),
                  fail=sum(r["result"] == "FAIL" for r in rep["results"]),
                  passed=sum(r["result"] == "PASS" for r in rep["results"]),
                  issues=[r["id"] for r in rep["results"] if r["result"] in ("FAIL", "REVIEW")]))
    json.dump(h, open(path, "w"), indent=1)
