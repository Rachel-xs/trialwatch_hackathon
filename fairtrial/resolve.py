"""Step 7: case resolution across documents.

Conservative: link records only when the names match AND nothing conflicts
(province, case number). Everything else becomes a duplicate *candidate* for human review.

Names match on three rules, in order: identical normalised form; one name's words are all
contained in the other's ("Diananta" vs "Diananta Putra Sumedi"); or a rapidfuzz score of at
least FUZZ_THRESHOLD, which catches spelling variants ("Putra" vs "Putera"). The looser two
rules additionally require an identical province, since a partial name is weaker evidence.
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from .schemas import CandidateCase, EvidenceClaim, SupportStatus

TITLES = re.compile(r"\b(wartawan|jurnalis|pemred|pemimpin redaksi|bung|pak|bu|sdr|saudara)\b\.?", re.I)


def norm_name(name: str) -> str:
    n = unicodedata.normalize("NFKC", name or "").lower()
    n = TITLES.sub(" ", n)
    n = re.sub(r"\(\s*\d+\s*\)", " ", n)  # "AS (35)" -> "as"
    return " ".join(re.sub(r"[^a-z ]", " ", n).split())


FUZZ_THRESHOLD = 85

# A first name common enough that it identifies nobody on its own: two unrelated "Muhammad X"
# must never merge just because the short form matches.
COMMON_FIRST = {"muhammad", "mohammad", "mohamad", "ahmad", "abdul", "nur", "siti", "dewi", "putri"}


def names_match(a: str, b: str) -> tuple[bool, str]:
    """(matched, rule) where rule is 'exact', 'variant', 'short' or ''.

    'variant' is a spelling difference with the same number of name parts (Putra/Putera,
    Wahidin/Walidin, Diananta/Diantara): every part must be close AND the whole must be close.
    'short'   is one name being a longer form of the other (Diananta -> Diananta Putra Sumedi):
    the shorter name's parts must all appear in the longer one and its first part must be
    distinctive - 6+ letters and not a common given name.
    """
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False, ""
    if na == nb:
        return True, "exact"
    ta, tb = na.split(), nb.split()
    if len(ta) == len(tb) and all(fuzz.ratio(x, y) >= 75 for x, y in zip(ta, tb)) \
            and fuzz.ratio(na, nb) >= FUZZ_THRESHOLD:
        return True, "variant"
    short, long_ = (ta, tb) if len(ta) < len(tb) else (tb, ta)
    if len(short) < len(long_) and len(short[0]) >= 6 and short[0] not in COMMON_FIRST \
            and fuzz.ratio(short[0], long_[0]) >= FUZZ_THRESHOLD \
            and all(max(fuzz.ratio(x, y) for y in long_) >= FUZZ_THRESHOLD for x in short):
        return True, "short"
    return False, ""


def matches_known(case: CandidateCase, known: set[str]) -> bool:
    """Known-case lookup under the same name rules, over the main name and every alias."""
    for name in [case.person_name_original, *case.person_aliases]:
        if any(names_match(name, k)[0] for k in known):
            return True
    return False


# ---------------------------------------------------------------- provinces
# All 38 Indonesian provinces. Key is the canonical code; the values are the spellings seen
# in English and Indonesian sources. Comparing provinces by raw string made two reports of
# the same case look like a conflict ("South Sulawesi" vs "Sulawesi Selatan").
PROVINCES = {
    "aceh": ["aceh", "nanggroe aceh darussalam", "nad"],
    "north sumatra": ["north sumatra", "north sumatera", "sumatera utara", "sumatra utara", "sumut"],
    "west sumatra": ["west sumatra", "west sumatera", "sumatera barat", "sumatra barat", "sumbar"],
    "riau": ["riau"],
    "riau islands": ["riau islands", "kepulauan riau", "kepri"],
    "jambi": ["jambi"],
    "south sumatra": ["south sumatra", "south sumatera", "sumatera selatan", "sumatra selatan", "sumsel"],
    "bengkulu": ["bengkulu"],
    "lampung": ["lampung"],
    "bangka belitung islands": ["bangka belitung islands", "bangka belitung", "kepulauan bangka belitung", "babel"],
    "jakarta": ["jakarta", "dki jakarta", "daerah khusus ibukota jakarta", "daerah khusus jakarta", "jakarta raya"],
    "west java": ["west java", "jawa barat", "jabar"],
    "central java": ["central java", "jawa tengah", "jateng"],
    "yogyakarta": ["yogyakarta", "di yogyakarta", "daerah istimewa yogyakarta", "jogja", "jogjakarta"],
    "east java": ["east java", "jawa timur", "jatim"],
    "banten": ["banten"],
    "bali": ["bali"],
    "west nusa tenggara": ["west nusa tenggara", "nusa tenggara barat", "ntb"],
    "east nusa tenggara": ["east nusa tenggara", "nusa tenggara timur", "ntt"],
    "west kalimantan": ["west kalimantan", "kalimantan barat", "kalbar"],
    "central kalimantan": ["central kalimantan", "kalimantan tengah", "kalteng"],
    "south kalimantan": ["south kalimantan", "kalimantan selatan", "kalsel"],
    "east kalimantan": ["east kalimantan", "kalimantan timur", "kaltim"],
    "north kalimantan": ["north kalimantan", "kalimantan utara", "kaltara"],
    "north sulawesi": ["north sulawesi", "sulawesi utara", "sulut"],
    "central sulawesi": ["central sulawesi", "sulawesi tengah", "sulteng"],
    "south sulawesi": ["south sulawesi", "sulawesi selatan", "sulsel"],
    "southeast sulawesi": ["southeast sulawesi", "south east sulawesi", "sulawesi tenggara", "sultra"],
    "gorontalo": ["gorontalo"],
    "west sulawesi": ["west sulawesi", "sulawesi barat", "sulbar"],
    "maluku": ["maluku", "moluccas"],
    "north maluku": ["north maluku", "maluku utara", "malut"],
    "papua": ["papua", "irian jaya"],
    "west papua": ["west papua", "papua barat"],
    "south papua": ["south papua", "papua selatan"],
    "central papua": ["central papua", "papua tengah"],
    "highland papua": ["highland papua", "papua pegunungan", "mountainous papua"],
    "southwest papua": ["southwest papua", "south west papua", "papua barat daya"],
}
_PROVINCE_LOOKUP = {v: k for k, vs in PROVINCES.items() for v in vs}

_DROP_WORDS = re.compile(r"\b(province|provinsi|propinsi|prov|daerah istimewa|daerah khusus|ibukota|kota|kabupaten|regency|city)\b", re.I)


# French sources (A009 is RSF in French) write the compass point as a separate word, either after
# the island ("Sulawesi du Sud") or hyphenated before it ("Sud-Kalimantan"). Rather than spell out
# a third list of 38 names, translate the direction words and compare the set of words, which makes
# word order irrelevant and covers the Indonesian ordering too ("Papua Barat" = "West Papua").
_WORD_MAP = {
    # French
    "sud": "south", "nord": "north", "ouest": "west", "est": "east",
    "centre": "central", "centrale": "central", "central": "central",
    "occidental": "west", "occidentale": "west", "oriental": "east", "orientale": "east",
    "meridional": "south", "meridionale": "south", "septentrional": "north", "septentrionale": "north",
    "iles": "islands", "ile": "islands", "sulawesi": "sulawesi", "celebes": "sulawesi",
    "borneo": "kalimantan", "moluques": "maluku",
    # Indonesian
    "selatan": "south", "utara": "north", "barat": "west", "timur": "east", "tengah": "central",
    "tenggara": "southeast", "kepulauan": "islands", "pegunungan": "highland",
    "sumatera": "sumatra", "jawa": "java", "jogja": "yogyakarta", "jogjakarta": "yogyakarta",
}
_PARTICLES = {"du", "de", "des", "la", "le", "les", "l", "d", "au", "aux", "en",
              "of", "the", "and", "dan"}


def _word_set(value) -> frozenset:
    t = unicodedata.normalize("NFKD", str(value or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z ]", " ", _DROP_WORDS.sub(" ", t))
    return frozenset(_WORD_MAP.get(w, w) for w in t.split() if w and w not in _PARTICLES)


# every spelling we know, indexed by its word set, so any ordering or language resolves
_PROVINCE_WORDS = {}
for _canon, _names in PROVINCES.items():
    for _n in [_canon, *_names]:
        _PROVINCE_WORDS.setdefault(_word_set(_n), _canon)

# Every word that can appear in a province name, in any of the three languages. Used by
# eval/eval_gold.py to drop a trailing province from a court name ("Kotabaru District Court,
# South Kalimantan"). Never strip these blindly: Jambi, Bengkulu, Gorontalo, Yogyakarta,
# Banten, Bali, Aceh, Papua and Riau are also the names of cities that host a court.
PROVINCE_WORDS = frozenset(
    w
    for _n in [*PROVINCES, *(v for vs in PROVINCES.values() for v in vs)]
    for w in re.findall(r"[a-z]+", _n)
) | frozenset(_WORD_MAP) | frozenset(_WORD_MAP.values())

# City / regency -> province, so "Palopo" is compatible with "South Sulawesi". Covers the 38
# provincial capitals plus the places this corpus mentions; it is NOT all 514 regencies, so an
# unlisted city falls back to a plain string comparison rather than a wrong match.
CITIES = {
    "banda aceh": "aceh", "medan": "north sumatra", "padang": "west sumatra", "pekanbaru": "riau",
    "tanjung pinang": "riau islands", "batam": "riau islands", "jambi": "jambi",
    "palembang": "south sumatra", "bengkulu": "bengkulu", "bandar lampung": "lampung",
    "pangkal pinang": "bangka belitung islands", "pangkalpinang": "bangka belitung islands",
    "jakarta pusat": "jakarta", "jakarta selatan": "jakarta", "jakarta barat": "jakarta",
    "jakarta timur": "jakarta", "jakarta utara": "jakarta", "central jakarta": "jakarta",
    "bandung": "west java", "bogor": "west java", "depok": "west java", "bekasi": "west java",
    "semarang": "central java", "surakarta": "central java", "solo": "central java",
    "yogyakarta": "yogyakarta", "surabaya": "east java", "malang": "east java", "sidoarjo": "east java",
    "serang": "banten", "tangerang": "banten", "cilegon": "banten", "denpasar": "bali",
    "mataram": "west nusa tenggara", "kupang": "east nusa tenggara", "pontianak": "west kalimantan",
    "palangkaraya": "central kalimantan", "palangka raya": "central kalimantan",
    "banjarmasin": "south kalimantan", "banjarbaru": "south kalimantan", "kotabaru": "south kalimantan",
    "samarinda": "east kalimantan", "balikpapan": "east kalimantan", "tanjung selor": "north kalimantan",
    "manado": "north sulawesi", "palu": "central sulawesi", "makassar": "south sulawesi",
    "palopo": "south sulawesi", "parepare": "south sulawesi", "kendari": "southeast sulawesi",
    "gorontalo": "gorontalo", "mamuju": "west sulawesi", "ambon": "maluku", "ternate": "north maluku",
    "sofifi": "north maluku", "jayapura": "papua", "manokwari": "west papua", "merauke": "south papua",
    "nabire": "central papua", "wamena": "highland papua", "sorong": "southwest papua",
}

def province_key(value) -> str:
    """Canonical province, or '' when the spelling is not recognised."""
    t = unicodedata.normalize("NFKC", str(value or "")).lower()
    t = " ".join(re.sub(r"[^a-z ]", " ", _DROP_WORDS.sub(" ", t)).split())
    if not t:
        return ""
    if t in _PROVINCE_LOOKUP:
        return _PROVINCE_LOOKUP[t]
    if t in CITIES:
        return CITIES[t]
    ws = _word_set(value)
    if ws in _PROVINCE_WORDS:                           # "Sulawesi du Sud", "Sud-Kalimantan"
        return _PROVINCE_WORDS[ws]
    for name, canon in _PROVINCE_LOOKUP.items():       # "serang, banten" / "south sulawesi province"
        if re.search(rf"\b{re.escape(name)}\b", t):
            return canon
    for city, canon in CITIES.items():
        if re.search(rf"\b{re.escape(city)}\b", t):
            return canon
    return ""


def same_province(a, b) -> bool:
    """True when both sides name the same province, in either language, or a city inside it."""
    ka, kb = province_key(a), province_key(b)
    if ka and kb:
        return ka == kb
    return _plain(a) == _plain(b)      # unrecognised spelling: fall back to a literal match


# ---------------------------------------------------------------- value comparison
def _plain(v) -> str:
    """Lower-case, punctuation and extra whitespace removed."""
    t = unicodedata.normalize("NFKC", str(v or "")).lower()
    return " ".join(re.sub(r"[^\w ]", " ", t).split())


def same_text(a, b, threshold: int = FUZZ_THRESHOLD) -> bool:
    """Two free-text values that mean the same thing: 'Berita News' / 'Berita.News'."""
    pa, pb = _plain(a), _plain(b)
    if pa == pb:
        return True
    if not pa or not pb:
        return False
    return fuzz.token_set_ratio(pa, pb) >= threshold


# Fields where two sources disagreeing is a real contradiction worth a human's eye.
# province / case_number are absent on purpose: a conflict there blocks the merge outright.
# procedural_status, event_dates and first_seen_at are absent too: they have defined
# precedence (latest stage wins, earliest sighting wins), so a difference is progression.
CONFLICT_FIELDS = ("court", "outlet_name", "charges_original", "charges_en",
                   "legal_provisions_original", "detention_status", "work_link")
CONFLICT_ENUM_FIELDS = ("complainant_type", "dewan_pers_status", "outlet_type")


def _known(v) -> bool:
    return str(v or "").strip().lower() not in ("", "unknown", "none")


def _find_conflicts(m: CandidateCase, case: CandidateCase) -> list[dict]:
    """Fields where both records give a value and the values really differ.

    Free text is compared after dropping case and punctuation, then by rapidfuzz similarity,
    so 'Berita News' vs 'Berita.News' is not a conflict. Enum fields stay an exact comparison:
    'bypassed' and 'referred' are different answers, not different spellings.
    """
    found = []
    for f in CONFLICT_FIELDS:
        va, vb = getattr(m, f), getattr(case, f)
        if not (_known(va) and _known(vb)):
            continue
        if f == "province" and same_province(va, vb):
            continue
        if same_text(va, vb):
            continue
        found.append({"field": f, "kept": str(va), "other": str(vb)})
    for f in CONFLICT_ENUM_FIELDS:
        va, vb = getattr(m, f).value, getattr(case, f).value
        if _known(va) and _known(vb) and va != vb:
            found.append({"field": f, "kept": va, "other": vb})
    return found


def _compatible(a: CandidateCase, b: CandidateCase) -> bool:
    """Nothing contradicts. Province is compared in canonical form, so the same place written
    in English and in Indonesian no longer blocks a merge."""
    if _known(a.province) and _known(b.province) and not same_province(a.province, b.province):
        return False
    # case numbers differ legitimately across stages (district vs appeal vs kasasi), so they only
    # block a merge when both look like the same kind of number and still differ
    na, nb = a.case_number, b.case_number
    if _known(na) and _known(nb):
        kind = lambda n: re.sub(r"[^a-z.]", "", n.lower().split("/")[1] if "/" in n else n.lower())
        if kind(na) == kind(nb) and _plain(na) != _plain(nb):
            return False
    return True


def resolve(items: list[tuple[CandidateCase, list[EvidenceClaim]]]):
    """Returns (merged list of (case, claims), duplicate_candidates, field_conflicts).

    duplicate_candidates: (case_id_a, case_id_b, reason) for records that look like the same
    case but could not be merged. field_conflicts: one entry per field where the merged
    sources disagreed; the claims for that field are marked needs_review rather than silently
    resolved in favour of whichever source happened to be processed first.
    """
    merged: list[tuple[CandidateCase, list[EvidenceClaim]]] = []
    dup_candidates = []
    field_conflicts: list[dict] = []
    for case, claims in items:
        target = None
        for i, (m, _) in enumerate(merged):
            matched, rule = names_match(m.person_name_original, case.person_name_original)
            if not matched:
                continue
            if not _compatible(m, case):
                dup_candidates.append((m.case_id, case.case_id,
                                       f"{rule} name match, conflicting province/case number"))
                continue
            # a partial or misspelt name is weaker evidence: demand an identical province
            if rule in ("variant", "short") and not same_province(m.province, case.province):
                dup_candidates.append((m.case_id, case.case_id,
                                       f"{rule} name match, province differs "
                                       f"({m.province!r} vs {case.province!r})"))
                continue
            target = i
            break
        if target is None:
            merged.append((case, claims))
            continue
        m, mclaims = merged[target]
        for c in claims:
            c.case_id = m.case_id
        # a disagreement between sources goes to human review instead of first-one-wins
        conflicts = _find_conflicts(m, case)
        for c in conflicts:
            field_conflicts.append({
                "case_id": m.case_id,
                "field": c["field"],
                "values": [{"value": c["kept"], "source_ids": list(m.source_ids)},
                           {"value": c["other"], "source_ids": list(case.source_ids)}],
                "kept": c["kept"],
            })
        conflicted = {c["field"] for c in conflicts}
        for c in mclaims + claims:
            if c.field in conflicted:
                c.support_status = SupportStatus.needs_review
        # keep the longer spelling as the display name; the shorter becomes an alias
        if len(case.person_name_original.strip()) > len(m.person_name_original.strip()):
            m.person_name_original, shorter = case.person_name_original, m.person_name_original
        else:
            shorter = case.person_name_original
        aliases = set(m.person_aliases) | set(case.person_aliases) | {shorter}
        m.person_aliases = sorted(a for a in aliases
                                  if a.strip() and norm_name(a) != norm_name(m.person_name_original))
        m.source_ids = sorted(set(m.source_ids) | set(case.source_ids))
        # earliest sighting wins for first_seen
        if case.first_seen_at and (not m.first_seen_at or case.first_seen_at < m.first_seen_at):
            m.first_seen_at, m.first_seen_source_type = case.first_seen_at, case.first_seen_source_type
        # fill unknown fields; later stage overrides earlier stage
        for f in ("province", "court", "case_number", "outlet_name", "charges_original", "charges_en",
                  "legal_provisions_original", "detention_status", "work_link"):
            if getattr(m, f) == "unknown" and getattr(case, f) != "unknown":
                setattr(m, f, getattr(case, f))
        for f in ("complainant_type", "dewan_pers_status", "outlet_type"):
            if getattr(m, f).value == "unknown" and getattr(case, f).value != "unknown":
                setattr(m, f, getattr(case, f))
        if STAGE_ORDER.index(case.procedural_status.value) > STAGE_ORDER.index(m.procedural_status.value):
            m.procedural_status = case.procedural_status
        m.event_dates.update({k: v for k, v in case.event_dates.items() if k not in m.event_dates})
        merged[target] = (m, mclaims + claims)
    return merged, dup_candidates, field_conflicts


STAGE_ORDER = ["unknown", "reported_to_police", "summoned", "investigation", "suspect", "detained",
               "prosecution", "trial", "verdict", "appeal", "dropped"]
