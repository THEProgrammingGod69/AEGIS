"""Drawing-guided reading of small labels (vision/guided.py) on a synthetic cabinet with a fake reader: what is looked
for, what is accepted (only the exact tag, at its own spot, read confidently), and that it never invents a fault."""
import numpy as np
import pytest

import consensus
from checks import Context, run_checks
from vision import guided
from vision.register import register

S, T = 10.0, (100.0, 50.0)          # synthetic photo = S * drawing + T
TAGS = {"PS11": (100, 100), "PS12": (140, 100), "PS13": (180, 100), "DS11": (100, 150), "DS12": (140, 150),
        "TS1": (180, 150), "CB21": (100, 200), "CB22": (140, 200)}


def _kb():
    tags = [{"tag": t, "family": t[:2], "center": list(c), "label_expected": True, "device_bbox": None, "label": None,
             "instances": [{"bbox": [c[0] - 2, c[1] - 0.7, c[0] + 2, c[1] + 0.7], "center": list(c), "rot": 0,
                            "size_pt": 1.6, "kind": "nameplate", "stray": False}]} for t, c in TAGS.items()]
    return {"cabinet": "TEST-01", "views": {"front": {"page": 1, "title": "FRONT", "bbox": [80, 80, 200, 220],
                                                      "region": [80, 80, 200, 220], "tags": tags, "callouts": []}},
            "vocabulary": sorted(TAGS), "groups": [], "device_links": [], "connections": [], "stats": {}}


def _photo():
    return {"rgb": np.zeros((2400, 2400, 3), np.uint8), "sha": "synthetic", "size": [2400, 2400], "ignore": [],
            "quality": {"score": 1.0, "issues": []}, "name": "synthetic.jpg"}


def _at(tag):
    c = TAGS[tag]
    return (S * c[0] + T[0], S * c[1] + T[1])


def _tok(text, xy, passes=2, conf=0.99, w=40, h=8):
    x, y = xy
    return {"text": text, "norm": text.upper(), "box": [x - w, y - h, x + w, y + h], "conf": conf, "rot": 0,
            "passes": passes, "support": ["full", "tile"][:passes]}


def reader(labels, conf=0.95, calls=None):
    """Fake magnified reader: returns the labels whose centre lies in the window, as OCR tokens."""
    def read(photo, box, rotations=(0,), scale=3.0):
        if calls is not None:
            calls.append((tuple(round(v) for v in box), scale))
        out = []
        for text, xy in labels:
            if box[0] <= xy[0] <= box[2] and box[1] <= xy[1] <= box[3]:
                out.append(_tok(text, xy, passes=1, conf=conf))
        return out
    return read


def _no_small(*a, **kw):
    raise AssertionError("small print is only for photos that could not be placed")


def test_targets_are_the_labels_of_placed_views_without_a_certain_read():
    tokens = [_tok(t, _at(t)) for t in TAGS if t not in ("TS1", "CB22")]
    tokens.append(_tok("CB2", _at("CB22"), passes=1, conf=0.7))            # a partial read is not certain
    reg = register(tokens, _kb(), _photo())
    tg = guided.targets(_kb(), reg, (2400, 2400))
    assert sorted({t["tag"] for t in tg}) == ["CB22", "TS1"]
    t = next(t for t in tg if t["tag"] == "TS1")
    x, y = _at("TS1")
    assert t["box"][0] < x < t["box"][2] and t["box"][1] < y < t["box"][3] and t["letter_px"] == pytest.approx(16.0)
    assert not guided.targets(_kb(), reg, (1500, 1500), skip={"CB22"})      # TS1 is outside a smaller photo


def test_an_exact_read_at_its_spot_joins_the_tokens_with_both_magnifications_as_passes():
    tokens = [_tok(t, _at(t)) for t in TAGS if t != "TS1"]
    reg = register(tokens, _kb(), _photo())
    calls = []
    out, reg2, st = guided.refine(_photo(), _kb(), tokens, reg, read=reader([("TS1", _at("TS1"))], calls=calls),
                                  small_print=_no_small)
    new = [t for t in out if t["norm"] == "TS1"]
    assert len(new) == 1 and new[0]["guided"] and new[0]["passes"] == 2 and new[0]["pass"] == "guided"
    assert st["found"] == 1 and st["targets"] == 1 and st["inliers_after"] >= st["inliers_before"]
    assert len(calls) == 2 and calls[1][1] > calls[0][1]                    # two magnifications
    assert calls[0][1] == pytest.approx(guided.MAG_TEXT / 16.0)             # letters magnified to MAG_TEXT px
    assert any(r["tag"] == "TS1" and r["dist_px"] < 5 for r in reg2["reads"])


@pytest.mark.parametrize("label, conf", [("TS2", 0.95), ("T51", 0.95), ("TS1", 0.6)])
def test_anything_but_a_confident_exact_read_of_the_tag_is_ignored(label, conf):
    tokens = [_tok(t, _at(t)) for t in TAGS if t != "TS1"]
    reg = register(tokens, _kb(), _photo())
    out, _reg, st = guided.refine(_photo(), _kb(), tokens, reg, read=reader([(label, _at("TS1"))], conf=conf),
                                  small_print=_no_small)
    assert st["found"] == 0 and len(out) == len(tokens)


def test_a_read_outside_the_labels_own_window_is_ignored():
    tokens = [_tok(t, _at(t)) for t in TAGS if t != "TS1"]
    reg = register(tokens, _kb(), _photo())
    far = (_at("TS1")[0] + 400, _at("TS1")[1])
    seen = []

    def read(photo, box, rotations=(0,), scale=3.0):          # a reader that returns a TS1 read wherever it looks
        seen.append(box)
        return [_tok("TS1", far, passes=1)]
    out, _reg, st = guided.refine(_photo(), _kb(), tokens, reg, read=read, small_print=_no_small)
    assert st["found"] == 0 and seen and not any(t["norm"] == "TS1" for t in out)


def test_a_photo_that_cannot_be_placed_gets_one_magnified_small_print_read():
    garbled = [_tok("C8Z1", _at("CB21"), passes=1, conf=0.6), _tok("P5I1", _at("PS11"), passes=1, conf=0.6),
               _tok("XX", (50, 50)), _tok("1", (60, 60)), _tok("D5", (70, 70))]
    reg = register(garbled, _kb(), _photo())
    assert not reg["localised"]
    got = {}

    def small(photo, near):
        got["near"] = near
        return [_tok(t, _at(t), passes=1) for t in ("PS11", "PS12", "PS13", "DS11")]
    out, reg2, st = guided.refine(_photo(), _kb(), garbled, reg, read=reader([]), small_print=small)
    assert st["small_print"] and st["small_print_tokens"] == 4 and len(got["near"]) == len(garbled)
    assert reg2["localised"]
    few = garbled[:2]                                                       # too little text to be small labels
    _o, reg3, st3 = guided.refine(_photo(), _kb(), few, register(few, _kb(), _photo()), read=reader([]),
                                  small_print=_no_small)
    assert not st3["small_print"] and not reg3["localised"]


def test_reads_of_the_same_text_at_the_same_spot_reinforce_instead_of_duplicating():
    a = _tok("PS11", (500, 500), passes=1)
    out, n = guided.add_tokens([a], [dict(_tok("PS11", (502, 501), passes=1), support=["guided1"])])
    assert n == 1 and len(out) == 1 and out[0]["passes"] == 2 and set(out[0]["support"]) == {"full", "guided1"}
    out, n = guided.add_tokens(out, [_tok("PS12", (900, 500), passes=1)])
    assert n == 1 and len(out) == 2


def test_a_small_label_the_first_read_missed_is_verified_and_nothing_is_invented():
    """End to end through the checks: TS1 was not read by the regular passes; the guided read finds it at its spot,
    so the presence and label checks pass it. CB22's label is genuinely gone: nothing can find it, so it is never
    passed, and its absence is still not a FAIL."""
    kb, photo = _kb(), _photo()
    tokens = [_tok(t, _at(t)) for t in TAGS if t not in ("TS1", "CB22")]
    reg = register(tokens, kb, photo)
    tokens, reg, st = guided.refine(photo, kb, tokens, reg, read=reader([("TS1", _at("TS1"))]), small_print=_no_small)
    ctx = Context(kb, "x.pdf", photo, tokens, reg, ocr_region=lambda box, rot, scale: [])
    findings, _t = run_checks(ctx, ["MISSING", "LABEL"])
    items = {i["id"]: i for i in consensus.decide(findings, {}, agent_on=False, registration=reg)}
    assert items["MISS-TS1"]["result"] == "PASS" and items["LBL-TS1"]["result"] == "PASS"
    assert items["MISS-CB22"]["result"] != "PASS" and items["LBL-CB22"]["result"] != "PASS"
    assert not [i for i in items.values() if i["result"] == "FAIL"]


# ------------------------------------------------------------------ look-alike characters, scored by the recognizer
def _scorer(table):
    """Fake recognizer scores: {text: probability} for every candidate; the best reading is the likeliest entry."""
    def score(photo, quad, texts):
        best = max(table, key=table.get)
        return {"best": (best, float(np.log(table[best]))),
                "scores": {t: float(np.log(table.get(t, 1e-6))) for t in texts}}
    return score


def _quad_tok(text, xy, conf=0.93):
    t = _tok(text, xy, passes=1, conf=conf)
    b = t["box"]
    t["quad"] = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]
    return t


def _quad_reader(text, xy, conf=0.93):
    def read(photo, box, rotations=(0,), scale=3.0):
        return [_quad_tok(text, xy, conf)] if box[0] <= xy[0] <= box[2] and box[1] <= xy[1] <= box[3] else []
    return read


def test_a_look_alike_read_is_taken_when_the_recognizer_itself_finds_the_tag_likely():
    tokens = [_tok(t, _at(t)) for t in TAGS if t != "CB22"]
    reg = register(tokens, _kb(), _photo())
    score = _scorer({"C822": 0.5, "CB22": 0.4, "CB21": 0.02})                 # B vs 8 nearly a tie, CB21 far behind
    out, reg2, st = guided.refine(_photo(), _kb(), tokens, reg, read=_quad_reader("C822", _at("CB22")), score=score,
                                  small_print=_no_small)
    [tok] = [t for t in out if t["norm"] == "CB22"]
    assert st["found"] == 1 and st["constrained"] == 1 and tok["passes"] == 2
    assert tok["constrained"]["read"] == "C822" and tok["constrained"]["ratio"] == pytest.approx(0.8)
    assert tok["conf"] <= 0.84                                             # verifies only because 2 magnifications agree
    ctx = Context(_kb(), "x.pdf", _photo(), out, reg2, ocr_region=lambda box, rot, scale: [])
    findings, _t = run_checks(ctx, ["MISSING", "LABEL"])
    lbl = next(f for f in findings if f["id"] == "LBL-CB22")
    assert lbl["status"] == "OK" and "read 'C822'" in lbl["evidence"][0] and "80% as likely" in lbl["evidence"][0]
    assert lbl["reads"][0]["printed"] == "C822"


@pytest.mark.parametrize("table", [
    {"C822": 0.9, "CB22": 0.05, "CB21": 0.001},        # the recognizer is sure it saw an 8: not taken
    {"C822": 0.5, "CB22": 0.4, "CB21": 0.3},           # a neighbouring tag is nearly as likely: not taken
])
def test_a_look_alike_read_the_recognizer_does_not_back_is_never_taken(table):
    tokens = [_tok(t, _at(t)) for t in TAGS if t != "CB22"]
    reg = register(tokens, _kb(), _photo())
    out, _reg, st = guided.refine(_photo(), _kb(), tokens, reg, read=_quad_reader("C822", _at("CB22")),
                                  score=_scorer(table), small_print=_no_small)
    assert st["found"] == 0 and not any(t["norm"] == "CB22" for t in out)


def test_without_a_recognizer_score_a_look_alike_read_is_not_taken():
    tokens = [_tok(t, _at(t)) for t in TAGS if t != "CB22"]
    reg = register(tokens, _kb(), _photo())
    out, _reg, st = guided.refine(_photo(), _kb(), tokens, reg, read=_quad_reader("C822", _at("CB22")),
                                  score=lambda *a: None, small_print=_no_small)
    assert st["found"] == 0
