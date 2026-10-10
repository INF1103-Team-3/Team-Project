"""Rank BRNS candidates against a validated BIS search request."""

import json

from BRNS import config
from shared import debug_log as log


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
    if wanted == "none":
        pass
    elif wanted in cuisines:
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


def _grounded_ai_reasons(restaurant, request, codes, candidate_id=None):
    """Translate only AI reason codes proven by candidate facts."""
    mode = request["mode"]
    budget = request["budget_per_person"]
    checks = {
        "cuisine_match": (
            request["cuisine"] != "none"
            and request["cuisine"] in restaurant["cuisines"],
            "matches your selected cuisine"),
        "within_budget": (
            type(restaurant.get("avg_price")) in (int, float)
            and 0 <= restaurant["avg_price"] <= budget,
            "average price is within your budget"),
        "within_route": (
            restaurant.get(f"{mode}_source") == "route"
            and type(restaurant.get(f"{mode}_meters")) in (int, float)
            and 0 <= restaurant[f"{mode}_meters"]
            <= request["max_distance_km"] * 1000,
            "within your route distance limit"),
        "well_rated": (
            type(restaurant.get("rating")) in (int, float)
            and 4 <= restaurant["rating"] <= 5,
            "rated at least 4 out of 5"),
        "vegetarian_options": (
            "vegetarian" in request["dietary_requirements"]
            and "vegetarian" in restaurant["dietary_requirements"],
            "vegetarian options listed"),
        "halal_hint_unofficial": (
            "halal" in request["dietary_requirements"]
            and restaurant["halal_status"] == "unofficial",
            "Halal (unofficial; not checked)"),
        "spicy_options": (
            "spicy" in " ".join(request["other_preferences"])
            and restaurant.get("spicy_options") is True,
            "has spicy options"),
    }
    if (not isinstance(codes, list) or len(codes) > 4
            or any(not isinstance(code, str) or code not in checks
                   for code in codes)
            or len(codes) != len(set(codes))):
        log.debug_log(
            f"Candidate ID {candidate_id}: invalid reason-code list.",
            "ERROR", "BRNS.logic_manager.rank_restaurants")
        raise ValueError("BRNS AI returned unsupported reasons.")
    evidence = {
        "cuisine_match": {
            "requested_cuisine": request["cuisine"],
            "candidate_cuisines": restaurant["cuisines"]},
        "within_budget": {
            "budget_sgd": budget,
            "candidate_avg_price_sgd": restaurant.get("avg_price")},
        "within_route": {
            "mode": mode,
            "limit_m": request["max_distance_km"] * 1000,
            "travel_m": restaurant.get(f"{mode}_meters"),
            "travel_source": restaurant.get(f"{mode}_source")},
        "well_rated": {"candidate_rating": restaurant.get("rating")},
        "vegetarian_options": {
            "vegetarian_requested": (
                "vegetarian" in request["dietary_requirements"]),
            "candidate_dietary": restaurant["dietary_requirements"]},
        "halal_hint_unofficial": {
            "halal_requested": "halal" in request["dietary_requirements"],
            "candidate_halal_status": restaurant["halal_status"]},
        "spicy_options": {
            "spicy_requested": "spicy" in " ".join(
                request["other_preferences"]),
            "candidate_spicy_options": restaurant.get("spicy_options")},
    }
    grounded = []
    for code in codes:
        if not checks[code][0]:
            name = restaurant.get("name")
            if not isinstance(name, str):
                name = "<unnamed>"
            detail = {
                "candidate_id": candidate_id,
                "candidate_name": name[:100],
                "rejected_reason_code": code,
                "evidence": evidence[code],
            }
            log.debug_log(
                "AI reason unsupported: " + json.dumps(
                    detail, ensure_ascii=False, separators=(",", ":")),
                "WARNING", "BRNS.logic_manager.rank_restaurants")
            continue
        grounded.append(checks[code][1])
    return grounded


def rank_restaurants(restaurants, request, recommendations=None):
    """Verify AI IDs and reasons, then enforce requirements on every candidate."""
    if recommendations is None:
        # Kept for direct Logic tests; BRNS.main requires AI recommendations.
        order = list(range(len(restaurants)))
        ai_reasons = {}
    else:
        if (not isinstance(recommendations, list)
                or len(recommendations) != len(restaurants)
                or any(not isinstance(item, dict)
                       or set(item) != {"id", "reason_codes"}
                       or type(item["id"]) is not int
                       or item["id"] < 0 or item["id"] >= len(restaurants)
                       for item in recommendations)):
            raise ValueError("BRNS AI returned invalid restaurant IDs.")
        order = [item["id"] for item in recommendations]
        if len(set(order)) != len(restaurants):
            raise ValueError("BRNS AI returned duplicate restaurant IDs.")
        ai_reasons = {}
        for item in recommendations:
            restaurant = normalize_candidate(restaurants[item["id"]])
            ai_reasons[item["id"]] = _grounded_ai_reasons(
                restaurant, request, item["reason_codes"], item["id"])
    matches, alternatives = [], []
    hidden = 0
    for index in order:
        raw = restaurants[index]
        restaurant = normalize_candidate(
            raw, offline=raw.get("source") == "offline catalog")
        status, score, reasons = decide_outcome(restaurant, request)
        for reason in ai_reasons.get(index, []):
            if reason not in reasons and f"! {reason}" not in reasons:
                reasons.append(reason)
        item = {"restaurant": restaurant, "score": score, "reasons": reasons}
        if status == "match":
            matches.append(item)
        elif status == "alternative":
            alternatives.append(item)
        else:
            hidden += 1
    if recommendations is None:
        matches.sort(key=lambda item: item["score"], reverse=True)
    return {
        "matches": matches[:config.MAX_MATCHES_SHOWN],
        "alternatives": alternatives[:config.MAX_ALTERNATIVES_SHOWN],
        "hidden": hidden,
        "mode": request["mode"],
        "requested_dietary": request["dietary_requirements"],
    }
