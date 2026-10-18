"""Lookalike-domain detection: homoglyph folding plus fuzzy matching (rapidfuzz) against known domains.

A sender domain is a lookalike when it is not itself known but either folds to a known domain after mapping
confusable characters (1->l, 0->o, rn->m, vv->w, Cyrillic/Greek letters, dropped hyphens), or is within a small
edit distance of one (an inserted, dropped or swapped letter). Exact known domains never match themselves.
"""

import unicodedata
from dataclasses import dataclass

from rapidfuzz.distance import DamerauLevenshtein

# Confusables seen in invoice-redirection fraud. Multi-character sequences are folded before single characters.
SEQUENCES = {"rn": "m", "vv": "w", "cl": "d", "ii": "u"}
HOMOGLYPHS = {
    "0": "o", "1": "l", "3": "e", "5": "s", "7": "t", "8": "b", "|": "l", "!": "i", "i": "l",
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "l", "ј": "j", "ԁ": "d", "ӏ": "l",
    "ѕ": "s", "һ": "h", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h",
    # Greek
    "α": "a", "ο": "o", "ρ": "p", "ν": "v", "τ": "t", "ι": "l", "κ": "k", "χ": "x",
}
MAX_EDITS = 2
MIN_LABEL_LEN = 6


@dataclass(frozen=True)
class LookalikeMatch:
    domain: str
    imitates: str
    method: str  # homoglyph | edit_distance
    edits: int


def _label(domain: str) -> tuple[str, str]:
    d = domain.lower().strip().rstrip(".")
    try:
        d = d.encode("ascii").decode("idna") if d.startswith("xn--") or ".xn--" in d else d
    except UnicodeError:
        pass
    label, _, tld = d.partition(".")
    return unicodedata.normalize("NFKC", label), tld


def fold(label: str) -> str:
    s = label.lower().replace("-", "").replace("_", "")
    for seq, rep in SEQUENCES.items():
        s = s.replace(seq, rep)
    return "".join(HOMOGLYPHS.get(c, c) for c in s)


def find_lookalike(domain: str, known: frozenset[str]) -> LookalikeMatch | None:
    d = domain.lower()
    if not d or d in known:
        return None
    label, tld = _label(d)
    folded = fold(label)
    best: LookalikeMatch | None = None
    for k in sorted(known):
        k_label, k_tld = _label(k)
        if label == k_label and tld != k_tld:  # same name, different TLD
            return LookalikeMatch(d, k, "tld_swap", 0)
        if fold(k_label) == folded:
            return LookalikeMatch(d, k, "homoglyph", DamerauLevenshtein.distance(label, k_label))
        if min(len(label), len(k_label)) < MIN_LABEL_LEN:
            continue
        edits = DamerauLevenshtein.distance(label, k_label)
        if tld == k_tld and 0 < edits <= MAX_EDITS and (best is None or edits < best.edits):
            best = LookalikeMatch(d, k, "edit_distance", edits)
    return best
