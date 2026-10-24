"""Photos taken at an angle: the perspective registration, the measured viewing angle, the local scale, the oblique
photo warning and the drawing overlays, on synthetic cameras (no photo, no OCR)."""
import math

import numpy as np
import pytest

from vision import register as rg

W, H = 2400, 1800
F = 0.8 * max(W, H)


def camera(yaw=0.0, pitch=0.0, centre=(180.0, 150.0), scale=6.0):
    """Homography drawing pt -> photo px of a phone camera turned by yaw / pitch (degrees) towards a flat cabinet."""
    K = np.array([[F, 0, W / 2], [0, F, H / 2], [0, 0, 1.0]])
    a, b = math.radians(yaw), math.radians(pitch)
    Ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    R = Rx @ Ry
    D = F / scale                                        # distance giving ``scale`` px per pt at the centre
    T = np.array([[1, 0, -centre[0]], [0, 1, -centre[1]], [0, 0, 1.0]])
    Hm = K @ np.c_[R[:, 0], R[:, 1], np.array([0, 0, D])] @ T
    return Hm / Hm[2, 2]


@pytest.mark.parametrize("yaw, pitch", [(0, 0), (20, 0), (-35, 0), (50, 0), (0, -25), (30, 15)])
def test_viewing_angle_is_measured_from_the_perspective(yaw, pitch):
    a = rg.view_angle(camera(yaw, pitch), (W, H))
    true = math.degrees(math.acos(math.cos(math.radians(yaw)) * math.cos(math.radians(pitch))))
    assert abs(a["tilt"] - true) < 1.0
    if abs(yaw) >= 15:
        assert (a["yaw"] > 0) == (yaw > 0)               # yaw > 0: the right side of the cabinet is nearer
        assert a["focal_source"] == "estimated" and abs(a["focal_px"] - F) / F < 0.02


def test_right_side_nearer_means_taken_from_the_right_and_letters_shrink_on_the_far_side():
    Hm = camera(35)
    left, right = rg.local_scale(Hm, (100, 150)), rg.local_scale(Hm, (260, 150))
    assert right > 1.3 * left                            # the right side is nearer: bigger
    assert rg.view_angle(Hm, (W, H))["yaw"] > 0
    assert rg.local_scale(camera(0), (100, 150)) == pytest.approx(6.0, rel=1e-6)


def test_degenerate_samples_are_refused():
    assert rg._degenerate([[0, 0], [10, 0], [20, 0], [5, 8]])        # three on a rail
    assert not rg._degenerate([[0, 0], [10, 0], [10, 10], [0, 10]])


# ------------------------------------------------------------------ register() on a cabinet seen at an angle
ROWS = {"PS": 100.0, "CB": 150.0, "DS": 200.0}
TAGS = {f"{fam}{11 + i}": (100.0 + 40.0 * i, y) for fam, y in ROWS.items() for i in range(5)}


def _kb():
    tags = [{"tag": t, "family": t[:2], "center": list(c), "label_expected": True, "device_bbox": None, "label": None,
             "instances": [{"bbox": [c[0] - 2, c[1] - 0.7, c[0] + 2, c[1] + 0.7], "center": list(c), "rot": 0,
                            "size_pt": 1.6, "kind": "nameplate", "stray": False}]} for t, c in TAGS.items()]
    return {"views": {"front": {"page": 1, "title": "FRONT", "bbox": [80, 80, 280, 220], "region": [80, 80, 280, 220],
                                "tags": tags, "callouts": []}},
            "vocabulary": sorted(TAGS), "groups": []}


def _tokens(Hm):
    out = []
    for t, c in TAGS.items():
        x, y = rg._apply(Hm, [c])[0]
        out.append({"text": t, "norm": t, "box": [x - 30, y - 10, x + 30, y + 10], "conf": 0.99, "rot": 0, "passes": 2})
    return out


def _photo():
    return {"size": [W, H], "ignore": [], "rgb": None}


def test_a_photo_from_the_side_is_placed_through_its_perspective():
    Hm = camera(42, centre=(180.0, 150.0), scale=7.0)
    reg = rg.register(_tokens(Hm), _kb(), _photo())
    [fit] = reg["fits"]
    assert fit["model"] in ("perspective", "homography") and len(fit["inliers"]) == len(TAGS)
    assert abs(fit["angle"]["tilt"] - 42) < 4 and fit["angle"]["yaw"] > 0
    pred = rg.project(fit, [180.0, 150.0])
    assert math.dist(pred, rg._apply(Hm, [[180.0, 150.0]])[0]) < 3.0
    near, far = reg["text_px"]["PS15"], reg["text_px"]["PS11"]              # PS15 is on the near (right) side
    assert near > far and reg["in_view"]["PS15"]["scale_px_per_pt"] > reg["in_view"]["PS11"]["scale_px_per_pt"]


def test_the_flat_registration_alone_loses_labels_at_that_angle(monkeypatch):
    Hm = camera(42, scale=7.0)
    monkeypatch.setattr(rg, "PERSPECTIVE", False)
    flat = rg.register(_tokens(Hm), _kb(), _photo())
    assert flat["fits"][0]["model"] != "perspective"
    monkeypatch.setattr(rg, "PERSPECTIVE", True)
    per = rg.register(_tokens(Hm), _kb(), _photo())
    assert len(per["fits"][0]["inliers"]) >= len(flat["fits"][0]["inliers"]) + 2


def test_a_straight_photo_keeps_the_similarity_and_reports_no_angle():
    reg = rg.register(_tokens(camera(0, scale=7.0)), _kb(), _photo())
    [fit] = reg["fits"]
    assert fit["model"] == "similarity" and fit["angle"] is None and len(fit["inliers"]) == len(TAGS)


def test_oblique_photos_are_named_in_the_report_warnings():
    import pipeline
    reg = {"fits": [{"view": "front", "angle": {"tilt": 38.0, "yaw": -38.0, "pitch": 2.0}}], "localised": True,
           "hint": None}
    w = pipeline._warnings(reg, {"quality": {}}, {"enabled": False}, [], {})
    [ob] = [x for x in w if x["code"] == "oblique_photo"]
    assert "38 degrees from the left" in ob["message"] and "NOT_IN_VIEW" in ob["message"]
    reg["fits"][0]["angle"] = {"tilt": 55.0, "yaw": 0.0, "pitch": -55.0}
    [ob] = [x for x in pipeline._warnings(reg, {"quality": {}}, {"enabled": False}, [], {}) if x["code"] == "oblique_photo"]
    assert "from above" in ob["message"] and "re-photograph straight on" in ob["message"]
    reg["fits"][0]["angle"] = {"tilt": 12.0, "yaw": 12.0, "pitch": 0.0}
    assert not [x for x in pipeline._warnings(reg, {"quality": {}}, {"enabled": False}, [], {}) if x["code"] == "oblique_photo"]


# ------------------------------------------------------------------ overlays through the perspective
def test_overlays_follow_the_perspective_and_straighten_the_photo(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image

    import report as rp
    pdf = tmp_path / "ga.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(pymupdf.Rect(100, 100, 260, 200), color=(0, 0, 0), width=2)
    doc.save(str(pdf))
    Hm = camera(30, centre=(180.0, 150.0), scale=5.0)
    pw, ph = 1200, 900                                   # preview at half size
    preview = np.full((ph, pw, 3), 90, np.uint8)
    fits = [{"view": "front", "H": Hm.tolist(), "scale_px_per_pt": 5.0, "angle": {"tilt": 30.0, "yaw": 30.0, "pitch": 0.0}}]
    info = rp.real_overlays(str(pdf), {"front": {"page": 1, "bbox": [80, 80, 280, 220]}}, fits, preview, (W, H), tmp_path)
    assert info["view"] == "front" and info["size"][0] == 1400 and info["angle"]["tilt"] == 30.0
    ov = np.asarray(Image.open(tmp_path / "drawing_overlay.png"))
    assert ov.shape == (ph, pw, 4)
    corner = rg._apply(Hm, [[100.0, 100.0]])[0] * 0.5           # the drawn rectangle's corner, in preview px
    x, y = int(round(corner[0])), int(round(corner[1]))
    assert ov[y - 3:y + 4, x - 3:x + 4, 3].max() > 100           # the linework lands on the photo through the camera
    rect = np.asarray(Image.open(tmp_path / "rectified.jpg"))
    assert rect.shape[1] == 1400 and abs(rect.shape[0] - 1400 * 140 / 200) <= 1
    g = np.asarray(Image.open(tmp_path / "ga_overlay.png"))
    k = info["k"]
    assert g[int((100 - 80) * k), int((100 - 80) * k) + 2:int((260 - 80) * k) - 2, 3].mean() > 100   # top edge, straight


def test_eval_angle_turns_images_like_a_sideways_camera():
    import eval_angle
    img = np.zeros((400, 200, 3), np.uint8)
    img[:, :100] = 255
    same, Ht = eval_angle.turn(img, 0)
    assert np.allclose(Ht, np.eye(3), atol=1e-9) and (same == img).all()
    turned, Ht = eval_angle.turn(img, 40)
    left_h = Ht @ np.array([0, 400, 1.0]); right_h = Ht @ np.array([200, 400, 1.0])
    l0 = Ht @ np.array([0, 0, 1.0]); r0 = Ht @ np.array([200, 0, 1.0])
    left = abs(left_h[1] / left_h[2] - l0[1] / l0[2]); right = abs(right_h[1] / right_h[2] - r0[1] / r0[2])
    assert left != pytest.approx(right, rel=0.05)                # one side shrinks: keystone
