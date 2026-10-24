"""Which wire colours are allowed where: the colour rule of a cabinet and the circuit class of each of its wires.

Colour codes are not universal. The same colour means different things under different standards and editions (black
is a phase under IEC 60445 and BS 7671 but the neutral under India's legacy IS 732 practice; white is the neutral
under NFPA 79), and every panel builder adds house rules on top. So the rule comes from the cabinet's own documents
first, from a standard only when someone chooses one, and is never assumed:

    1. wire list       the exact colour of each wire (when a wire list with colours is supplied)
    2. drawing legend  the drawing set's own wire-colour table: colours per circuit (230 V AC distribution, 24 V DC
                       distribution, alarm wiring ...), read by kb/drawing_kb.py from the cabinet's drawings
    3. profile         a named profile chosen for the project (wire_profiles.json: IEC 60204-1, NFPA 79, IEC 60445,
                       India legacy, AS/NZS legacy); each names the edition to check
    4. none            only the universal rule below is checked, and the report says so

One rule holds under every one of these standards: green-and-yellow identifies the protective conductor only.

A wire's circuit class comes from the drawing's own wiring, never from its colour. Seeds come from pin names that mean
the same on any device: L, N, L1-L3 are AC; +, -, 0V, L+, L- are DC; PE, E, GND and earth bars are protective earth;
breaker contacts 91-98 (EN 50005 fault-signalling contacts) and ALM terminals are the alarm loop. Classes spread along
the drawing's wires and buses and through the main poles of breakers and switches (1-2, 3-4 ...). A power supply is
a boundary (its input is AC, its output DC), so is an earth point (a wire to it is the earth wire), and a reference to
a device without a pin stays on its own drawing sheet (a device's mains and alarm circuits are drawn on different
sheets). A circuit whose seeds disagree gets no class: nothing is guessed.

    rules(kb, wires=None, profile=None) -> {"source", "classes": {class: [codes]}, "notes", ...}
    circuit_classes(kb) -> {"nodes", "devices", "known", "stats"}     wire_class(ends, cc) -> (class, reason)
"""
import json
import re
from collections import Counter
from functools import lru_cache

import config
from kb.tags import family_of

PROFILES_FILE = config.BASE / "wire_profiles.json"
CLASSES = ("AC", "DC", "ALARM", "PE")
CLASS_NAME = {"AC": "AC mains", "DC": "DC distribution", "ALARM": "alarm wiring", "PE": "protective earth"}
# IEC 60757 colour codes; drawings and lists spell some differently
ALIAS = {"OR": "OG", "GNYE": "GN/YE", "GN-YE": "GN/YE", "YEGN": "GN/YE", "YE/GN": "GN/YE", "GRYE": "GN/YE",
         "LB": "BU", "LBU": "BU", "WHBU": "WH/BU", "BL": "BU", "GR": "GN", "BR": "BN", "SW": "BK"}
GREEN = {"GN/YE", "GN"}
UNIVERSAL_PE = ["GN/YE", "GN"]          # green-and-yellow everywhere; plain green is also allowed in North America
EARTH_PINS = {"PE", "E", "GND", "EARTH", "PG", "FE"}
AC_PINS = {"L", "N", "L1", "L2", "L3", "AC", "ACL", "ACN"}
DC_PINS = {"+", "-", "L+", "L-", "0V", "+24V", "24V", "V+", "V-", "DC+", "DC-", "+V", "-V"}
POLES = {"CB", "RCCB", "DS"}            # switching devices: pins 1-2, 3-4, 5-6, 7-8 carry one conductor through
SIGNAL = re.compile(r"^9[1-8]$")        # EN 50005 fault-signalling contacts of breakers: the alarm loop


def code(c):
    c = re.sub(r"\s+", "", str(c or "").upper())
    return ALIAS.get(c, c)


def legend_class(key):
    """Circuit class of a legend row ('230VAC' -> 'AC', '24VDC' -> 'DC', 'ALARM'); None for an unnamed group."""
    k = re.sub(r"\s+", "", str(key or "").upper())
    if "ALARM" in k:
        return "ALARM"
    if re.search(r"\d+V?AC|VAC|MAINS", k):
        return "AC"
    if re.search(r"\d+V?DC|VDC", k):
        return "DC"
    return None


@lru_cache(maxsize=1)
def _profiles_file():
    try:
        return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def profiles():
    """{id: profile} of wire_profiles.json."""
    return _profiles_file().get("profiles") or {}


def profile_list():
    """Profiles for a picker: [{"id", "name", "region", "edition", "verify"}]."""
    return [{"id": k, **{f: p.get(f) for f in ("name", "region", "edition", "verify")}} for k, p in profiles().items()]


def rules(kb, wires=None, profile=None):
    """The colour rule of one cabinet: where it comes from and the allowed colours per circuit class."""
    if wires:
        per_wire = {str(w.get("ferrule") or w.get("terminal")): code(w.get("colour")) for w in wires if w.get("colour")}
        if per_wire:
            return {"source": "wire list", "kind": "wire_list", "per_wire": per_wire, "classes": {}, "notes": []}
    legend = (kb or {}).get("wire_colours")
    if legend:
        classes, unnamed = {}, []
        for key, codes in legend.items():
            cls = legend_class(key)
            if cls is None:
                unnamed += [code(c) for c in codes]
                continue
            for c in codes:
                if code(c) not in classes.setdefault(cls, []):
                    classes[cls].append(code(c))
        pe = sorted({c for codes in classes.values() for c in codes if c in GREEN}, key=lambda c: c != "GN/YE")
        if pe:
            classes["PE"] = pe
        page = ((kb or {}).get("stats") or {}).get("wire_colours_page")
        notes = [f"a legend group without a circuit name ({'/'.join(unnamed)}) is not used"] if unnamed else []
        return {"source": f"drawing legend (page {page})" if page else "drawing legend", "kind": "legend",
                "classes": classes, "legend": legend, "notes": notes}
    if profile:
        p = profiles().get(profile)
        if not p:
            return {"source": None, "kind": None, "classes": {}, "notes": [f"unknown wire-colour profile '{profile}'"]}
        return {"source": f"profile: {p['name']}", "kind": "profile", "profile": profile,
                "classes": {k: [code(c) for c in v] for k, v in p["classes"].items()}, "meaning": p.get("meaning") or {},
                "notes": [n for n in (p.get("edition"), p.get("verify")) if n]}
    return {"source": None, "kind": None, "classes": {}, "notes": [
        "no wire-colour legend in the drawing set and no profile chosen: only the universal rule (green-and-yellow "
        "for protective earth only) is checked"]}


def allowed(rule, cls):
    """Colours a wire of this circuit class may have. Green-and-yellow belongs to protective earth only; plain green
    only where the rule itself lists it for the class (a DC ground return in some house legends)."""
    codes = list((rule.get("classes") or {}).get(cls) or [])
    if cls == "PE":
        return [c for c in codes if c in GREEN] or list(UNIVERSAL_PE)
    return [c for c in codes if c != "GN/YE"]


def describe(rule, cc=None):
    """The rule as the report shows it: source, allowed colours per class, notes and circuit-class coverage."""
    out = {"source": rule.get("source"), "kind": rule.get("kind"), "profile": rule.get("profile"),
           "classes": {c: allowed(rule, c) for c in CLASSES if (rule.get("classes") or {}).get(c) or c == "PE"},
           "notes": list(rule.get("notes") or []), "universal": "green-and-yellow identifies protective earth only"}
    if rule.get("kind") == "wire_list":
        out["classes"] = {}
        out["wires"] = len(rule.get("per_wire") or {})
    if cc:
        out["circuits"] = cc["stats"]
    return out


# ------------------------------------------------------------------ circuit class of the drawing's pins
def _split(ref, devices=frozenset()):
    """'PS12-L' -> ('PS12', 'L'), 'PS12--' -> ('PS12', '-'), 'X-FSW1-3' -> ('X-FSW1', '3'), 'DS1' -> ('DS1', None).
    Known device names (the drawing's vocabulary) win over the first '-'."""
    ref = str(ref or "").strip().upper()
    if ref in devices:
        return ref, None
    for i in [k for k, ch in enumerate(ref) if ch == "-" and 0 < k < len(ref) - 1][::-1]:
        if ref[:i] in devices:
            return ref[:i], ref[i + 1:]
    m = re.match(r"^(.*?[A-Z0-9])-(.+)$", ref)
    return (m.group(1), m.group(2)) if m else (ref, None)


def _kind(dev, pin):
    """Class a pin (or device) declares by itself: 'EARTH', 'AC', 'DC', 'ALARM' or None."""
    fam = family_of(dev) or ""
    pin = (pin or "").upper()
    if fam in ("EARTH", "SB") or pin in EARTH_PINS:
        return "EARTH"
    if "ALM" in dev:
        return "ALARM"
    if pin in AC_PINS:
        return "AC"
    if pin in DC_PINS:
        return "DC"
    if fam in POLES and SIGNAL.match(pin):
        return "ALARM"
    return None


def circuit_classes(kb):
    """Circuit class of the drawing's pins: {"nodes": {'CB12-2': 'AC', 'DS1@11': 'AC', ...}, "devices": {device: class
    where all its sheets agree}, "known": device names, "stats": counts}. Unknown and conflicting circuits are left out."""
    kb = kb or {}
    devices = frozenset(str(t).upper() for t in kb.get("vocabulary") or ()) | frozenset(
        str(d).upper() for b in kb.get("buses") or () for d in b.get("devices") or ())
    parent, ref = {}, {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def node(dev, pin, page):
        dev = str(dev or "").upper()
        pin = str(pin).upper() if pin else None
        n = f"{dev}-{pin}" if pin else f"{dev}@{page}"
        ref[n] = (dev, pin)
        find(n)
        return n

    def link(nodes):
        live = [n for n in nodes if _kind(*ref[n]) != "EARTH"]       # an earth point is a boundary, not a junction
        for n in live[1:]:
            union(live[0], n)

    wires = 0
    for c in kb.get("connections") or ():
        if c.get("from_device") and c.get("to_device"):
            a = node(c["from_device"], c.get("from_pin"), c.get("page"))
            b = node(c["to_device"], c.get("to_pin"), c.get("page"))
        else:
            a = node(*_split(c.get("from"), devices), c.get("page"))
            b = node(*_split(c.get("to"), devices), c.get("page"))
        wires += 1
        link([a, b])
    for bus in kb.get("buses") or ():
        link([node(*_split(m, devices), bus.get("page")) for m in bus.get("members") or ()])
    for n, (dev, pin) in list(ref.items()):                          # main poles carry one conductor through
        if pin and pin.isdigit() and 1 <= int(pin) <= 8 and (family_of(dev) or "") in POLES:
            k = int(pin)
            union(n, node(dev, str(k + 1 if k % 2 else k - 1), None))
    seeds = {}
    for n, (dev, pin) in ref.items():
        k = _kind(dev, pin)
        if k and k != "EARTH":
            seeds.setdefault(find(n), set()).add(k)
    nodes, conflicts = {}, set()
    for n, (dev, pin) in ref.items():
        if _kind(dev, pin) == "EARTH":
            nodes[n] = "PE"
            continue
        found = seeds.get(find(n)) or set()
        if len(found) == 1:
            nodes[n] = next(iter(found))
        elif len(found) > 1:
            conflicts.add(find(n))
    per_dev = {}
    for n, (dev, pin) in ref.items():                                # a device on every sheet it is drawn on
        if pin is None:
            per_dev.setdefault(dev, set()).add(nodes.get(n))
    devs = {d: next(iter(s)) for d, s in per_dev.items() if len(s) == 1 and None not in s}
    return {"nodes": nodes, "all": set(ref), "devices": devs, "known": devices,
            "stats": {"wires": wires, "classified": dict(Counter(nodes.values())), "conflicts": len(conflicts)}}


def _end(e, known):
    if isinstance(e, dict):
        dev, pin, page = e.get("device"), e.get("pin"), e.get("page")
    else:
        (dev, pin), page = _split(e, known), None
    return str(dev or "").upper(), (str(pin).upper() if pin else None), page


def wire_class(ends, cc):
    """(class, reason) of a wire from its two ends ({"device", "pin"[, "page"]} dicts or 'CB12-2' strings), or
    (None, reason). An end the drawing draws is judged by its own circuit; only a pin the drawing does not draw (a
    terminal 'X3-5' of a strip drawn as 'X3') falls back to its device, and only when every sheet agrees on it."""
    seen = []
    for e in ends:
        dev, pin, page = _end(e, cc.get("known") or frozenset())
        name = f"{dev}-{pin}" if pin else dev
        k = _kind(dev, pin)
        if k == "EARTH":
            return "PE", f"{name} is an earth point, so this is the earth wire"
        if k:
            seen.append((name, k, "by its pin name"))
            continue
        here = name if pin else f"{dev}@{page}"
        if here in cc["all"]:
            if cc["nodes"].get(here):
                seen.append((name, cc["nodes"][here], "in the drawing's power schematics"))
        elif cc["devices"].get(dev):
            seen.append((name, cc["devices"][dev], f"where the drawing wires {dev}"))
    kinds = {k for _n, k, _w in seen}
    if not kinds:
        return None, "the drawing's extracted wiring does not reach either end of this wire"
    if len(kinds) > 1:
        return None, "its ends sit on different circuits (" + ", ".join(f"{n}: {k}" for n, k, _w in seen) + ")"
    n, k, w = seen[0]
    return k, f"{n} is on the {CLASS_NAME[k]} side {w}"
