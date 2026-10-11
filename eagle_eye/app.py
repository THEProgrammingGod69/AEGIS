"""EAGLE EYE - Streamlit UI (prototype).  Run:  streamlit run app.py"""
import json, os, tempfile
import streamlit as st
import pandas as pd
from inspector import inspect
from report import markup, numbered, fill_checklist, recheck, snippet, ga_png

st.set_page_config(page_title="EAGLE EYE · Cabinet QC", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.2rem}
.kpi{border:1px solid #2e6b3c;border-radius:10px;padding:10px 14px;background:#06150a}
.kpi b{font-size:28px;display:block}
.kpi{color:#d7e3da}
</style>""", unsafe_allow_html=True)
st.markdown("## 🦅 EAGLE EYE  <span style='font-size:16px;color:#8aa'>Team ENIGMA · drawing-anchored cabinet QC</span>", unsafe_allow_html=True)

with st.sidebar:
    st.header("1 · Upload")
    photo = st.file_uploader("HD cabinet photo", type=["jpg", "jpeg", "png"])
    ga = st.file_uploader("GA drawing (PDF)", type=["pdf"])
    wl = st.file_uploader("Wire & label list (Excel)", type=["xlsx"])
    cl = st.file_uploader("QC checklist (Excel)", type=["xlsx"])
    st.header("Checks (plug-ins)")
    enabled = [c for c in ["GA", "ORDER", "LABEL", "FERRULE", "COLOUR"] if st.checkbox(c, True)]
    demo = st.toggle("Use demo inputs", value=True)
    run = st.button("▶  Inspect", type="primary", use_container_width=True)

def save(u, name):
    p = os.path.join(tempfile.gettempdir(), name); open(p, "wb").write(u.getbuffer()); return p

if run or "rep" in st.session_state:
    if run:
        if demo:
            P, G, W, C = "out/demo/photo_v1.jpg", "inputs/GA_EE-DEMO-01.pdf", "inputs/WireList_EE-DEMO-01.xlsx", "inputs/QC_Checklist_EE-DEMO-01.xlsx"
        else:
            P, G, W, C = save(photo, "p.jpg"), save(ga, "ga.pdf"), save(wl, "wl.xlsx"), save(cl, "cl.xlsx")
        with st.spinner("Parsing drawing · registering photo · running checks…"):
            rep, _ = inspect(P, G, W, enabled=enabled); numbered(rep["results"])
            markup(P, rep, "out/ui_marked.jpg")
        st.session_state.update(rep=rep, P=P, G=G, C=C)
    rep = st.session_state["rep"]
    res = rep["results"]
    k = {x: sum(r["result"] == x for r in res) for x in ("PASS", "FAIL", "REVIEW", "SKIP")}
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f"<div class='kpi'><b style='color:#22c55e'>{k['PASS']}</b>PASS</div>", unsafe_allow_html=True)
    c2.markdown(f"<div class='kpi'><b style='color:#f05252'>{k['FAIL']}</b>FAIL · fix before shipping</div>", unsafe_allow_html=True)
    c3.markdown(f"<div class='kpi'><b style='color:#f5a524'>{k['REVIEW']}</b>REVIEW · re-photo zone</div>", unsafe_allow_html=True)
    c4.markdown(f"<div class='kpi'><b style='color:#9aa'>{k['SKIP']}</b>SKIP · root cause elsewhere</div>", unsafe_allow_html=True)
    left, right = st.columns([1, 1.25])
    left.image("out/ui_marked.jpg", caption="Every FAIL boxed and numbered on the photo", use_container_width=True)
    df = pd.DataFrame([dict(**{"#": r.get("marker", ""), "Check": r["id"], "Expected (drawing)": r["expected"],
                               "Found (photo)": r["found"], "Result": r["result"]}) for r in res])
    only = right.toggle("Show only issues", value=True)
    view = df[df.Result.isin(["FAIL", "REVIEW"])] if only else df
    right.dataframe(view.style.map(lambda v: {"FAIL": "color:#f05252;font-weight:700", "PASS": "color:#22c55e",
                                              "REVIEW": "color:#f5a524", "SKIP": "color:#999"}.get(v, ""), subset=["Result"]),
                    use_container_width=True, hide_index=True, height=260)
    gs = ga_png(st.session_state["G"], "out/ui_ga.png")
    fails = [r for r in res if "marker" in r]
    if fails:
        sel = right.selectbox("Proof for issue #", [f"#{r['marker']} · {r['id']} · {r['found']}" for r in fails], index=min(1, len(fails) - 1))
        r = fails[int(sel.split("·")[0].strip()[1:]) - 1]
        snippet(st.session_state["P"], rep, r, "out/ui_ga.png", gs, "out/ui_snip.png")
        right.image("out/ui_snip.png", width=430)
    fill_checklist(st.session_state["C"], rep, "out/ui_checklist.xlsx")
    b1, b2, b3 = right.columns(3)
    b1.download_button("⬇ Filled checklist", open("out/ui_checklist.xlsx", "rb"), "QC_Checklist_FILLED.xlsx", use_container_width=True)
    b2.download_button("⬇ Report JSON", json.dumps(rep, default=str), "report.json", use_container_width=True)
    b3.button("📷 Re-check after fix", use_container_width=True)
else:
    st.info("Upload a cabinet photo, its GA drawing, wire list and QC checklist (or use the demo inputs), then press Inspect.")
