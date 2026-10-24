"""Drawing knowledge base (Phase 1): pure helpers, the synthetic demo drawing and, when present, Emerson's real set.

The real drawing set is not in git (data/emerson/); those tests skip when it is missing.
"""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import config
from kb import drawing_kb as dkb
from kb.drawing_kb import build_kb, drawing_crop, is_real_drawing, kind_of_title, tag_of, view_key, view_tags

REAL = Path(__file__).resolve().parents[2] / "data" / "emerson" / "Sanitized_Cabinet_Drawing.pdf"
needs_real = pytest.mark.skipif(not REAL.exists(), reason="Emerson drawing set not available (data/emerson/)")


# ------------------------------------------------------------------ pure helpers
@pytest.mark.parametrize("title, kind", [
    ("INTERNAL GENERAL ARRANGEMENT - FRONT AND SIDE VIEW - 13GE03331", "ga"),
    ("Internal General  Arrangement-Rear View", "ga"),
    ("G.A. DRAWING - CABINET X", "ga"),
    ("FRONT DOOR INTERNAL VIEW", "ga"),
    ("NAMEPLATE DETAILS - 1 - 13GE03331", "nameplate"),
    ("Name Plate Details", "nameplate"),
    ("LABEL SCHEDULE", "nameplate"),
    ("BILL OF MATERIALS - 2", "bom"),
    ("POWER DISTRIBUTION - 4 / SMOKE DETECTOR WIRING - 13GE03331", "power"),
    ("LEGEND & GENERAL SPECIFICATIONS SHEET - 13GE03331", "legend"),
    ("ABBREVIATION SHEET", "abbreviations"),
    ("CABINET OUTLINE DIMENSIONS - FRONT, REAR & SIDE VIEW", "outline"),
    ("CABINET TOP VIEW, PLINTH AND GLAND PLATE DETAILS", "top_view"),
    ("GROUNDING TYPICAL FOR MARSHALLING CABINET", "grounding"),
    ("EARTHING DETAILS - 13GE03331", "earthing"),
    ("NETWORK CONNECTIONS", "network"),
    ("TAGGING NOTES", None),
    ("", None),
])
def test_page_kind_from_title(title, kind):
    assert kind_of_title(title) == kind


@pytest.mark.parametrize("title, key", [
    ("FRONT INSIDE VIEW", "front"), ("REAR INSIDE VIEW", "rear"), ("LEFT SIDE VIEW", "left"),
    ("Right inside view", "right"), ("FRONT DOOR INSIDE VIEW", "door"), ("BACK VIEW", "rear"),
    ("TOP VIEW", "top"), ("SECTION A VIEW", "a"), ("VIEW", "view"),
])
def test_view_key(title, key):
    assert view_key(title) == key


@pytest.mark.parametrize("word, tag", [
    ("PS11", "PS11"), ("13CSLS03335(PRI)", "13CSLS03335"), ("D13-In1(+)", "D13"), ("X-FSW1-3", "X-FSW1"),
    ("(IE)", "IE"), ("XS1-4", "XS1"), ("2.5mm²", None), ("18.E-5", None), ("C-13GE03331-01", None), ("16A", None),
])
def test_tag_of(word, tag):
    assert tag_of(word) == tag


def _word(text, x0, size=1.5, line=(0, 0), n=0, y0=10.0):
    return {"text": text, "bbox": (x0, y0, x0 + len(text) * 0.6 * size, y0 + size), "size": size, "rot": 0,
            "line": line, "n": n}


def test_tag_tokens_joins_split_descriptions():
    toks = dkb._tag_tokens([_word("FILTER", 10, n=0), _word("1", 15, n=1), _word("CB11", 30, line=(1, 0)),
                            _word("16A", 40, line=(2, 0)), _word("TYPE", 45, line=(2, 0), n=1)])
    assert [(t["tag"], t["display"]) for t in toks] == [("FILTER1", "FILTER 1"), ("CB11", "CB11")]


def test_edit1():
    assert dkb._edit1("XS11", "XS21") and dkb._edit1("ISG", "ISE") and dkb._edit1("XS1", "XS11")
    assert not dkb._edit1("CB11", "CB22") and not dkb._edit1("X1", "X111")


def _inst(size, inside=True):
    return {"size": size, "inside": inside}


def test_size_bands_follow_the_drawing_distribution():
    inst = ([_inst(1.03)] * 10 + [_inst(0.88)] + [_inst(1.28)] * 3 + [_inst(1.4)] * 30 + [_inst(1.47)] * 40
            + [_inst(1.65)] * 20 + [_inst(3.05)] * 15 + [_inst(6.92, inside=False)] * 60)
    b = dkb._size_bands(inst)
    assert 1.4 <= b["ref_pt"] <= 1.65
    assert 3.05 < b["callout_pt"] < 5.9
    assert 1.03 < b["device_text_below_pt"] < 1.28
    for size, inside, kind in ((1.03, True, "device_text"), (1.28, True, "nameplate"), (3.05, True, "nameplate"),
                               (5.96, False, "callout"), (1.65, False, "nameplate"), (3.05, False, "callout")):
        assert dkb._kind(_inst(size, inside), b) == kind, (size, inside)
    # the same relative rule on a drawing drawn at twice the scale
    b2 = dkb._size_bands([dict(i, size=2 * i["size"]) for i in inst])
    assert dkb._kind(_inst(2.06), b2) == "device_text" and dkb._kind(_inst(6.1), b2) == "nameplate"


def test_size_bands_without_device_text():
    b = dkb._size_bands([_inst(1.47)] * 20 + [_inst(1.28)] * 3 + [_inst(1.65)] * 7 + [_inst(3.05)] * 30)
    assert dkb._kind(_inst(1.28), b) == "nameplate"


def _rec(tag, *pts):
    return {"tag": tag, "family": dkb.family_of(tag),
            "instances": [{"center": list(p), "kind": "nameplate", "stray": False} for p in pts]}


def test_groups_columns_rows_and_gaps():
    recs = [_rec(f"CB1{i}", (157, 277 + 8.5 * (i - 1))) for i in range(1, 7)]           # two rails, one column
    recs += [_rec(f"CB2{i}", (157, 408 + 8.5 * (i - 1))) for i in range(1, 7)]
    recs += [_rec("PS11", (421, 297)), _rec("PS21", (445, 297)), _rec("PS12", (480, 297)), _rec("PS22", (527, 297)),
             _rec("PS13", (431, 237)), _rec("PS23", (475, 237))]
    recs += [_rec("SB01", (442, 385)), _rec("SB02", (442, 518)), _rec("SB03", (499, 385)), _rec("SB04", (499, 518))]
    recs += [_rec("334CBP01", (532, 386), (552, 410)), _rec("334CBP02", (532, 430), (552, 454)),
             _rec("335CBP01", (474, 386), (494, 410)), _rec("335CBP02", (474, 430), (494, 454))]
    recs.append({"tag": "CB41", "family": "CB", "instances": [{"center": [526, 214], "kind": "device_text",
                                                               "stray": False}]})
    got = {tuple(g["order"]): g["axis"] for g in dkb._groups("v", recs)}
    assert got[tuple(f"CB1{i}" for i in range(1, 7))] == "y"
    assert got[tuple(f"CB2{i}" for i in range(1, 7))] == "y"
    assert got[("PS11", "PS21", "PS12", "PS22")] == "x"
    assert got[("PS13", "PS23")] == "x"
    assert got[("335CBP01", "335CBP02")] == "y" and got[("334CBP01", "334CBP02")] == "y"
    assert ("SB01", "SB03") in got and ("SB02", "SB04") in got
    assert not any("CB41" in o for o in got)
    ids = [g["id"] for g in dkb._groups("v", recs)]
    assert len(ids) == len(set(ids)) and "v-CB-1" in ids


def test_view_outline_is_the_long_frame_not_the_page_border():
    segs = [(28, 15, 28, 827), (28, 827, 1176, 827),                       # page border
            (120, 180, 120, 640), (310, 180, 310, 640), (120, 180, 310, 180), (120, 650, 310, 650),
            (60, 300, 150, 300), (200, 300, 200, 330)]                    # leader line, small detail
    box = dkb._view_outline(np.array(segs, dtype=float), (0, 130, 350, 842), 842)
    assert box == (120.0, 180.0, 310.0, 650.0)
    assert dkb._view_outline(np.zeros((0, 4)), (0, 0, 10, 10), 842) is None


def _line(text, x0, y0, size=7.4, w=None):
    return {"text": text, "bbox": (x0, y0, x0 + (w or len(text) * 4.0), y0 + size), "size": size, "rot": 0}


def test_nameplate_table_rows():
    lines = [_line("DESCRIPTION", 100, 84), _line("NAMEPLATE TYPE", 171, 84), _line("NAMEPLATE SIZE", 266, 84),
             _line("LETTER SIZE", 372, 84), _line("QTY", 439, 84),
             _line("DESCRIPTION", 513, 84), _line("NAMEPLATE TYPE", 584, 84), _line("NAMEPLATE SIZE", 678, 84),
             _line("LETTER SIZE", 780, 84), _line("QTY", 854, 84)]
    for k, (a, b) in enumerate([("PS11", "FILTER 1"), ("CB61", "X-ALM")]):
        y = 102 + 17.5 * k
        lines += [_line(a, 100, y), _line("ADHESIVE LABEL", 172, y), _line('20MM X 10MM (0.8" X 0.4")', 266, y - 1),
                  _line('6MM (0.25")', 372, y - 1), _line("2", 444, y),
                  _line(b, 513, y), _line("KLM LABEL", 584, y), _line('44MM X 9MM (1.72" X 0.35")', 679, y - 1),
                  _line('4MM (0.15")', 780, y - 1), _line("2", 859, y)]
    lines.append(_line("NOTES: ALL LABELS WHITE", 100, 160))
    rows = {r["tag"]: r for r in dkb._nameplates(16, lines, 1191)}
    assert set(rows) == {"PS11", "CB61", "FILTER1", "X-ALM"}
    assert rows["PS11"] == {"tag": "PS11", "display": "PS11", "type": "ADHESIVE LABEL", "size": "20MM X 10MM",
                            "w_mm": 20, "h_mm": 10, "letter": "6MM", "qty": 2, "page": 16}
    assert rows["FILTER1"]["display"] == "FILTER 1" and rows["X-ALM"]["w_mm"] == 44 and rows["X-ALM"]["h_mm"] == 9


def test_wire_colours_from_the_legend_table():
    lines = [_line("Power", 143, 526, 7.9), _line("Colour", 222, 526, 7.9),
             _line("Black (BK)", 216, 550, 7.9), _line("Brown (BN)", 214, 589, 7.9), _line("230V AC", 136, 591, 7.9),
             _line("Green/Yellow (GN/YE)", 195, 634, 7.9), _line("Black (BK)", 216, 679, 7.9),
             _line("24V DC", 139, 704, 7.9), _line("White (WH)", 214, 718, 7.9), _line("Green (GN)", 214, 748, 7.9),
             _line("Orange (OR)", 212, 763, 7.9), _line("Alarm Wiring", 129, 773, 7.9),
             _line("White (WH)", 214, 773, 7.9), _line("Black (BK)", 216, 783, 7.9)]
    rules = np.array([(126.9, y, 383.6, y) for y in (534.2, 662.9, 762.1, 791.8)], dtype=float)
    assert dkb._wire_colours(lines, rules) == {"230VAC": ["BK", "BN", "GN/YE"], "24VDC": ["BK", "WH", "GN"],
                                               "ALARM": ["OR", "WH", "BK"]}
    assert dkb._wire_colours([_line("NOTES", 10, 10)], rules) is None


# ------------------------------------------------------------------ synthetic demo drawing (legacy engine input)
def test_demo_drawing_is_not_a_real_drawing_set(tmp_path):
    assert is_real_drawing(config.DEMO_GA) is False
    kb = build_kb(config.DEMO_GA, cache_dir=tmp_path)
    assert kb["schema"] == "eagle-eye-kb/1" and kb["views"] == {} and kb["groups"] == []
    assert kb["cabinet"] == "EE-DEMO-01"
    assert kb["wire_colours"] == dkb.DEFAULT_WIRE_COLOURS
    assert any("not a real" in w for w in kb["stats"]["warnings"])


def test_is_real_drawing_never_raises(tmp_path):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    assert is_real_drawing(junk) is False
    assert is_real_drawing(tmp_path / "missing.pdf") is False


def test_cache_round_trip_and_version_bump(tmp_path):
    a = build_kb(config.DEMO_GA, cache_dir=tmp_path)
    b = build_kb(config.DEMO_GA, cache_dir=tmp_path)
    assert a["stats"]["cache"] == "miss" and b["stats"]["cache"] == "hit"
    a["stats"].pop("cache"), b["stats"].pop("cache")
    assert a == b
    f = tmp_path / f"{a['pdf_sha256']}.json"
    stale = json.loads(f.read_text(encoding="utf-8"))
    stale["kb_version"] = "0.0"
    f.write_text(json.dumps(stale), encoding="utf-8")
    assert build_kb(config.DEMO_GA, cache_dir=tmp_path)["stats"]["cache"] == "miss"
    assert build_kb(config.DEMO_GA, cache_dir=tmp_path, refresh=True)["stats"]["cache"] == "miss"


# ------------------------------------------------------------------ Emerson 13GE03331 (real drawing set)
@pytest.fixture(scope="module")
def real_kb(tmp_path_factory):
    if not REAL.exists():
        pytest.skip("Emerson drawing set not available (data/emerson/)")
    return build_kb(REAL, cache_dir=tmp_path_factory.mktemp("kb"), refresh=True)


def _group(kb, view, first):
    return next((g for g in kb["groups"] if g["view"] == view and g["order"][0] == first), None)


@needs_real
def test_real_page_kinds_and_cabinet(real_kb):
    kinds = {p["page"]: p["kind"] for p in real_kb["pages"]}
    assert real_kb["cabinet"] == "13GE03331"
    assert kinds[1] == "legend" and kinds[2] == "abbreviations" and kinds[3] == "outline" and kinds[4] == "top_view"
    assert kinds[5] == kinds[6] == "ga"
    assert kinds[7] == kinds[8] == "bom"
    assert all(kinds[p] == "power" for p in (9, 10, 11, 12))
    assert kinds[13] == "network" and kinds[14] == "grounding" and kinds[15] == "earthing"
    assert kinds[16] == kinds[17] == "nameplate"
    assert real_kb["stats"]["timing_s"]["total"] < 20


@needs_real
def test_real_views(real_kb):
    views = real_kb["views"]
    assert {"front", "rear", "left", "right"} <= set(views)
    assert views["front"]["page"] == views["left"]["page"] == views["right"]["page"] == 5
    assert views["rear"]["page"] == 6 and views["rear"]["title"] == "REAR INSIDE VIEW"
    for name, v in views.items():
        x0, y0, x1, y1 = v["bbox"]
        assert 150 < x1 - x0 < 250 and 400 < y1 - y0 < 560, name     # one cabinet outline per view
        for r in v["tags"]:
            assert x0 - 5 <= r["center"][0] <= x1 + 5 and y0 - 5 <= r["center"][1] <= y1 + 5, (name, r["tag"])
    fl, fr = view_tags(real_kb, "left"), view_tags(real_kb, "front")
    assert {"CB11", "CB16", "DS1", "XP11", "XG11"} <= set(fl) and "CB11" not in fr
    assert {"PS11", "DS11", "334CBP01", "13CSLS03334", "TERM1F"} <= set(fr)
    assert {"CB61", "CB79", "X-ALM", "TS1"} <= set(view_tags(real_kb, "right"))
    assert {"331CBP01", "333CBP08", "13CSLS03331", "TERM3R", "CL2"} <= set(view_tags(real_kb, "rear"))
    assert any(c["tag"] == "PS11" for c in views["front"]["callouts"])      # leader-list text: membership only


@needs_real
def test_real_positions_and_instances(real_kb):
    ps11 = view_tags(real_kb, "front")["PS11"]
    assert abs(ps11["center"][0] - 421) < 3 and abs(ps11["center"][1] - 297) < 3
    assert ps11["label"] == {"w_mm": 20, "h_mm": 10, "qty": 2}
    cb11 = view_tags(real_kb, "left")["CB11"]
    kinds = sorted(i["kind"] for i in cb11["instances"])
    assert kinds == ["device_text", "nameplate"]
    assert abs(cb11["center"][0] - 157) < 2 and cb11["device_bbox"] is not None
    cbp = view_tags(real_kb, "front")["334CBP01"]
    assert any(i["rot"] == 90 for i in cbp["instances"])
    ds11 = view_tags(real_kb, "front")["DS11"]
    assert len([i for i in ds11["instances"] if i["kind"] == "nameplate"]) == 2


@needs_real
def test_real_label_expected(real_kb):
    front = view_tags(real_kb, "front")
    for t in ("CB41", "CB42", "CB51", "CB52"):
        assert front[t]["label_expected"] is False, t
        assert all(i["kind"] == "device_text" for i in front[t]["instances"])
    left = view_tags(real_kb, "left")
    for t in ["CB1%d" % i for i in range(1, 7)]:
        assert left[t]["label_expected"] is True, t
    for t in ("PS11", "DS11", "334CBP01", "13CSLS03334"):
        assert front[t]["label_expected"] is True, t
    assert set(real_kb["stats"]["label_expected_false"]) == {"CB41", "CB42", "CB51", "CB52"}


@needs_real
def test_real_group_orders(real_kb):
    expect = [
        ("left", "y", ["CB11", "CB12", "CB13", "CB14", "CB15", "CB16"]),
        ("left", "y", ["CB21", "CB22", "CB23", "CB24", "CB25", "CB26"]),
        ("right", "y", [f"CB6{i}" for i in range(1, 10)] + [f"CB7{i}" for i in range(1, 10)]),
        ("front", "x", ["PS11", "PS21", "PS12", "PS22"]),
        ("front", "x", ["DS11", "DS12", "DS21", "DS22"]),
        ("front", "y", ["334CBP01", "334CBP02", "334CBP03"]),
        ("front", "y", ["335CBP01", "335CBP02"]),
        ("rear", "y", [f"331CBP0{i}" for i in range(1, 9)]),
        ("rear", "y", [f"332CBP0{i}" for i in range(1, 7)]),
        ("rear", "y", [f"333CBP0{i}" for i in range(1, 9)]),
    ]
    for view, axis, order in expect:
        g = _group(real_kb, view, order[0])
        assert g is not None, (view, order[0])
        assert g["order"] == order and g["axis"] == axis, g


@needs_real
def test_real_nameplates_and_coverage(real_kb):
    np_ = {r["tag"]: r for r in real_kb["nameplates"]}
    assert len(np_) >= 110
    assert np_["PS11"]["w_mm"] == 20 and np_["PS11"]["h_mm"] == 10 and np_["PS11"]["qty"] == 2
    assert np_["FILTER1"]["display"] == "FILTER 1" and np_["X-ALM"]["type"] == "KLM LABEL"
    assert {"331CBP08", "13CSLS03335", "13RDEW-40A870GI", "ALM-FSW2", "CB79"} <= set(np_)
    cov = real_kb["stats"]["nameplate_coverage"]
    assert cov["total"] == len(np_)
    assert cov["ratio_placed"] >= 0.85 and cov["ratio_with_explained"] >= 0.9
    assert not cov["unexplained"]
    assert "outline" in cov["explained"]["FILTER1"]                      # door-mounted, drawn on the outline page
    vocab = set(real_kb["vocabulary"])
    assert set(np_) <= vocab and {"CB11", "CB41", "XP12"} <= vocab        # GA-only and schematic-only tags
    assert real_kb["devices"]["PS11"]["views"] == ["front"] and 9 in real_kb["devices"]["PS11"]["pages"]
    assert real_kb["devices"]["CB41"]["label_expected"] is False


@needs_real
def test_real_connections_and_wire_colours(real_kb):
    conns = {(c["from"], c["to"]) for c in real_kb["connections"]}
    assert ("CB12-2", "PS12-L") in conns and ("CB13-4", "PS13-N") in conns
    assert ("CB14-4", "X-FSW1-3") in conns and ("XG11-2", "PS12-E") in conns
    links = {tuple(sorted(link)) for link in real_kb["device_links"]}
    for a, b in (("CB12", "PS12"), ("CB14", "X-FSW1"), ("CB15", "CL1"), ("CB16", "XP11")):
        assert tuple(sorted((a, b))) in links, (a, b)
    for c in real_kb["connections"]:
        assert 0 < c["confidence"] <= 0.75
        if not (c["from_pin"] and c["to_pin"]):
            assert c["confidence"] <= 0.5
    assert real_kb["wire_colours"] == {"230VAC": ["BK", "BN", "GN/YE"], "24VDC": ["BK", "WH", "GN"],
                                       "ALARM": ["OR", "WH", "BK"]}


@needs_real
def test_real_is_real_drawing_and_crops(real_kb, tmp_path):
    assert is_real_drawing(REAL) is True
    im = drawing_crop(real_kb, REAL, "front", tag="PS11", dpi=200)
    assert isinstance(im, Image.Image) and im.width > 50 and im.height > 30
    im2 = drawing_crop(real_kb, REAL, "rear", bbox=[430, 280, 460, 320], margin_pt=4, dpi=100)
    assert im2.size == (pytest.approx(38 / 72 * 100, abs=2), pytest.approx(48 / 72 * 100, abs=2))
    with pytest.raises(KeyError):
        drawing_crop(real_kb, REAL, "front", tag="CB11")
    page = dkb.render_page(REAL, 5, dpi=36, cache_dir=tmp_path)
    assert page.size == (596, 421)
    assert dkb.render_page(REAL, 5, dpi=36, cache_dir=tmp_path).size == page.size     # from the PNG cache
    out = dkb.debug_png(real_kb, REAL, 6, tmp_path / "p6.png", zoom=1.0)
    assert Path(out).exists()
