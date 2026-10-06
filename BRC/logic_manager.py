from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from models import SearchRequest

OUTCOME_ACCEPT = "accept"
OUTCOME_FLAG = "flag"
OUTCOME_REJECT = "reject"

CERT_CERTIFIED = "halal-certified"
CERT_NOT_LISTED = "not-listed"
CERT_UNVERIFIED = "unverified"
CERT_NOT_APPLICABLE = "n/a"

MAX_RESULTS = 5  # how many restaurants are shown per search
PRICE_NEAR_BUDGET_RATIO = 0.8
NAME_MATCH_THRESHOLD = 0.85
HALAL_VERIFY_CUISINES = {
    "japanese",
    "korean",
    "chinese",
    "western",
    "italian",
    "french",
    "steakhouse",
    "pub",
    "bar",
}
FISH_SHELLFISH_ALLERGENS = {
    "fish",
    "shellfish",
    "crustaceans",
    "molluscs",
}

_NAME_NOISE = {
    "restaurant", "cafe", "pte", "ltd", "the", "and", "bistro",
    "eating", "house", "singapore", "outlet", "halal", "certified",
}
_POSTAL_RE = re.compile(r"\b(\d{6})\b")


# --------------------------------------------------------- certificate matching


def _postal_from_address(address: str | None) -> str | None:
    found = _POSTAL_RE.findall(address or "")
    return found[-1] if found else None  # Singapore addresses end with the postal code


def _normalize_name(name: str | None) -> str:
    text = re.sub(r"\(.*?\)", " ", (name or "").lower())  # drop bracketed branch info
    text = re.split(r"\s[-–—@|]\s", text)[0]  # drop " - AMK" style suffixes
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = text.split()
    kept = [t for t in tokens if t not in _NAME_NOISE]
    return " ".join(kept or tokens)


def _name_similarity(a: str | None, b: str | None) -> float:
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    containment = 0.9 if len(short) >= 2 and short <= long_ else 0.0
    return max(SequenceMatcher(None, na, nb).ratio(), containment)


def build_directory_index(directory: list[dict] | None) -> dict | None:
    """Group directory entries by postal code. None means no usable directory data."""
    index: dict[str, list[dict]] = {}
    for entry in directory or []:
        postal = entry.get("postal_code")
        if postal:
            index.setdefault(str(postal), []).append(entry)
    return index or None


def match_certification(name: str, postal: str, index: dict) -> dict | None:
    """Best directory entry with this postal code and a similar name, or None."""
    best, best_score = None, 0.0
    for entry in index.get(postal, []):
        score = _name_similarity(name, entry.get("name"))
        if score > best_score:
            best, best_score = entry, score
    return best if best_score >= NAME_MATCH_THRESHOLD else None


def _check_certification(record: dict, request: SearchRequest, index: dict | None):
    """Return (certification status, matching directory entry or None)."""
    if request.food_type == "vegetarian":
        return CERT_UNVERIFIED, None
    if request.food_type != "halal":
        return CERT_NOT_APPLICABLE, None

    postal = _postal_from_address(record.get("address"))
    if index is None or postal is None:
        return CERT_UNVERIFIED, None  # nothing to check against

    match = match_certification(record.get("name", ""), postal, index)
    return (CERT_CERTIFIED, match) if match else (CERT_NOT_LISTED, None)


# --------------------------------------------------------------- record logic


def _cuisine_from_type(primary_type: str) -> str:
    label = re.sub(r"\s*restaurant$", "", primary_type or "", flags=re.IGNORECASE)
    return label.strip().lower() or "restaurant"


def _resolve_fields(record: dict, request: SearchRequest, index: dict | None) -> dict:
    """Merge Google data, AI output and the certificate check into final fields."""
    out = dict(record)
    out["cuisine"] = (record.get("cuisine") or _cuisine_from_type(record.get("primary_type", ""))).lower()
    out["food_type"] = request.food_type
    out["dietary"] = request.food_type

    status, match = _check_certification(record, request, index)
    out["certification"] = status
    if match:
        out["certificate_name"] = match.get("name")
        out["certificate_type"] = match.get("type")
        out["certificate_url"] = match.get("profile_url")

    if record.get("price_google") is not None:
        out["avg_price"], out["price_source"] = record["price_google"], "google"
    elif record.get("ai_avg_price") is not None:
        out["avg_price"], out["price_source"] = record["ai_avg_price"], "ai"
    else:
        out["avg_price"], out["price_source"] = None, None
    return out


def _score(record: dict, request: SearchRequest) -> float:
    """0-100: rating (50), closeness (20), price fit (10), halal certification (20)."""
    rating = record.get("rating")
    rating_part = (rating if rating is not None else 3.0) / 5 * 50

    walk = record.get("walk_minutes")
    if walk is None or request.max_walk_min <= 0:
        walk_part = 10.0
    else:
        walk_part = (1 - min(walk, request.max_walk_min) / request.max_walk_min) * 20

    price = record.get("avg_price")
    if request.max_budget and price is not None:
        price_part = (1 - min(price / request.max_budget, 1)) * 10
    else:
        price_part = 5.0

    # Certified halal is best, not listed is worst; everything else is neutral.
    cert_part = {CERT_CERTIFIED: 20.0, CERT_NOT_LISTED: 0.0}.get(record.get("certification"), 10.0)

    return round(rating_part + walk_part + price_part + cert_part, 1)


def evaluate_record(record: dict, request: SearchRequest, directory_index: dict | None = None) -> dict:
    """Apply the business rules to one AI-enriched record."""
    rec = _resolve_fields(record, request, directory_index)
    rejects: list[str] = []
    flags: list[str] = []

    walk = rec.get("walk_minutes")
    rating = rec.get("rating")
    price = rec.get("avg_price")

    # --- reject rules
    if walk is not None and walk > request.max_walk_min:
        rejects.append(f"Walk of {walk} min is over your {request.max_walk_min} min limit.")

    if request.min_rating > 0:
        if rating is None:
            rejects.append("No rating yet.")
        elif rating < request.min_rating:
            rejects.append(f"Rated {rating:.1f}, below your minimum of {request.min_rating:.1f}.")

    if request.max_budget is not None and price is not None and price > request.max_budget:
        rejects.append(f"Average price {price:g} is over your budget of {request.max_budget:g}.")

    # --- flag rules (multi-condition, using AI output fields)
    if (
        rec.get("price_source") == "ai"
        and request.max_budget is not None
        and price is not None
        and request.max_budget * PRICE_NEAR_BUDGET_RATIO <= price <= request.max_budget
    ):
        flags.append("Price is an AI estimate close to your budget; check the menu.")

    if (
        request.food_type == "halal"
        and rec["certification"] == CERT_UNVERIFIED
        and rec["cuisine"] in HALAL_VERIFY_CUISINES
    ):
        flags.append(f"Halal status unverified for {rec['cuisine']} cuisine; confirm with the restaurant.")

    seafood = FISH_SHELLFISH_ALLERGENS & set(rec.get("allergens") or [])
    if request.food_type == "vegetarian" and rec["certification"] == CERT_UNVERIFIED and seafood:
        flags.append(
            f"AI lists likely fish or shellfish ({', '.join(sorted(seafood))}); "
            "confirm vegetarian options with the restaurant."
        )

    if request.food_type == "halal" and rec["certification"] == CERT_NOT_LISTED:
        flags.append("Not found in the halal-certified list; confirm halal status with the restaurant.")

    if rec.get("ai_status") != "ok":
        flags.append("AI details unavailable; cuisine, allergens and spice are unknown.")

    if rejects:
        rec["outcome"] = OUTCOME_REJECT
        rec["reasons"] = rejects + flags
    elif flags:
        rec["outcome"] = OUTCOME_FLAG
        rec["reasons"] = flags
    else:
        rec["outcome"] = OUTCOME_ACCEPT
        rec["reasons"] = []

    rec["score"] = _score(rec, request)
    return rec


def process(records: list[dict], request: SearchRequest, directory_index: dict | None = None) -> list[dict]:
    """Evaluate every record. Returns all of them, including rejected ones."""
    return [evaluate_record(r, request, directory_index) for r in records]


def select_for_display(processed: list[dict], limit: int = MAX_RESULTS) -> list[dict]:
    """The top `limit` accepted or flagged records, best match first."""
    shown = [r for r in processed if r["outcome"] != OUTCOME_REJECT]
    return sorted(shown, key=lambda r: r["score"], reverse=True)[:limit]


def count_matching(processed: list[dict]) -> int:
    """How many records passed the filters (accepted or flagged)."""
    return sum(1 for r in processed if r["outcome"] != OUTCOME_REJECT)


def count_rejected(processed: list[dict]) -> int:
    return sum(1 for r in processed if r["outcome"] == OUTCOME_REJECT)


def summarize(records: list[dict]) -> dict:
    """Statistics over saved records, for the I/O Manager's summary view."""

    def average(values):
        values = [v for v in values if isinstance(v, (int, float))]
        return round(sum(values) / len(values), 2) if values else None

    return {
        "total": len(records),
        "by_outcome": dict(Counter(r.get("outcome", "unknown") for r in records)),
        "by_food_type": dict(Counter(r.get("food_type", "unknown") for r in records)),
        "avg_rating": average(r.get("rating") for r in records),
        "avg_price": average(r.get("avg_price") for r in records),
        "top_cuisines": Counter(
            r.get("cuisine") for r in records if r.get("cuisine")
        ).most_common(3),
    }
