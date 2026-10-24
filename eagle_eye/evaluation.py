"""Read-only evaluation catalogue; missing measurements are null, never fabricated zeros.

Only aggregate metrics are exposed. Company photos, annotations and drawing paths stay private.
"""
import json

import config

SCHEMA = "eagle-eye-evaluation/1"


def _read(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _empty(kind, label):
    return dict(id=kind, label=label, source=kind, status="not_evaluated", images=None, cabinets=None,
                engine_version=None, confirmed=None, referred=None, incorrect_pass=None, unassessed=None,
                total_faults=None, review_rate=None, false_fail=None,
                note="No evaluation has been recorded. Unmeasured values are not zero.")


def _synthetic():
    result = _empty("synthetic", "Generated cabinet benchmark")
    summary = _read(config.OUT / "forge" / "summary.json")
    if not summary:
        return result
    version = summary.get("engine_version")
    result.update(status="available" if version == config.VERSION else "legacy", engine_version=version,
                  images=summary.get("cabinets"), cabinets=summary.get("cabinets"),
                  total_faults=summary.get("planted"), confirmed=summary.get("confirmed"),
                  referred=summary.get("referred"), incorrect_pass=summary.get("incorrect_pass"),
                  unassessed=summary.get("unassessed"), review_rate=summary.get("review_rate"),
                  false_fail=summary.get("false_alarms"),
                  note="Synthetic images with generated answer keys. These results do not establish real-cabinet accuracy.")
    if result["status"] == "legacy":
        result["note"] += " Historical result; rerun eval_forge.py to measure the current engine."
    return result


def _real():
    result = _empty("real", "Real cabinet benchmark")
    roots = {config.DATA, config.OUT}
    paths = [p for root in roots for p in root.glob("real_eval*/summary.json")]
    for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
        summary = _read(path)
        if not summary or not isinstance(summary.get("total"), dict):
            continue
        total, version = summary["total"], summary.get("engine_version")
        strict = summary.get("schema") == "eagle-eye-real-evaluation/2"
        result.update(status="available" if strict and version == config.VERSION else "legacy",
                      engine_version=version, images=len(summary.get("photos") or {}),
                      cabinets=summary.get("cabinets"), total_faults=total.get("deviations"),
                      confirmed=total.get("deviations_confirmed") if strict else None,
                      referred=total.get("deviations_review") if strict else None,
                      incorrect_pass=total.get("deviations_incorrect_pass") if strict else None,
                      unassessed=total.get("deviations_unassessed") if strict else None,
                      review_rate=total.get("review_rate"), false_fail=total.get("false_fail"),
                      note="Real photos scored against supplied expert annotations. Coverage and sample size limit these results.")
        if result["status"] == "legacy":
            result["note"] += " Historical result; rerun eval_real.py for current, separate detection and referral metrics."
        break
    return result


def catalogue():
    return dict(schema=SCHEMA, metrics={
        "confirmed_recall": "Confirmed defects / annotated defects. REVIEW is excluded.",
        "referral_rate": "Annotated defects sent to REVIEW / annotated defects; not automatic detection.",
        "incorrect_pass": "Annotated defects incorrectly cleared by their applicable checks.",
    }, datasets=[_synthetic(), _real()])
