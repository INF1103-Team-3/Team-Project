"""Rank BRNS candidates against a validated BIS search request."""

from BRNS import config


def normalize_candidate(record, *, offline=False):
    """Keep known facts; never turn a search hint into certification."""
    candidate = dict(record)
    # The future checker owns official certification; do not return
    # legacy catalog claims as an official BRNS result.
    candidate.pop("certification", None)
    raw_cuisines = candidate.get("cuisines")
    if raw_cuisines is None:
        raw_cuisines = [candidate.get("cuisine")]
    candidate["cuisines"] = [
        item for item in raw_cuisines or [] if isinstance(item, str)
        and item in _SUPPORTED_CUISINES
    ]
    raw_diet = candidate.get("dietary_requirements")
    if raw_diet is None:
        legacy = candidate.get("dietary")
        raw_diet = ["vegetarian"] if legacy in ("vegetarian", "vegan") else (
            ["halal"] if legacy == "halal" else [])
    candidate["dietary_requirements"] = [
        item for item in raw_diet if item in ("halal", "vegetarian")
    ]
    candidate["halal_status"] = (
        "unofficial" if candidate.get("halal_hint")
        or "halal" in candidate["dietary_requirements"] else "unverified"
    )
    # Catalog walk times have no origin and cannot establish today's travel.
    if offline:
        candidate["walk_minutes"] = None
        candidate["walk_meters"] = None
        candidate["drive_minutes"] = None
        candidate["drive_meters"] = None
        candidate["walk_source"] = None
        candidate["drive_source"] = None
        candidate["source"] = "offline catalog"
    return candidate


# This imports BIS's shared vocabulary without importing its interactive code.
from BIS.sources.profile_schema import CUISINES as _SUPPORTED_CUISINES


def decide_outcome(restaurant, request):
    """Return match, alternative, or reject with explicit reasons."""
    reasons = []
    problems = []
    unverified = []
    cuisines = restaurant.get("cuisines") or []
    if set(cuisines) & set(request["disliked_cuisines"]):
        return "reject", 0, ["contains a disliked cuisine"]
    wanted = request["cuisine"]
    if wanted in cuisines:
        reasons.append("matches your selected cuisine")
    elif cuisines:
        problems.append("does not match your selected cuisine")
    else:
        unverified.append("cuisine unavailable")

    dietary = set(restaurant.get("dietary_requirements") or [])
    for requirement in request["dietary_requirements"]:
        if requirement == "halal":
            if restaurant.get("halal_status") == "unofficial":
                unverified.append("Halal (unofficial; not checked)")
            else:
                unverified.append("halal status unverified")
        elif requirement == "vegetarian" and "vegetarian" not in dietary:
            unverified.append("vegetarian options unverified")

    budget = request["budget_per_person"]
    price = restaurant.get("avg_price")
    minimum_price = restaurant.get("price_start")
    if price is not None:
        if price > budget:
            problems.append(
                f"average price SGD {price:g} exceeds your SGD {budget:g} budget")
        else:
            reasons.append("average price is within your budget")
    elif minimum_price is not None:
        if minimum_price > budget:
            problems.append(
                f"prices start at SGD {minimum_price:g}, over your budget")
        else:
            unverified.append("some prices may fit; full budget unverified")
    else:
        unverified.append("price unavailable")

    mode = request["mode"]
    meters = restaurant.get(f"{mode}_meters")
    source = restaurant.get(f"{mode}_source")
    if source != "route" or meters is None:
        unverified.append("travel distance estimated or unavailable")
    elif meters > request["max_distance_km"] * 1000:
        problems.append("route exceeds your distance limit")
    else:
        reasons.append("within your route distance limit")

    if "spicy" in " ".join(request["other_preferences"]):
        if restaurant.get("spicy_options") is True:
            reasons.append("has spicy options")
    if problems or unverified:
        return "alternative", 0, (
            reasons + [f"! {item}" for item in problems + unverified])
    return "match", len(reasons), reasons


def rank_restaurants(restaurants, request, suggested_order=None):
    """Validate every AI suggestion; use its order only within safe groups."""
    if suggested_order is None:
        order = list(range(len(restaurants)))
    else:
        if (not isinstance(suggested_order, list)
                or any(type(index) is not int or index < 0
                       or index >= len(restaurants)
                       for index in suggested_order)
                or len(suggested_order) != len(set(suggested_order))):
            raise ValueError("BRNS AI returned invalid restaurant IDs.")
        order = suggested_order + [
            index for index in range(len(restaurants))
            if index not in suggested_order
        ]
    matches, alternatives = [], []
    hidden = 0
    for index in order:
        raw = restaurants[index]
        restaurant = normalize_candidate(
            raw, offline=raw.get("source") == "offline catalog")
        status, score, reasons = decide_outcome(restaurant, request)
        item = {"restaurant": restaurant, "score": score, "reasons": reasons}
        if status == "match":
            matches.append(item)
        elif status == "alternative":
            alternatives.append(item)
        else:
            hidden += 1
    if suggested_order is None:
        matches.sort(key=lambda item: item["score"], reverse=True)
    return {
        "matches": matches[:config.MAX_MATCHES_SHOWN],
        "alternatives": alternatives[:config.MAX_ALTERNATIVES_SHOWN],
        "hidden": hidden,
        "mode": request["mode"],
        "requested_dietary": request["dietary_requirements"],
    }
