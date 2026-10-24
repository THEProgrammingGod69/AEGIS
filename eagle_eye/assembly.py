"""Where a finding belongs on the assembly line: its device family, its area of the cabinet and the line station that
fixes it. Stored with every issue of a run so QC analytics can rank recurring faults (a Pareto) and send them back to
the station that causes them.

    dims(item, report, groups=None) -> {"check", "target", "family", "area", "station"}

Demo-cabinet runs place a device by its drawing zone (rail, baseplate row, terminal strip); real-cabinet runs by the GA
view and the drawing's aligned device group ("Front · PS row 1"). Families use readable names ("Circuit breaker").
"""
import re

from kb.tags import family_of

STATION = {"GA": "Kitting and mounting", "MISSING": "Kitting and mounting", "ORDER": "Mounting (rail layout)",
           "LABEL": "Labelling", "UNKNOWN_LABEL": "Labelling", "FERRULE": "Wiring (ferrules)",
           "COLOUR": "Wiring (wire colours)"}
FAMILY_NAME = {"CSLS": "CHARM carrier", "CBP": "CHARM baseplate", "RDEW": "Cabinet nameplate", "TERM": "CHARM terminator",
               "RCCB": "Residual-current breaker", "SPD": "Surge protector", "REC": "Socket outlet", "FILTER": "Filter",
               "XALM": "Alarm terminal", "FSW": "Fan switch", "CB": "Circuit breaker", "PS": "Power supply",
               "DS": "Disconnect switch", "D": "Redundancy module", "SB": "Shield bar", "TS": "Thermostat",
               "CF": "Cabinet fan", "CL": "Cabinet light", "X": "Terminal block", "EARTH": "Earth bar"}
# demo drawing (EE-DEMO-01): device type -> family and zone of the backplate
DEMO_TYPE = {"psu": ("Power supply", "Power supply row"), "controller": ("Controller", "Power supply row"),
             "breaker": ("Circuit breaker", "Breaker rail"), "baseplate": ("I/O baseplate", "I/O baseplates"),
             "earth": ("Earth bar", "Earth bar")}
WIRING = {"FERRULE": "Wire ferrule", "COLOUR": "Wire"}
_PREFIX = {"GA": "GA", "ORD": "ORDER", "LBL": "LABEL", "FER": "FERRULE", "COL": "COLOUR", "MISS": "MISSING",
           "UNK": "UNKNOWN_LABEL"}


def check_of(item_id):
    return _PREFIX.get(item_id.split("-")[0], item_id.split("-")[0])


def family_name(tag):
    fam = family_of(tag or "")
    if fam:
        return FAMILY_NAME.get(fam, fam)
    letters = re.sub(r"[^A-Z]", "", str(tag or "").upper())
    return FAMILY_NAME.get(letters, letters or "Other")


def _view_title(view):
    return (view or "").split("-")[0].capitalize() or "Cabinet"


def _demo(item, rep):
    ga = rep.get("ga") or {}
    devices = {d["tag"]: d for d in ga.get("devices") or []}
    check, target = item.get("check") or check_of(item["id"]), str(item.get("target") or "")
    rails = {r["name"]: r for r in ga.get("rails") or []}
    if check in ("FERRULE", "COLOUR") or ":" in target:
        strip = target.split(":")[0]
        return WIRING.get(check, "Terminal block"), f"Terminal strip {strip}"
    if target in rails:                                   # ORDER item of a rail
        tags = rails[target]["tags"]
        fam = next((DEMO_TYPE[devices[t]["type"]][0] for t in tags if (devices.get(t) or {}).get("type") in DEMO_TYPE),
                   family_name(tags[0]))
        return fam, f"Breaker rail ({target})" if fam == "Circuit breaker" else f"Rail {target}"
    d = devices.get(target)
    if d:
        fam, zone = DEMO_TYPE.get(d.get("type"), (family_name(target), "Backplate"))
        return fam, f"{zone} ({d['group']})" if d.get("group") else zone
    return family_name(target), "Backplate"


def _real(item, groups):
    check, target, view = item.get("check") or check_of(item["id"]), str(item.get("target") or ""), item.get("view")
    if check in ("FERRULE", "COLOUR"):
        return WIRING[check], f"{_view_title(view)} · wiring"
    by_id = {g["id"]: g for g in groups or []}
    g = by_id.get(target) or next((g for g in groups or [] if target in g["order"] and (not view or g["view"] == view)),
                                  None)
    if g:
        fam = FAMILY_NAME.get(g["family"], g["family"])
        row = g["id"].rsplit("-", 1)[-1]
        return fam, f"{_view_title(g['view'])} · {g['family']} row {row}"
    return family_name(target), f"{_view_title(view)} view" if view else "Cabinet (view not placed)"


def dims(item, rep, groups=None):
    """Check, target, device family, cabinet area and line station of one report item."""
    check = item.get("check") or check_of(item["id"])
    real = rep.get("engine_kind") == "real"
    fam, area = _real(item, groups) if real else _demo(item, rep)
    return {"check": check, "target": item.get("target"), "family": fam, "area": area,
            "station": STATION.get(check, "Final inspection")}
