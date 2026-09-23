"""Deterministic hard constraints and explainable recommendation ranking."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from debug import debug_log
from schemas import is_number, normalize_request, validate_request

WEIGHTS = {"food": 35, "profile": 25, "walking": 20, "price": 15, "variety": 5}


def prepare_request(request, profile=None):
    error = validate_request(request)
    if error:
        return None, error
    result = normalize_request(request)
    profile = profile or {}
    for field in ("allergies", "dietary_requirements"):
        saved = profile.get(field, [])
        if not isinstance(saved, list) or not all(isinstance(v, str) for v in saved):
            return None, "Stored safety preferences are invalid; repair the profile first."
        result[field] = sorted(set(result[field]) | {v.casefold() for v in saved})
    if result["unsupported_requirements"]:
        return None, "Some requirements need clarification. Use manual search to restate them."
    if result["walking_time_max"] is not None and result["location"] is None:
        return None, "A walking limit requires latitude and longitude."
    if result["open_now"] and result["requested_time"]:
        return None, "Choose either open now or a specific time."
    return result, None


def opening_status(restaurant, when):
    """Weekly hours are local; include prior-day overnight intervals."""
    hours = restaurant.get("opening_hours")
    if not isinstance(hours, dict) or not hours.get("source_ids"):
        return None
    try:
        local = when.astimezone(ZoneInfo(hours["timezone"]))
        exceptions = hours.get("exceptions", {})
        known_today = False
        for offset in (0, -1):
            day = local.date() + timedelta(days=offset)
            intervals = exceptions.get(day.isoformat(),
                                       hours["weekly"].get(str(day.weekday())))
            if intervals is None:
                continue
            if offset == 0:
                known_today = True
            for start, end in intervals:
                start_time = datetime.strptime(start, "%H:%M").time()
                end_time = datetime.strptime(end, "%H:%M").time()
                begin = datetime.combine(day, start_time, local.tzinfo)
                finish = datetime.combine(day, end_time, local.tzinfo)
                if finish <= begin:
                    finish += timedelta(days=1)
                if begin <= local < finish:
                    return True
        return False if known_today else None
    except (ValueError, TypeError, KeyError, ZoneInfoNotFoundError):
        return None


def confirmed(claim):
    return isinstance(claim, dict) and claim.get("confirmed") is True


def eligible_items(restaurant, request):
    """A single meal must satisfy price, diet AND allergy evidence together."""
    matches = []
    for item in restaurant["menu"]:
        if any(not confirmed(item.get("dietary", {}).get(diet))
               for diet in request["dietary_requirements"]):
            continue
        if any(not confirmed(item.get("allergen_free", {}).get(allergy))
               or item["allergen_free"][allergy].get("cross_contact_excluded") is not True
               for allergy in request["allergies"]):
            continue
        price = item.get("price")
        if request["budget_max"] is not None:
            if not is_number(price) or price > request["budget_max"]:
                continue
        matches.append(item)
    return matches


def score_candidate(restaurant, item, request, profile, walking):
    cuisines = {value.casefold() for value in restaurant["cuisines"]}
    foods = {value.casefold() for value in item.get("food_tags", [])}
    matches = len(cuisines & set(request["cuisines"])) + len(foods & set(request["foods"]))
    requested = len(request["cuisines"]) + len(request["foods"])
    counts = profile.get("cuisine_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    learned = max((min(counts.get(c, 0), 10) / 10 for c in cuisines
                   if type(counts.get(c, 0)) is int and counts.get(c, 0) >= 0), default=0)
    price = item.get("price")
    scores = {
        "food": WEIGHTS["food"] * matches / max(requested, 1),
        "profile": WEIGHTS["profile"] * learned,
        "walking": WEIGHTS["walking"] / (1 + walking / 10) if walking is not None else 0,
        "price": WEIGHTS["price"] / (1 + price / 10) if is_number(price) else 0,
        "variety": WEIGHTS["variety"] if restaurant["restaurant_id"] not in
        profile.get("selected_ids", []) else 0,
    }
    return {key: round(value, 3) for key, value in scores.items()}


def recommend(restaurants, request, profile=None, routes=None, when=None):
    profile, routes = profile or {}, routes or {}
    request, error = prepare_request(request, profile)
    if error:
        return [], {"request": 1}, error
    when = datetime.fromisoformat(request["requested_time"]) if request["requested_time"] else (
        when or datetime.now(timezone.utc))
    results, excluded = [], {"meal_constraints": 0, "walking": 0, "opening": 0}
    for restaurant in restaurants:
        items = eligible_items(restaurant, request)
        if not items:
            excluded["meal_constraints"] += 1
            continue
        walking = routes.get(restaurant["restaurant_id"])
        if not is_number(walking):
            walking = None
        if request["walking_time_max"] is not None and (
            walking is None or walking > request["walking_time_max"]
        ):
            excluded["walking"] += 1
            continue
        opened = opening_status(restaurant, when)
        if (request["open_now"] or request["requested_time"]) and opened is not True:
            excluded["opening"] += 1
            continue
        scored = [(score_candidate(restaurant, item, request, profile, walking), item)
                  for item in items]
        scores, item = min(scored, key=lambda pair: (-sum(pair[0].values()), pair[1]["name"]))
        results.append({"restaurant": restaurant, "item": item, "walking_minutes": walking,
                        "open": opened, "scores": scores, "score": round(sum(scores.values()), 3)})
    debug_log("filtered", count=sum(excluded.values()))
    results.sort(key=lambda value: (-value["score"], value["restaurant"]["restaurant_id"]))
    debug_log("ranked", count=len(results))
    return results[:5], excluded, None


def record_selection(profile, restaurant):
    """Small deterministic learning step, preserving hard requirements."""
    result = dict(profile)
    counts = dict(result.get("cuisine_counts", {}))
    for cuisine in restaurant["cuisines"]:
        cuisine = cuisine.casefold()
        counts[cuisine] = min(10, counts.get(cuisine, 0) + 1)
    result["cuisine_counts"] = counts
    result["selected_ids"] = sorted(set(result.get("selected_ids", [])) |
                                    {restaurant["restaurant_id"]})
    debug_log("profile_updated")
    return result
