"""Wire colour by circuit class: the colour rule (wire_rules.py), the drawing's circuit classes, the colour classifier
(vision/wire_colour.py) and the real-engine COLOUR check, on synthetic drawings and synthetic photos."""
import cv2
import numpy as np
import pytest

import consensus
import wire_rules
from checks import CHECKS, Context
from vision.wire_colour import classify

# ------------------------------------------------------------------ the colour rule
LEGEND_KB = {"wire_colours": {"230VAC": ["BK", "BN", "GN/YE"], "24VDC": ["BK", "WH", "GN"], "ALARM": ["OR", "WH", "BK"]},
             "stats": {"wire_colours_page": 3}}


def test_rule_precedence_legend_then_profile_then_nothing():
    r = wire_rules.rules(LEGEND_KB, profile="nfpa-79")
    assert r["source"] == "drawing legend (page 3)"                   # the cabinet's own legend beats any profile
    assert wire_rules.allowed(r, "AC") == ["BK", "BN"]                 # green-and-yellow is never an AC colour
    assert wire_rules.allowed(r, "DC") == ["BK", "WH", "GN"]           # plain green stays where the legend lists it
    assert wire_rules.allowed(r, "ALARM") == ["OG", "WH", "BK"]        # 'OR' spelled as IEC 60757 'OG'
    assert wire_rules.allowed(r, "PE") == ["GN/YE", "GN"]
    p = wire_rules.rules({"wire_colours": None}, profile="nfpa-79")
    assert p["source"].startswith("profile: NFPA 79") and p["notes"]   # a profile always names the edition to check
    assert wire_rules.allowed(p, "DC") == ["BK", "BU", "WH/BU"]
    none = wire_rules.rules({"wire_colours": None})
    assert none["source"] is None and "only the universal rule" in none["notes"][0]
    assert wire_rules.allowed(none, "PE") == ["GN/YE", "GN"]          # the universal earth rule still holds
    assert wire_rules.rules({}, profile="no-such")["source"] is None


def test_unnamed_legend_groups_are_not_filed_under_a_neighbour():
    r = wire_rules.rules({"wire_colours": {"230VAC": ["BK", "BN"], "UNNAMED": ["RD"]}, "stats": {}})
    assert r["classes"] == {"AC": ["BK", "BN"]} and "RD" in r["notes"][0]


@pytest.mark.parametrize("key, cls", [("230VAC", "AC"), ("110 V AC", "AC"), ("24VDC", "DC"), ("24 V DC", "DC"),
                                      ("ALARM", "ALARM"), ("UNNAMED", None), ("SPARE", None)])
def test_legend_rows_map_to_circuit_classes(key, cls):
    assert wire_rules.legend_class(key) == cls


def test_profiles_are_complete_and_keep_green_and_yellow_for_earth():
    profs = wire_rules.profiles()
    assert {"iec-60204-1", "nfpa-79", "iec-60445", "is-732-legacy", "as-nzs-3000-legacy"} <= set(profs)
    valid = {"BK", "BN", "RD", "OG", "YE", "GN", "BU", "VT", "GY", "WH", "PK", "TQ", "GN/YE", "WH/BU"}
    for pid, p in profs.items():
        assert p["name"] and p["verify"] and p["edition"], pid
        assert "GN/YE" in p["classes"]["PE"] or "GN" in p["classes"]["PE"], pid
        for cls, codes in p["classes"].items():
            assert set(codes) <= valid, (pid, cls)
            assert cls == "PE" or "GN/YE" not in codes, (pid, cls)
    # the same colour means different things: black is a phase (IEC 60445) but the neutral in India's legacy scheme
    assert "BK" in profs["iec-60445"]["classes"]["AC"] and "neutral" in profs["is-732-legacy"]["meaning"]["BK"]
    assert [p["id"] for p in wire_rules.profile_list()] == list(profs)


# ------------------------------------------------------------------ circuit classes from the drawing's wiring
def _wiring_kb():
    conn = lambda a, ap, b, bp, page=11: {"from": f"{a}-{ap}" if ap else a, "to": f"{b}-{bp}" if bp else b,  # noqa: E731
                                          "from_device": a, "from_pin": ap, "to_device": b, "to_pin": bp, "page": page}
    return {"vocabulary": ["CB11", "CB12", "CB61", "CB62", "PS11", "PS12", "X1", "X3", "XP11", "DCG", "IPE", "X-ALM",
                           "TS1", "D13", "DS11"],
            "connections": [conn("CB11", "2", "PS11", "L"), conn("CB11", "4", "PS11", "N"), conn("PS11", "+", "X1", None),
                            conn("PS11", "-", "DCG", None), conn("CB61", "94", "CB62", None, 12),
                            conn("X-ALM", None, "PS11", None, 12), conn("X-ALM", None, "TS1", "5", 12),
                            conn("D13", None, "DS11", None, 13), conn("PS12", "E", "XP11", "3")],
            "buses": [{"page": 11, "members": ["CB11-1", "CB12-1", "XP11-1"], "devices": ["CB11", "CB12", "XP11"]},
                      {"page": 11, "members": ["PS12--", "X3", "X3-1"], "devices": ["PS12", "X3"]}]}


def test_circuit_classes_spread_from_pin_names_and_stop_at_supplies_and_earth():
    cc = wire_rules.circuit_classes(_wiring_kb())
    n = cc["nodes"]
    assert n["CB11-2"] == n["CB11-1"] == n["XP11-1"] == n["CB12-1"] == "AC"   # through the breaker pole and the bus
    assert n["CB12-2"] == "AC"                                            # the other end of CB12's pole
    assert n["PS11-+"] == n["X1@11"] == "DC" and n["X3-1"] == "DC"          # a supply's output side
    assert n["DCG@11"] == "PE" and n["PS12-E"] == "PE"
    assert n["CB61-94"] == n["CB62@12"] == "ALARM"                          # fault-signalling contacts 91-98
    assert n["PS11@12"] == "ALARM" and n["TS1-5"] == "ALARM"                 # the alarm sheet's device references
    assert "D13@13" not in n and "XP11-3" not in n                           # no seed: no class, nothing guessed
    assert cc["devices"]["X1"] == "DC" and cc["devices"]["PS11"] == "ALARM"   # PS11 without a pin: the alarm sheet
    assert cc["stats"]["conflicts"] == 0 and cc["stats"]["wires"] == 9


def test_conflicting_seeds_leave_a_circuit_unclassified():
    kb = {"vocabulary": ["X5", "PS11"], "connections": [
        {"from_device": "PS11", "from_pin": "L", "to_device": "X5", "to_pin": "1", "page": 1},
        {"from_device": "PS11", "from_pin": "+", "to_device": "X5", "to_pin": "1", "page": 1}]}
    cc = wire_rules.circuit_classes(kb)
    assert "X5-1" not in cc["nodes"] and cc["stats"]["conflicts"] == 1
    assert wire_rules.wire_class(["X5-1", "X5-2"], cc)[0] is None


def test_wire_class_of_ferrule_ends():
    cc = wire_rules.circuit_classes(_wiring_kb())
    assert wire_rules.wire_class([{"device": "CB12", "pin": "2"}, {"device": "XP11", "pin": "9"}], cc)[0] == "AC"
    cls, why = wire_rules.wire_class(["PS11-+", "X1-7"], cc)
    assert cls == "DC" and "pin name" in why
    assert wire_rules.wire_class(["X1-7", "X1-8"], cc)[0] == "DC"           # undrawn terminals: their strip's class
    assert wire_rules.wire_class(["X3-1", "IPE"], cc) == ("PE", "IPE is an earth point, so this is the earth wire")
    assert wire_rules.wire_class(["PS11-L", "PS11-+"], cc)[0] is None        # a wire cannot be on both sides
    assert wire_rules.wire_class(["Q1-1", "Q2-1"], cc)[0] is None            # not in the drawing at all


def test_vocabulary_names_with_dashes_split_correctly():
    known = frozenset({"X-FSW1", "SPD1", "PS12"})
    assert wire_rules._split("X-FSW1-3", known) == ("X-FSW1", "3")
    assert wire_rules._split("SPD1-UNPR-L", known) == ("SPD1", "UNPR-L")
    assert wire_rules._split("PS12--", known) == ("PS12", "-")
    assert wire_rules._split("X-FSW1", known) == ("X-FSW1", None)


# ------------------------------------------------------------------ the colour classifier
INS = {"BK": (28, 28, 30), "BN": (115, 68, 38), "RD": (200, 32, 32), "OG": (238, 122, 24), "YE": (240, 208, 30),
       "GN": (24, 138, 62), "BU": (24, 72, 178), "VT": (122, 52, 160), "WH": (238, 238, 232), "TQ": (32, 178, 188)}
PLATE = 168


def scene(code, cast=(1.0, 1.0, 1.0), text="CB12-2/PS12-L", wire_px=34, text_h=16, size=(360, 640), seed=0,
          sides=("wire", "wire"), sleeve=(245, 245, 240)):
    """A wire ferrule on a horizontal wire over a galvanised backplate, seen through a colour cast."""
    rng = np.random.default_rng(seed)
    H, W = size
    img = np.full((H, W, 3), float(PLATE)) + rng.normal(0, 5, (H, W, 1))
    cy = H // 2
    y0, y1 = cy - wire_px // 2, cy + wire_px // 2
    prof = np.linspace(-1, 1, y1 - y0)
    shade = (0.78 + 0.22 * np.sqrt(np.clip(1 - prof ** 2, 0, 1)))[:, None, None]
    if code == "GN/YE":
        band = np.zeros((y1 - y0, W, 3))
        band[: int(0.4 * (y1 - y0))], band[int(0.4 * (y1 - y0)):] = INS["YE"], INS["GN"]
    else:
        band = np.tile(np.array(INS[code], float), (y1 - y0, W, 1))
    font, scale = cv2.FONT_HERSHEY_SIMPLEX, text_h / 22.0
    (tw, th), base = cv2.getTextSize(text, font, scale, 2)
    tx0 = W // 2 - tw // 2
    sl0, sl1 = tx0 - int(0.12 * tw), tx0 + tw + int(0.12 * tw)
    keep = np.ones(W, bool)
    if sides[0] != "wire":
        keep[:sl0] = False
    if sides[1] != "wire":
        keep[sl1:] = False
    img[y0:y1][:, keep] = (band * shade)[:, keep]
    img[cy - int(0.65 * wire_px): cy + int(0.65 * wire_px), sl0:sl1] = sleeve
    u8 = np.clip(img, 0, 255).astype(np.uint8)
    cv2.putText(u8, text, (tx0, cy + th // 2), font, scale, (20, 20, 20), 2, cv2.LINE_AA)
    box = [tx0, cy - th // 2 - 1, tx0 + tw, cy + th // 2 + base // 2]
    out = u8.astype(np.float64) * np.array(cast) + rng.normal(0, 4, u8.shape)
    return cv2.GaussianBlur(np.clip(out, 0, 255).astype(np.uint8), (3, 3), 0.8), box


CASTS = [(1.0, 1.0, 1.0), (1.12, 1.0, 0.78), (0.85, 1.0, 1.18)]


@pytest.mark.parametrize("code", list(INS) + ["GN/YE"])
def test_classifier_names_insulation_colours_through_colour_casts(code):
    for k, cast in enumerate(CASTS):
        img, box = scene(code, cast, seed=k)
        r = classify(img, box)
        assert r and r["code"] == code, (code, cast, r)
        # a white wire beside a white sleeve is the one colour judged less surely (it could be a long sleeve)
        assert r["conf"] >= (0.6 if code == "WH" else 0.8) and r["white"] == "ferrule sleeve"


def _slant(img, box, deg):
    """The scene turned by ``deg`` about the print's centre: (image, upright bounding box, the print's quadrilateral as
    OCR reports it)."""
    c = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    M = cv2.getRotationMatrix2D(c, deg, 1.0)
    out = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderValue=(PLATE,) * 3)
    q = cv2.transform(np.float32([[[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]]), M)[0]
    return out, [float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max())], q.tolist()


@pytest.mark.parametrize("deg", [-30, -15, 20, 35])
@pytest.mark.parametrize("code", ["BN", "GN/YE", "BU", "RD"])
def test_classifier_follows_a_slanted_wire(code, deg):
    img, box = scene(code, seed=7, size=(480, 640))
    img, box, quad = _slant(img, box, deg)
    r = classify(img, box, quad=quad)                                    # OCR's quadrilateral gives the slant
    assert r and r["code"] == code and r["sleeve"] == "found", (code, deg, r)
    assert abs(((r["axis_deg"] + deg) + 90) % 180 - 90) < 3        # the sampled direction follows the slant


@pytest.mark.parametrize("deg", [-12, 15])
def test_without_a_quadrilateral_the_print_strokes_give_the_slant(deg):
    img, box = scene("BN", seed=8, size=(480, 640))
    img, box, _q = _slant(img, box, deg)
    r = classify(img, box)
    assert r and r["code"] == "BN" and abs(((r["axis_deg"] + deg) + 90) % 180 - 90) < 6


def test_classifier_reads_vertical_ferrules_and_yellow_sleeves():
    img, box = scene("BU", (1.1, 1.0, 0.85), seed=3)
    rot = np.ascontiguousarray(np.rot90(img, -1))
    H = img.shape[0]
    r = classify(rot, [H - box[3], box[0], H - box[1], box[2]], 90)
    assert r and r["code"] == "BU"
    img, box = scene("BN", sleeve=(235, 200, 40), seed=4)                 # a yellow sleeve is not a white reference
    r = classify(img, box)
    assert r and r["code"] == "BN" and r["white"] == "grey world"


def test_a_green_and_yellow_wire_showing_one_stripe_at_one_end_is_still_green_and_yellow():
    img, box = scene("GN/YE", seed=5)
    cy = img.shape[0] // 2
    left = slice(0, box[0] - 30)
    img[cy - 17: cy + 17, left] = cv2.GaussianBlur(np.tile(np.array(INS["GN"], np.uint8), (34, box[0] - 30, 1)), (3, 3), 0)
    r = classify(img, box)
    assert r and r["code"] == "GN/YE" and "only the green one" in r["reason"] and r["conf"] >= 0.8


def test_classifier_makes_no_claim_without_a_distinct_wire():
    img, box = scene("BK", sides=("plate", "plate"))
    assert classify(img, box) is None                                    # sleeve on the backplate: no wire to judge
    img, box = scene("RD", sides=("wire", "plate"))
    r = classify(img, box)                                               # one end runs into a surface
    assert r and r["code"] == "RD" and "surface" in r["reason"] and r["conf"] < 0.97
    img, box = scene("GN")
    r = classify(img, [560, 170, 660, 190])                              # a print running off the photo
    assert r is None or r["code"] == "GN"


def test_white_wires_count_only_when_the_white_runs_well_past_any_sleeve():
    img, box = scene("WH", seed=2)
    r = classify(img, box)
    assert r and r["code"] == "WH" and r["conf"] >= 0.6 and "white wire" in r["reason"]


# ------------------------------------------------------------------ the COLOUR check
def _ferrule(box, a, ap, b, bp):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return {"raw": f"{a}-{ap}/{b}-{bp}", "norm": f"{a}-{ap}/{b}-{bp}", "box": [float(v) for v in box], "center": [cx, cy],
            "conf": 0.98, "passes": 2, "rot": 0, "from": {"device": a, "pin": ap, "known": True},
            "to": {"device": b, "pin": bp, "known": True}, "partial": False}


def _colour(code, ends=("CB12", "2", "PS12", "L"), kb=None, profile=None, **kw):
    img, box = scene(code, **kw)
    kb = dict(_wiring_kb(), **(kb if kb is not None else LEGEND_KB))
    photo = {"rgb": img, "size": [img.shape[1], img.shape[0]], "sha": "s", "ignore": [], "quality": {"score": 1}}
    reg = {"ferrules": [_ferrule(box, *ends)], "fits": [], "reads": [], "unknown": [], "in_view": {}}
    ctx = Context(kb, "x.pdf", photo, [], reg, cfg={"colour_profile": profile})
    found = CHECKS["COLOUR"]().run(ctx)
    return found, ctx


def test_colour_check_passes_a_legend_colour_and_cites_the_rule():
    found, ctx = _colour("BN")
    [f] = found
    assert f["id"] == "COL-CB12-2/PS12-L" and f["status"] == "OK" and f["wire_class"] == "AC"
    assert f["expected"] == "BK/BN (AC mains)" and "drawing legend (page 3)" in f["evidence"][-1]
    assert f["swatch"].startswith("#") and f["box"] and len(f["sample_boxes"]) >= 2
    rule = ctx.facts["wire_rule"]
    assert rule["source"] == "drawing legend (page 3)" and rule["judged"] == 1 and rule["circuits"]["conflicts"] == 0
    assert "1 of 1" in ctx.facts["colour_note"]


def test_green_and_yellow_on_a_live_wire_is_a_candidate_fault_under_any_rule():
    for kb in (LEGEND_KB, {"wire_colours": None}):
        [f], _ = _colour("GN/YE", kb=kb)
        assert f["status"] == "CANDIDATE_FAULT" and f["rule"] == "COLOUR.reserved_green_yellow"
        assert f["strength"] == "strong"
        [item] = consensus.decide([f], {}, agent_on=False)
        assert item["result"] == "REVIEW"                                  # a colour alone never FAILs a cabinet
    [ok], _ = _colour("GN/YE", ends=("PS12", "E", "XP11", "3"))
    assert ok["status"] == "OK" and ok["wire_class"] == "PE"


def test_a_colour_outside_the_class_rule_is_referred_with_the_rule_it_breaks():
    [f], _ = _colour("RD")
    assert f["status"] == "CANDIDATE_FAULT" and f["rule"] == "COLOUR.not_allowed" and f["strength"] == "weak"
    assert "allows black, brown" in f["evidence"][-1]
    [d], _ = _colour("WH", ends=("PS11", "+", "X1", "7"))                 # white is a DC colour in this legend
    assert d["status"] == "OK" and d["wire_class"] == "DC"


def test_no_rule_means_only_the_universal_rule_and_a_profile_must_be_chosen_explicitly():
    found, ctx = _colour("RD", kb={"wire_colours": None})
    assert found == [] and ctx.facts["wire_rule"]["source"] is None
    assert "universal green-and-yellow rule only" in ctx.facts["colour_note"]
    [f], ctx = _colour("BU", ends=("PS11", "+", "X1", "7"), kb={"wire_colours": None}, profile="nfpa-79")
    assert f["status"] == "OK" and ctx.facts["wire_rule"]["profile"] == "nfpa-79"
    # the same black DC wire: NFPA 79 allows black for DC power, IEC 60445 marks DC brown / grey / blue
    [us], _ = _colour("BK", ends=("PS11", "+", "X1", "7"), kb={"wire_colours": None}, profile="nfpa-79")
    [eu], _ = _colour("BK", ends=("PS11", "+", "X1", "7"), kb={"wire_colours": None}, profile="iec-60445")
    assert us["status"] == "OK" and eu["status"] == "CANDIDATE_FAULT" and eu["expected"] == "BN/GY/BU (DC distribution)"


def test_unmeasurable_or_unclassified_wires_get_no_item_but_are_counted():
    found, ctx = _colour("BK", ends=("Q1", "1", "Q2", "1"))               # ends the drawing does not wire, BK in rule
    assert found == [] and ctx.facts["wire_rule"]["no_rule"] == 1
    found, ctx = _colour("BK", sides=("plate", "plate"))                  # no wire visible next to the sleeve
    assert found == [] and ctx.facts["wire_rule"]["not_measured"] == 1
    assert "not measurable" in ctx.facts["colour_note"]
    found, ctx = _colour("VT", ends=("Q1", "1", "Q2", "1"))               # a colour no circuit of the legend uses
    assert found[0]["rule"] == "COLOUR.not_in_rule" and found[0]["status"] == "CANDIDATE_FAULT"
