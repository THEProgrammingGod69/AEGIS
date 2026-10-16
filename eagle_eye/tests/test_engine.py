"""Engine regression tests: drawing parser, closed-vocabulary OCR decoding, and the five sample photos."""
import numpy as np
import pytest
from PIL import Image

import config
from inspector import InspectionError, inspect, parse_ga, read_wire_list, vote

SAMPLES = {
    # sample id: (FAIL items, SKIP items)
    "01": ({"GA-PS12", "ORD-RAIL-1", "LBL-1CBP03", "FER-X3:3"}, {"LBL-PS12"}),
    "02": (set(), set()),
    "03": ({"FER-X3:5", "COL-X3:7"}, set()),
    "04": ({"GA-CB42", "LBL-PS11"}, {"LBL-CB42"}),
    "05": ({"FER-X3:3"}, set()),
}


def sample(sid):
    return next(config.SAMPLES.glob(f"{sid}_*.jpg"))


def test_parse_ga_reads_every_item_from_the_vector_drawing():
    ga = parse_ga(str(config.DEMO_GA))
    assert ga["cabinet"] == "EE-DEMO-01"
    assert ga["size"] == (600, 800)
    assert {d["tag"] for d in ga["devices"]} == {"PS11", "PS12", "D12", "CB41", "CB42", "CB43", "CB44",
                                                 "1CBP01", "1CBP02", "1CBP03", "1CBP04", "PE"}
    assert [t["tag"] for t in ga["terminals"]] == [f"X3:{i}" for i in range(1, 9)]
    assert ga["rails"] == [{"name": "RAIL-1", "tags": ["CB41", "CB42", "CB43", "CB44"]}]


def test_parse_ga_is_cached_but_returns_independent_copies():
    a = parse_ga(str(config.DEMO_GA))
    a["devices"].clear()
    assert len(parse_ga(str(config.DEMO_GA))["devices"]) == 12


def test_wire_list():
    wires = read_wire_list(str(config.DEMO_WIRES))
    assert len(wires) == 8
    assert wires[2] == {"terminal": "X3:3", "ferrule": "X3-3/CB43-2", "colour": "BN"}


@pytest.mark.parametrize("readings, expected", [
    (["CB43", "CB43", "CB43", "CB43"], "CB43"),      # clean read
    (["CB4B", "CB43", "C843", "CB43"], "CB43"),      # B/8 confusion handled by the canonical form
    (["B43", "B43"], "CB43"),                        # first character clipped
    (["CB43E", "CB43"], "CB43"),                     # vocabulary item embedded in junk
])
def test_vote_decodes_against_the_closed_vocabulary(readings, expected):
    best, agreement, _ = vote(readings, ["CB41", "CB42", "CB43", "CB44"])
    assert best == expected and agreement > 0


def test_vote_refuses_to_guess_outside_the_vocabulary():
    best, agreement, raw = vote(["PS17", "PS17"], ["PS11", "PS12"])
    assert best is None and agreement == 0 and raw == "PS17"


@pytest.mark.parametrize("sid", sorted(SAMPLES))
def test_sample_photos_match_their_answer_key(sid):
    rep, _ = inspect(str(sample(sid)), config.DEMO_GA, config.DEMO_WIRES)
    fails = {r["id"] for r in rep["results"] if r["result"] == "FAIL"}
    skips = {r["id"] for r in rep["results"] if r["result"] == "SKIP"}
    want_fail, want_skip = SAMPLES[sid]
    assert fails == want_fail, "every planted fault is a FAIL and nothing else is (no false alarms)"
    assert skips == want_skip
    assert len(rep["results"]) == 41
    assert rep["registration"]["anchors"] >= 12


def test_progress_events_cover_every_stage():
    events = []
    inspect(str(sample("02")), config.DEMO_GA, config.DEMO_WIRES, enabled=["GA", "LABEL"], on_event=events.append)
    stages = [(e["stage"], e["status"]) for e in events]
    assert stages[0] == ("parse", "start") and ("register", "done") in stages and stages[-1][0] == "consensus"
    assert [e["check"] for e in events if e["stage"] == "check" and e["status"] == "done"] == ["GA", "LABEL"]


def test_root_cause_skip_needs_the_ga_check():
    rep, _ = inspect(str(sample("04")), config.DEMO_GA, config.DEMO_WIRES, enabled=["LABEL"])
    assert not any(r["result"] == "SKIP" for r in rep["results"])


def test_upside_down_photo_is_rotated_back(tmp_path):
    p = tmp_path / "upside_down.jpg"
    Image.open(sample("02")).rotate(180).save(p, quality=92)
    rep, ctx = inspect(str(p), config.DEMO_GA, config.DEMO_WIRES)
    assert rep["orientation"] == 180 and [w["code"] for w in rep["warnings"]] == ["rotated"]
    assert all(r["result"] == "PASS" for r in rep["results"])
    assert ctx.photo.shape[:2] == (rep["photo_size"][1], rep["photo_size"][0])


def test_photo_that_does_not_match_the_drawing_never_fails(tmp_path):
    """Registration guard: a photo of another cabinet (here: mirrored) must not produce false alarms."""
    p = tmp_path / "mirrored.jpg"
    Image.open(sample("02")).transpose(Image.FLIP_LEFT_RIGHT).save(p, quality=92)
    rep, _ = inspect(str(p), config.DEMO_GA, config.DEMO_WIRES)
    assert not any(r["result"] == "FAIL" for r in rep["results"])
    assert any(w["code"] == "weak_registration" for w in rep["warnings"])
    assert all(r["found"].startswith("Unverified") for r in rep["results"] if r.get("guarded"))


def test_blank_photo_is_a_clear_input_error(tmp_path):
    p = tmp_path / "blank.jpg"
    Image.fromarray(np.full((800, 600, 3), 40, np.uint8)).save(p)
    with pytest.raises(InspectionError, match="backplate"):
        inspect(str(p), config.DEMO_GA, config.DEMO_WIRES)


def test_unreadable_photo_is_a_clear_input_error(tmp_path):
    p = tmp_path / "not_a_photo.jpg"
    p.write_bytes(b"definitely not a jpeg")
    with pytest.raises(InspectionError, match="photo"):
        inspect(str(p), config.DEMO_GA, config.DEMO_WIRES)
