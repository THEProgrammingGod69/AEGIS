"""Device-tag families shared by the drawing parser (kb.drawing_kb) and the OCR decoder (vision.decode).

A *tag* is the reference designation printed on a device's nameplate and on the GA drawing (PS11, CB14, 334CBP02,
13CSLS03334, X-FSW1 ...). Nothing here is specific to one cabinet: the families describe the naming scheme of Emerson
marshalling/power cabinets, and the cabinet's actual vocabulary always comes from its drawing set.
"""
import re

# (family, full-match regex on normalised text). Most specific first: the first family that matches wins.
FAMILIES = [
    ("CSLS", r"\d{2}CSLS\d{5}"),               # CHARM carrier (13CSLS03334)
    ("CBP", r"\d{3}CBP\d{2}"),                  # CHARM baseplate (334CBP02)
    ("RDEW", r"\d{2}RDEW-\d{2}[A-Z]\d{3}[A-Z]{1,2}"),   # cabinet nameplate (13RDEW-40A870G)
    ("TERM", r"TERM\d[FR]"),                    # CHARM terminator (TERM1F, TERM2R)
    ("RCCB", r"RCCB\d{1,2}"),
    ("SPD", r"SPD\d{1,2}"),
    ("REC", r"REC\d{1,2}"),
    ("FILTER", r"FILTER\d{1,2}"),
    ("XALM", r"(?:X|ALM)-[A-Z]+\d{0,2}"),      # X-ALM, X-FSW1, ALM-FSW2
    ("FSW", r"FSW\d{1,2}"),
    ("CB", r"CB\d{1,3}"),                       # circuit breaker
    ("PS", r"PS\d{1,3}"),                       # power supply
    ("DS", r"DS\d{1,3}"),                       # disconnect switch
    ("D", r"D\d{2}"),                           # redundancy / diode module (D13, D23)
    ("SB", r"SB\d{2}"),                         # shield bar
    ("TS", r"TS\d{1,2}"),                       # thermostat
    ("CF", r"CF\d{1,2}"),                       # cabinet fan
    ("CL", r"CL\d{1,2}"),                       # cabinet light
    ("X", r"X[A-Z]?\d{1,3}"),                   # terminal strips X1, X11, XP11, XS21, XG11, XU1
    ("EARTH", r"IPE|IE|ISE|ISG|DCG"),           # earth / ground bars
]
_COMPILED = [(f, re.compile(rf"^(?:{rx})$")) for f, rx in FAMILIES]

# Characters OCR confuses. Letter -> digit and digit -> letter, used when a position's expected class is known.
TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "U": "0", "I": "1", "L": "1", "T": "1", "J": "1", "Z": "2", "S": "5",
            "G": "6", "B": "8", "A": "4"}
TO_LETTER = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B", "4": "A", "7": "T"}
# Position-free canonical classes (used to compare a read with the closed vocabulary): every member of a class maps to
# the same symbol, so 'C8P' and 'CBP', 'OS21' and 'DS21', 'S802' and 'SB02' compare equal.
_CANON = str.maketrans({"O": "0", "D": "0", "Q": "0", "U": "0", "I": "1", "L": "1", "|": "1", "Z": "2", "S": "5",
                        "G": "6", "B": "8"})


def normalize(s):
    """Upper-case, drop whitespace and punctuation except '-' and '/' ('FILTER 1' -> 'FILTER1', ' ps11.' -> 'PS11')."""
    s = (s or "").upper()
    s = re.sub(r"[\s_]+", "", s)
    s = re.sub(r"[^A-Z0-9\-/]", "", s)
    return s.strip("-/")


def canonical(s):
    """Confusion-collapsed form of a normalised string (only for comparing against a closed vocabulary)."""
    return normalize(s).replace("-", "").replace("/", "").translate(_CANON)


def family_of(tag):
    """Family name of a tag ('PS11' -> 'PS'), or None when it does not look like a device tag."""
    t = normalize(tag)
    for fam, rx in _COMPILED:
        if rx.match(t):
            return fam
    return None


def is_tag(s):
    return family_of(s) is not None


# Per-family character template used to repair OCR reads: 'A' letter, '9' digit, other characters literal.
_TEMPLATES = {
    "CSLS": ["99CSLS99999"], "CBP": ["999CBP99"], "TERM": ["TERM9F", "TERM9R"], "RCCB": ["RCCB9"], "SPD": ["SPD9"],
    "REC": ["REC9"], "FILTER": ["FILTER9"], "FSW": ["FSW9"], "CB": ["CB99", "CB9"], "PS": ["PS99", "PS9"],
    "DS": ["DS99", "DS9"], "D": ["D99"], "SB": ["SB99"], "TS": ["TS9"], "CF": ["CF9"], "CL": ["CL9"],
    "X": ["X9", "X99", "XA99", "XA9"],
}


def _fit(s, template):
    """Coerce ``s`` onto ``template`` position by position; None when a character cannot be repaired."""
    if len(s) != len(template):
        return None
    out = []
    for ch, t in zip(s, template):
        if t == "9":
            if ch.isdigit():
                out.append(ch)
            elif ch in TO_DIGIT:
                out.append(TO_DIGIT[ch])
            else:
                return None
        elif t == "A":
            if ch.isalpha():
                out.append(ch)
            elif ch in TO_LETTER:
                out.append(TO_LETTER[ch])
            else:
                return None
        else:                                   # literal letter of the family prefix
            if ch == t or TO_LETTER.get(ch) == t or TO_DIGIT.get(t) == ch or TO_DIGIT.get(ch) == TO_DIGIT.get(t, "#"):
                out.append(t)
            else:
                return None
    return "".join(out)


def coerce_to_family(s):
    """Repair a read onto the tag families' character templates.

    Returns ``[(family, coerced), ...]`` for every family the read can be repaired onto (usually zero or one), e.g.
    '334C8P06' -> [('CBP', '334CBP06')], 'OS21' -> [('DS', 'DS21')], 'S802' -> [('SB', 'SB02')]. Exact family matches
    are returned unchanged. Used for strings that are tag-shaped but not in the vocabulary (UNKNOWN_LABEL).
    """
    n = normalize(s).replace("/", "")
    if not n:
        return []
    fam = family_of(n)
    if fam:
        return [(fam, n)]
    out = []
    for fam, temps in _TEMPLATES.items():
        for t in temps:
            c = _fit(n, t)
            if c and family_of(c) == fam and (fam, c) not in out:
                out.append((fam, c))
    return out


def tag_sort_key(tag):
    """Natural sort: family, then the numbers inside ('CB9' < 'CB11', '331CBP02' < '331CBP10')."""
    t = normalize(tag)
    return (family_of(t) or "~", [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", t)])
