"""EAGLE EYE - Streamlit UI (lightweight fallback for Streamlit Cloud).   streamlit run app.py

The full console is server.py (FastAPI + web UI). Both use the same engine and run store (service.py).
"""
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

import config
import service
from inspector import ORDER, InspectionError, tesseract_info

st.set_page_config(page_title="EAGLE EYE · Cabinet QC", page_icon="🦅", layout="wide")

TONE = {"PASS": "#34d399", "FAIL": "#fb7185", "REVIEW": "#fbbf24", "SKIP": "#94a3b8", "CLOSED": "#34d399",
        "OPEN": "#fb7185", "REGRESSION": "#c084fc", "NEW": "#fb923c", "HOLD": "#fb7185"}

st.markdown("""<style>
:root{--line:rgba(148,163,184,.14)}
.block-container{padding-top:1.4rem;max-width:1440px}
[data-testid="stSidebar"]{background:#070a10;border-right:1px solid var(--line)}
h1,h2,h3{letter-spacing:-.02em}
.ee-brand{display:flex;align-items:center;gap:12px;margin-bottom:.4rem}
.ee-brand b{font-size:22px;letter-spacing:.16em}
.ee-brand span{color:#6c788d;font-size:12px;letter-spacing:.12em;text-transform:uppercase}
.ee-verdict{border:1px solid var(--c);border-left:5px solid var(--c);border-radius:16px;padding:16px 20px;
  background:linear-gradient(90deg,color-mix(in srgb,var(--c) 16%,transparent),transparent 70%);margin:6px 0 14px}
.ee-verdict small{font-family:monospace;letter-spacing:.16em;color:var(--c);font-weight:700}
.ee-verdict h3{margin:.2rem 0 .1rem;font-size:26px}
.ee-verdict p{color:#a6b1c4;margin:0}
.ee-kpi{border:1px solid var(--line);border-radius:14px;padding:12px 16px;background:rgba(148,163,184,.04)}
.ee-kpi b{font-size:32px;display:block;line-height:1.1;color:var(--c)}
.ee-kpi span{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#6c788d}
.ee-cap{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#6c788d;margin-bottom:4px}
.ee-pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:700;font-family:monospace;
  color:var(--c);border:1px solid var(--c);background:color-mix(in srgb,var(--c) 12%,transparent)}
</style>""", unsafe_allow_html=True)

st.markdown("<div class='ee-brand'><b>🦅 EAGLE EYE</b><span>Drawing-first cabinet QC · Team ENIGMA</span></div>",
            unsafe_allow_html=True)


def save_upload(u, name):
    p = Path(tempfile.gettempdir()) / f"ee_{os.getpid()}_{name}"
    p.write_bytes(u.getbuffer())
    return p


def kpi(col, value, label, tone):
    col.markdown(f"<div class='ee-kpi' style='--c:{tone}'><b>{value}</b><span>{label}</span></div>", unsafe_allow_html=True)


def pill(s):
    return f"<span class='ee-pill' style='--c:{TONE.get(s, '#94a3b8')}'>{s}</span>"


samples = service.samples()
with st.sidebar:
    t = tesseract_info()
    if not t["ok"]:
        st.error(t["error"])
    st.header("1 · Cabinet photo")
    up = st.file_uploader("Upload a photo", type=["jpg", "jpeg", "png"])
    labels = {f"{s['id']} · {s['title']}": s for s in samples}
    pick = st.selectbox("…or a sample photo", list(labels), index=0, disabled=up is not None)
    sel = labels[pick]
    if up is None:
        st.caption(f"Planted: {', '.join(sel['fault_text']) or 'none'}")
    st.header("2 · Engineering inputs")
    st.caption("Leave empty to use the demo drawing set (EE-DEMO-01).")
    ga = st.file_uploader("GA drawing (vector PDF)", type=["pdf"])
    wl = st.file_uploader("Wire & label list (Excel)", type=["xlsx"])
    cl = st.file_uploader("QC checklist (Excel)", type=["xlsx"])
    st.header("3 · Plug-in checks")
    enabled = [c for c in ORDER if st.checkbox(c, True, key=f"chk_{c}")]
    run = st.button("▶  Inspect", type="primary", use_container_width=True, disabled=not enabled)
    st.divider()
    st.caption("Full console with live pipeline, interactive viewer and Fault Forge: `python server.py`")


def inspect_now(photo_path, name, parent=None):
    files = {k: (save_upload(u, u.name), u.name) for k, u in (("ga", ga), ("wires", wl), ("checklist", cl)) if u}
    with st.status("Parsing drawing · registering photo · running checks…", expanded=True) as box:
        def on_event(ev):
            if ev["status"] == "done" and ev["stage"] in ("parse", "register", "check", "consensus", "report", "recheck"):
                extra = ev.get("check") or ""
                box.write(f"✓ {ev['stage']} {extra}  ·  {ev['t']:.2f}s")
        try:
            meta = service.run_inspection(photo_path, files.get("ga", (None,))[0], files.get("wires", (None,))[0],
                                          files.get("checklist", (None,))[0], enabled=enabled, parent=parent,
                                          source="upload" if up else "sample", photo_name=name,
                                          input_names={k: v[1] for k, v in files.items()}, on_event=on_event)
        except InspectionError as e:
            box.update(label=str(e), state="error")
            return None
        box.update(label=f"Done in {meta['timing']['total']:.1f} s", state="complete", expanded=False)
    return meta


if run:
    photo_path, name = (save_upload(up, up.name), up.name) if up else (config.SAMPLES / sel["file"], sel["file"])
    meta = inspect_now(photo_path, name)
    if meta:
        st.session_state["rid"] = meta["id"]

rid = st.session_state.get("rid")
if not rid:
    st.info("Pick a sample (or upload a photo) in the sidebar and press **Inspect**. Sample 01 is Emerson's example "
            "with 4 planted faults; re-check it with sample 05 to see 3 CLOSED and 1 OPEN.")
    st.stop()

p = service.run_payload(rid)
meta, res = p["meta"], p["results"]
v = meta["verdict"]
st.markdown(f"<div class='ee-verdict' style='--c:{TONE[v['label']]}'><small>{v['label']}</small>"
            f"<h3>{v['headline'].split(' · ')[-1]}</h3><p>{v['detail']} · {meta['label']} · "
            f"{meta['timing']['total']:.1f} s on CPU · {meta['registration']['anchors']} anchors</p></div>",
            unsafe_allow_html=True)
cols = st.columns(4)
if meta.get("recheck"):
    for c, k in zip(cols, ("CLOSED", "OPEN", "REGRESSION", "NEW")):
        kpi(c, meta["recheck"][k], k, TONE[k])
else:
    for c, k, lab in zip(cols, ("PASS", "FAIL", "REVIEW", "SKIP"),
                         ("PASS", "FAIL · fix before shipping", "REVIEW · re-photo zone", "SKIP · root cause elsewhere")):
        kpi(c, meta["counts"][k], lab, TONE[k])

st.write("")
left, right = st.columns([1, 1.2])
left.image(str(service.artefact(rid, "marked")), caption="Every issue boxed and numbered on the photo", use_container_width=True)
issues = [r for r in res if r.get("marker")]
with right:
    df = pd.DataFrame([{"#": str(r.get("marker") or ""), "Item": r["id"], "Expected (drawing)": r["expected"],
                        "Found (photo)": r["found"], "Result": r["result"], "Re-check": r.get("recheck") or ""} for r in res])
    only = st.toggle("Show only issues", value=True)
    view = df[df["#"] != ""] if only else df
    st.dataframe(view.style.map(lambda x: f"color:{TONE[x]};font-weight:700" if x in TONE else "", subset=["Result", "Re-check"]),
                 use_container_width=True, hide_index=True, height=260)
    options = issues or res
    choice = st.selectbox("Proof for", [f"#{r.get('marker') or '-'} · {r['id']} · {r['found']}" for r in options])
    r = options[[f"#{r.get('marker') or '-'} · {r['id']} · {r['found']}" for r in options].index(choice)]
    a, b = st.columns(2)
    a.markdown("<div class='ee-cap'>Expected · GA drawing</div>", unsafe_allow_html=True)
    a.image(str(service.item_crop(rid, r["id"], "expected")), use_container_width=True)
    b.markdown("<div class='ee-cap'>Found · photo</div>", unsafe_allow_html=True)
    b.image(str(service.item_crop(rid, r["id"], "found")), use_container_width=True)
    st.markdown(f"{pill(r.get('recheck') or r['result'])} &nbsp; `{r['expected']}` → **{r['found']}**  \n"
                f"<span style='color:#6c788d;font-size:12px'>{'; '.join(map(str, r['evidence']))}</span>", unsafe_allow_html=True)
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇ PDF report", service.artefact(rid, "pdf").read_bytes(), f"EAGLE_EYE_Report_{rid}.pdf", use_container_width=True)
    d2.download_button("⬇ Filled checklist", service.artefact(rid, "checklist").read_bytes(), f"QC_Checklist_{rid}.xlsx", use_container_width=True)
    d3.download_button("⬇ Report JSON", service.artefact(rid, "json").read_bytes(), f"EAGLE_EYE_{rid}.json", use_container_width=True)

st.divider()
st.subheader("📷 Re-check after the fix")
st.caption("New photo of the same cabinet: fixed items CLOSE, the rest stay OPEN, newly broken items are REGRESSION.")
c1, c2 = st.columns([1, 1])
rc_up = c1.file_uploader("Photo taken after the fix", type=["jpg", "jpeg", "png"], key="rc_up")
rc_pick = c2.selectbox("…or a sample", list(labels), index=min(4, len(labels) - 1), key="rc_pick")
if c2.button("Re-check", type="primary", use_container_width=True):
    src = (save_upload(rc_up, rc_up.name), rc_up.name) if rc_up else (config.SAMPLES / labels[rc_pick]["file"], labels[rc_pick]["file"])
    m2 = inspect_now(*src, parent=rid)
    if m2:
        st.session_state["rid"] = m2["id"]
        st.rerun()

if meta.get("parent"):
    prev = service.get_meta(meta["parent"])
    st.markdown(f"**Before (v{prev['version']}, {prev['verdict']['label']}) → after (v{meta['version']}, {v['label']})**")
    b1, b2 = st.columns(2)
    b1.image(str(service.artefact(prev["id"], "marked")), caption=f"v{prev['version']}", use_container_width=True)
    b2.image(str(service.artefact(rid, "marked")), caption=f"v{meta['version']}", use_container_width=True)

with st.expander("History of this cabinet"):
    st.dataframe(pd.DataFrame([{"Version": f"v{m['version']}", "Run": m["id"], "Label": m["label"], "Verdict": m["verdict"]["label"],
                                "FAIL": m["counts"]["FAIL"], "REVIEW": m["counts"]["REVIEW"],
                                "Closed": (m.get("recheck") or {}).get("CLOSED"), "Open": (m.get("recheck") or {}).get("OPEN")}
                               for m in service.chain(rid)]), hide_index=True, use_container_width=True)
with st.expander("Raw report JSON"):
    st.json(json.loads(service.artefact(rid, "json").read_text(encoding="utf-8")), expanded=False)
