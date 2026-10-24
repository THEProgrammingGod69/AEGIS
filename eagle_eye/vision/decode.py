"""Closed-vocabulary decoding of OCR reads and the wire-ferrule parser.

The drawing's vocabulary is the only source of truth for what a label may say. ``decode`` maps a read onto it in
increasing order of tolerance (exact -> OCR-confusion classes -> one edit -> unique containment) and refuses to
guess when two tags explain the read equally well. A read that is itself a well-formed tag of its family but not in
the vocabulary ('TS2', 'CB17', '334CBP06') is never "corrected" by edit distance: a wrong label must stay visible, so
it comes back as ``tag_like`` with its near neighbours as ``candidates``.
"""
import re

from kb.tags import canonical, coerce_to_family, family_of, normalize, tag_sort_key


def _within1(a, b):
    """True when the edit distance between a and b is <= 1 (O(n))."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] if la == lb else a[i:] == b[i + 1:]


def edit_distance(a, b, limit=None):
    """Levenshtein distance; with ``limit`` returns ``limit + 1`` as soon as it is exceeded."""
    if limit is not None and abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if limit is not None and min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


class Vocab:
    """Index of a drawing vocabulary: exact tags, confusion-canonical forms and canonical-length buckets."""

    def __init__(self, vocabulary):
        self.tags = sorted({normalize(t) for t in vocabulary if normalize(t)}, key=tag_sort_key)
        self.exact = set(self.tags)
        self.canon = {}
        self.by_len = {}
        for t in self.tags:
            c = canonical(t)
            self.canon.setdefault(c, []).append(t)
            self.by_len.setdefault(len(c), []).append((c, t))
        self._memo = {}

    def __contains__(self, tag):
        return normalize(tag) in self.exact

    def __iter__(self):
        return iter(self.tags)

    def __len__(self):
        return len(self.tags)

    def near(self, c, dist=1):
        """Tags whose canonical form is within ``dist`` edits of canonical string ``c``."""
        out = []
        for n in range(len(c) - dist, len(c) + dist + 1):
            for tc, t in self.by_len.get(n, ()):
                if (_within1(c, tc) if dist == 1 else edit_distance(c, tc, dist) <= dist):
                    out.append(t)
        return out

    def containing(self, c):
        """Tags whose canonical form contains canonical string ``c``."""
        return [t for n, items in self.by_len.items() if n > len(c) for tc, t in items if c in tc]


def _as_vocab(vocab):
    return vocab if isinstance(vocab, Vocab) else Vocab(vocab or ())


def decode(token_or_text, vocab):
    """Decode a read (Token dict or string) against the vocabulary -> Read dict.

    ``{"tag", "method": exact|confusion|edit1|partial|None, "raw", "norm", "candidates", "ambiguous", "family",
    "tag_like"}``. ``tag`` is set only when exactly one vocabulary tag explains the read; ``tag_like`` is the read
    coerced onto a tag family when it is tag-shaped but not in the vocabulary (an unknown / wrong label candidate).
    """
    vocab = _as_vocab(vocab)
    raw = token_or_text.get("text", "") if isinstance(token_or_text, dict) else str(token_or_text or "")
    norm = normalize(raw)
    key = norm
    if key in vocab._memo:
        return dict(vocab._memo[key], raw=raw)
    read = _decode(norm, vocab)
    vocab._memo[key] = read
    return dict(read, raw=raw)


def _decode(norm, vocab):
    out = {"tag": None, "method": None, "norm": norm, "candidates": [], "ambiguous": False, "family": None,
           "tag_like": None}
    if not norm:
        return out
    fam = family_of(norm)

    def found(tag, method):
        out.update(tag=tag, method=method, candidates=[tag], family=family_of(tag))
        return out

    if norm in vocab.exact:
        return found(norm, "exact")
    c = canonical(norm)
    hits = vocab.canon.get(c, [])
    coerced = coerce_to_family(norm)
    if not hits:
        hits = sorted({t for _f, t in coerced if t in vocab.exact}, key=tag_sort_key)
    if len(hits) == 1:
        return found(hits[0], "confusion")
    if len(hits) > 1:
        out.update(candidates=hits, ambiguous=True, family=fam)
        return out

    near = sorted(set(vocab.near(c, 1)), key=tag_sort_key) if len(c) >= 3 else []
    tag_like = norm if fam else (coerced[0][1] if len(coerced) == 1 else None)
    if tag_like:
        # A well-formed tag (as read, or after fixing confusable characters) that the drawing does not list:
        # report it, never "correct" it by edit distance onto a neighbour.
        out.update(family=family_of(tag_like), tag_like=tag_like, candidates=near)
        return out
    if len(near) == 1:
        return found(near[0], "edit1")
    if len(near) > 1:
        out.update(candidates=near, ambiguous=True)
        return out
    if len(c) >= 5:
        best = [t for t in vocab.containing(c) if len(c) >= 0.6 * len(canonical(t))]
        if len(best) == 1:
            return found(best[0], "partial")
        if best:
            out.update(candidates=sorted(best, key=tag_sort_key), ambiguous=True)
    return out


def partial_candidates(norm, vocab):
    """Vocabulary tags a partial read may belong to: tags containing it (read >= 3 chars) or within 2 edits.

    Returns ``[{"tag", "dist", "contains"}]`` sorted by distance; the checks combine this with the predicted
    position (a partial read that only one nearby expected tag explains counts as support).
    """
    vocab = _as_vocab(vocab)
    c = canonical(norm)
    if not c:
        return []
    out = {}
    if len(c) >= 3:
        for t in vocab.containing(c):
            out[t] = {"tag": t, "dist": edit_distance(c, canonical(t)), "contains": True}
    for n in range(max(1, len(c) - 2), len(c) + 3):
        for tc, t in vocab.by_len.get(n, ()):
            if t not in out:
                d = edit_distance(c, tc, 2)
                if d <= 2:
                    out[t] = {"tag": t, "dist": d, "contains": False}
    return sorted(out.values(), key=lambda r: (r["dist"], not r["contains"], tag_sort_key(r["tag"])))


# ------------------------------------------------------------------ ferrules
_PIN = re.compile(r"^(?:[A-Z0-9]{1,4})(?:-[A-Z0-9]{1,4})?$")
_SLASH_LIKE = "1LI7"          # what OCR makes of a '/' it cannot see as one


def _pin(p):
    p = p.strip("-")
    if p in ("I", "O"):
        p = {"I": "1", "O": "0"}[p]
    elif len(p) <= 2 and any(ch.isdigit() for ch in p):
        p = p.replace("I", "1").replace("O", "0")
    return p if p and _PIN.match(p) else None


def _device(d, vocab):
    """(device, score): 3 exact vocabulary tag, 2 decoded onto one, 1 well-formed family tag, 0 invalid."""
    if not d:
        return None, 0
    if vocab is not None:
        if d in vocab.exact:
            return d, 3
        r = decode(d, vocab)
        if r["tag"] and r["method"] in ("confusion", "edit1"):
            return r["tag"], 2
    if family_of(d):
        return d, 1
    co = coerce_to_family(d)
    if len(co) == 1:
        return co[0][1], 1
    return None, 0


def _parse_end(s, vocab):
    """Best (device, pin|None, score) split of one ferrule end such as 'X-FSW1-3', 'SPD1-UNPR-L', 'PS12-PE'.

    Preference: the better-known device (vocabulary > family pattern), then a split at a '-', then the longest device.
    """
    best = None
    for i in range(1, len(s) + 1):
        dev_raw, rest = s[:i], s[i:]
        pin = _pin(rest) if rest else None
        if rest and pin is None:
            continue
        dev, score = _device(dev_raw.strip("-"), vocab)
        if not score:
            continue
        rank = (score, rest.startswith("-") or not rest, len(dev_raw))
        if best is None or rank > best[3]:
            best = (dev, pin, score, rank)
    return best


def parse_ferrule(text, vocab=None):
    """Parse a wire ferrule '<DEV>-<PIN>/<DEV>-<PIN>' -> ``{"raw", "norm", "from", "to", "partial"}`` or None.

    Devices may contain '-' (X-FSW1-3 -> X-FSW1 pin 3; SPD1-UNPR-L -> SPD1 pin UNPR-L); the split uses the longest
    vocabulary device when ``vocab`` is given, else the tag-family patterns. Tolerates OCR noise: I/O for 1/0 in
    pins, a '/' read as '1', 'L' or 'I' or lost entirely, and spaces. ``from`` / ``to`` are ``{"device", "pin",
    "known"}`` (``known``: device is in the vocabulary); ``partial`` is True when a pin is missing.
    """
    raw = text.get("text", "") if isinstance(text, dict) else str(text or "")
    norm = normalize(raw)
    if "-" not in norm or len(norm) < 5:
        return None
    vocab = _as_vocab(vocab) if vocab is not None else None
    candidates = []
    if norm.count("/") == 1:
        a, b = norm.split("/")
        candidates.append((a, b, 0))
    elif "/" not in norm:
        for i in range(2, len(norm) - 1):
            if norm[i] in _SLASH_LIKE and norm[i - 1] != "-":
                candidates.append((norm[:i], norm[i + 1:], 1))
            candidates.append((norm[:i], norm[i:], 2))
    best = None
    for a, b, penalty in candidates:
        fa, fb = _parse_end(a, vocab), _parse_end(b, vocab)
        if not fa or not fb or (fa[1] is None and fb[1] is None):
            continue
        rank = (fa[2] + fb[2] + (fa[1] is not None) + (fb[1] is not None), -penalty, len(a))
        if best is None or rank > best[0]:
            best = (rank, fa, fb)
    if best is None:
        return None
    _rank, fa, fb = best

    def end(f):
        return {"device": f[0], "pin": f[1], "known": vocab is not None and f[0] in vocab.exact}
    out = {"raw": raw, "from": end(fa), "to": end(fb), "partial": fa[1] is None or fb[1] is None}
    out["norm"] = "/".join(f"{e['device']}-{e['pin']}" if e["pin"] else e["device"] for e in (out["from"], out["to"]))
    return out


# ------------------------------------------------------------------ token classification
ANCHOR_METHODS = ("exact", "confusion")      # reads certain enough to place the photo on the drawing
ANCHOR_MIN_LEN = 3                           # 'IE', 'X1' are too easily read off other print to place a photo


def _centre(box):
    return [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0]


def classify_tokens(tokens, vocab):
    """Split OCR tokens into device-label reads, wire-ferrule reads and unknown tag-shaped reads.

    Returns ``{"reads", "ferrules", "unknown"}``; every entry keeps the token index ``i``, ``box``, ``center``, ``conf``,
    ``passes`` and ``rot``. ``reads`` are vocabulary tags (``anchor`` True for exact / confusion decodes),
    ``ferrules`` parsed ``A-n/B-m`` markers, ``unknown`` tag-shaped reads the drawing does not list (``tag_like``).
    A token that decodes exactly onto a tag is a label even when it could also parse as a ferrule ('X-FSW1').
    """
    vocab = _as_vocab(vocab)
    out = {"reads": [], "ferrules": [], "unknown": []}
    for i, t in enumerate(tokens or ()):
        box = [float(v) for v in t["box"]]
        base = {"i": i, "raw": t.get("text", ""), "box": box, "center": _centre(box), "conf": float(t.get("conf", 0)),
                "passes": int(t.get("passes", 1)), "rot": int(t.get("rot", 0))}
        r = decode(t, vocab)
        if r["tag"] and r["method"] == "exact":
            out["reads"].append(dict(base, tag=r["tag"], method="exact", norm=r["norm"],
                                     anchor=len(r["tag"]) >= ANCHOR_MIN_LEN))
            continue
        f = parse_ferrule(t, vocab) if ("/" in r["norm"] or "-" in r["norm"]) else None
        if f and (("/" in r["norm"] and (f["from"]["known"] or f["to"]["known"]))
                  or (not f["partial"] and f["from"]["known"] and f["to"]["known"])):
            # the text's own quadrilateral: the wire runs along it (wire colour samples along the sleeve)
            out["ferrules"].append(dict(base, quad=t.get("quad"), **{k: f[k] for k in ("norm", "from", "to", "partial")}))
            continue
        if r["tag"] and not r["ambiguous"]:
            out["reads"].append(dict(base, tag=r["tag"], method=r["method"], norm=r["norm"],
                                     anchor=r["method"] in ANCHOR_METHODS and len(r["tag"]) >= ANCHOR_MIN_LEN))
        elif r["tag_like"]:
            out["unknown"].append(dict(base, tag_like=r["tag_like"], family=r["family"], norm=r["norm"],
                                       candidates=r["candidates"]))
    return out
