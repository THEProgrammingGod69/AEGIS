"""The in-process OCR backend must read exactly what the tesseract CLI reads (it is only a speed-up)."""
import pytesseract
import pytest

import config
import inspector
import ocr_capi
import service


@pytest.mark.skipif(not ocr_capi.available(), reason="libtesseract cannot be loaded on this machine")
def test_capi_text_identical_to_cli(runs_dir, monkeypatch):
    jobs = []
    orig = inspector._tess
    monkeypatch.setattr(inspector, "_tess", lambda job: jobs.append(job) or orig(job))
    service.run_inspection(next(config.SAMPLES.glob("01_*.jpg")), reports=False)
    assert len(jobs) > 40
    for img, psm in jobs[::2]:
        cli = pytesseract.image_to_string(img, config=f"--psm {psm} -c tessedit_char_whitelist={inspector.WL}").strip()
        assert ocr_capi.image_to_string(img, psm, inspector.WL).strip() == cli


def test_cli_fallback_when_disabled(monkeypatch):
    monkeypatch.setattr(inspector, "_CAPI", False)
    img = inspector.cv2.putText(inspector.np.full((60, 220), 255, inspector.np.uint8), "CB41", (10, 45),
                                inspector.cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    assert "CB41" in inspector._tess((img, 7)).replace(" ", "")
