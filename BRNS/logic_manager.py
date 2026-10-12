"""Rank BRNS candidates against a validated BIS search request."""

import json
import re
from datetime import datetime, timedelta, timezone

from BRNS import config
from shared import debug_log as log


_RATING_FLOOR = re.compile(
    r"\b(?:minimum|min\.?|at least|no less than|above|over)\s*"
    r"(?:rating\s*(?:of\s*)?|rated\s*)?"
    r"(\d+(?:\.\d+)?)\s*(?:stars?|/\s*5|rating)\b"
    r"|\b(\d+(?:\.\d+)?)\s*(?:stars?|/\s*5)\s*"
    r"(?:or higher|or above|and up|minimum|\+)(?!\w)"
    r"|\b(\d+(?:\.\d+)?)\s*\+\s*(?:stars?|/\s*5)\b",
    re.IGNORECASE,
)


def minimum_rating(preferences):
    """Read explicit Google star floors from today's free-text wishes."""
    ratings = []
    for preference in preferences:
        for match in _RATING_FLOOR.finditer(preference):
            rating = float(next(group for group in match.groups() if group))
            if not 1 <= rating <= 5:
                raise ValueError("Minimum Google rating must be between 1 and 5 stars.")
            ratings.append(rating)
    return max(ratings, default=None)


def confidence_adjusted_rating(rating, review_count):
    """Shrink small review samples toward 4/5 for ranking comparisons."""
    if (type(rating) not in (int, float) or not 1 <= rating <= 5
            or type(review_count) is not int or review_count < 0):
        return None
    return round((rating * review_count + 4 * 100) / (review_count + 100), 3)


def normalize_candidate(record, *, offline=False):
    """Keep known facts; never turn a search hint into certification."""
    candidate = dict(record)
    # The future checker owns official certification; do not return
    # saved claims as an official BRNS result.
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
    # Saved records have no route from today's origin.
    if offline:
        candidate["walk_minutes"] = None
        candidate["walk_meters"] = None
        candidate["drive_minutes"] = None
        candidate["drive_meters"] = None
        candidate["transit_minutes"] = None
        candidate["transit_meters"] = None
        candidate["walk_source"] = None
        candidate["drive_source"] = None
        candidate["transit_source"] = None
        candidate["source"] = "offline restaurants"
    return candidate


# This imports BIS's shared vocabulary without importing its interactive code.
from BIS.sources.profile_schema import CUISINES as _SUPPORTED_CUISINES


def decide_outcome(restaurant, request):
    """Return match, alternative, or reject with explicit reasons."""
    if restaurant.get("source") in ("google places", "saved + google places") \
            and restaurant.get("open_now") is not True:
        return "reject", 0, ["not confirmed open now"]
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
    maximum_price = restaurant.get("price_end")
    if price is not None:
        if price > budget:
            problems.append(
                f"average price SGD {price:g} exceeds your SGD {budget:g} budget")
        else:
            reasons.append("average price is within your budget")
    elif minimum_price is not None and minimum_price > budget:
        problems.append(
            f"prices start at SGD {minimum_price:g}, over your budget")
    elif (maximum_price is not None and maximum_price <= budget
          and (minimum_price is None or minimum_price <= maximum_price)):
        reasons.append("listed price range is within your budget")
    elif minimum_price is not None:
        unverified.append("some prices may fit; full budget unverified")
    else:
        unverified.append("price unavailable")

    rating_floor = minimum_rating(request["other_preferences"])
    if rating_floor is not None:
        rating = restaurant.get("rating")
        if type(rating) not in (int, float) or not 1 <= rating <= 5:
            unverified.append(
                f"Google rating unavailable; requested at least {rating_floor:g}/5")
        elif rating < rating_floor:
            problems.append(
                f"Google rating {rating:g}/5 is below your {rating_floor:g}/5 minimum")
        else:
            reasons.append(f"Google rating meets your {rating_floor:g}/5 minimum")

    mode = request["mode"]
    source = restaurant.get(f"{mode}_source")
    if request["max_travel_minutes"] is not None:
        minutes = restaurant.get(f"{mode}_minutes")
        if source != "route" or minutes is None:
            unverified.append(f"{mode} journey time unavailable")
        elif minutes > request["max_travel_minutes"]:
            problems.append(
                f"{mode} journey is {minutes:g} min, over your "
                f"{request['max_travel_minutes']:g} min limit")
        else:
            reasons.append(f"within your {mode} time limit")
    else:
        meters = restaurant.get(f"{mode}_meters")
        if source != "route" or meters is None:
            unverified.append("travel distance estimated or unavailable")
        elif meters > request["max_distance_km"] * 1000:
            problems.append(
                f"route is {meters / 1000:.2f} km, over your "
                f"{request['max_distance_km']:g} km limit")
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
    average = restaurant.get("avg_price")
    range_end = restaurant.get("price_end")
    range_start = restaurant.get("price_start")
    average_within_budget = (
        type(average) in (int, float) and 0 <= average <= budget)
    range_within_budget = (
        average is None and type(range_end) in (int, float)
        and 0 <= range_end <= budget
        and (range_start is None or 0 <= range_start <= range_end))
    if request["max_travel_minutes"] is not None:
        travel_within_limit = (
            restaurant.get(f"{mode}_source") == "route"
            and type(restaurant.get(f"{mode}_minutes")) in (int, float)
            and 0 <= restaurant[f"{mode}_minutes"]
            <= request["max_travel_minutes"])
        travel_reason = f"within your {mode} time limit"
    else:
        travel_within_limit = (
            restaurant.get(f"{mode}_source") == "route"
            and type(restaurant.get(f"{mode}_meters")) in (int, float)
            and 0 <= restaurant[f"{mode}_meters"]
            <= request["max_distance_km"] * 1000)
        travel_reason = "within your route distance limit"
    checks = {
        "cuisine_match": (
            request["cuisine"] != "none"
            and request["cuisine"] in restaurant["cuisines"],
            "matches your selected cuisine"),
        "within_budget": (
            average_within_budget or range_within_budget,
            "average price is within your budget" if average_within_budget
            else "listed price range is within your budget"),
        "within_route": (
            travel_within_limit, travel_reason),
        "well_rated": (
            type(restaurant.get("rating")) in (int, float)
            and 4 <= restaurant["rating"] <= 5,
            f"rated {restaurant['rating']:g} out of 5 on Google"
            if type(restaurant.get("rating")) in (int, float) else "rating unavailable"),
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
            "candidate_avg_price_sgd": average,
            "candidate_price_start_sgd": range_start,
            "candidate_price_end_sgd": range_end},
        "within_route": {
            "mode": mode,
            "limit_m": (request["max_distance_km"] * 1000
                        if request["max_distance_km"] is not None else None),
            "limit_minutes": request["max_travel_minutes"],
            "travel_m": restaurant.get(f"{mode}_meters"),
            "travel_minutes": restaurant.get(f"{mode}_minutes"),
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


def rank_restaurants(restaurants, request, recommendations=None,
                     previous_restaurants=()):
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
            raw, offline=raw.get("source") == "offline restaurants")
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
    previous_keys = {
        (str(item.get("name", "")).casefold().strip(),
         str(item.get("address", "")).casefold().strip())
        for item in previous_restaurants if isinstance(item, dict)
    }

    def was_returned(item):
        restaurant = item["restaurant"]
        return (str(restaurant.get("name", "")).casefold().strip(),
                str(restaurant.get("address", "")).casefold().strip()) in previous_keys

    matches.sort(key=was_returned)
    alternatives.sort(key=was_returned)
    visible_matches = matches[:config.MAX_MATCHES_SHOWN]
    visible_alternatives = alternatives[:config.MAX_ALTERNATIVES_SHOWN]
    return {
        "matches": visible_matches,
        "alternatives": visible_alternatives,
        "new_count": sum(not was_returned(item) for item in
                         visible_matches + visible_alternatives),
        "hidden": hidden,
        "mode": request["mode"],
        "limit_unit": "minutes" if request["max_travel_minutes"] is not None else "km",
        "traffic_aware": request["traffic_aware"],
        "requested_dietary": request["dietary_requirements"],
    }


# ---------- Opening-hours decisions (Logic) ----------

SINGAPORE = timezone(timedelta(hours=8))
DAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday")
WEEK_MINUTES = 7 * 24 * 60


def _minute(point):
    if not isinstance(point, dict):
        return None
    day, hour, minute = point.get("day"), point.get("hour", 0), point.get("minute", 0)
    if (type(day) is not int or not 0 <= day < 7
            or type(hour) is not int or not 0 <= hour < 24
            or type(minute) is not int or not 0 <= minute < 60):
        return None
    return day * 1440 + hour * 60 + minute


def _intervals(hours):
    if not isinstance(hours, dict):
        return []
    intervals = []
    for period in hours.get("periods") or []:
        if not isinstance(period, dict):
            continue
        start = _minute(period.get("open"))
        if start is None:
            continue
        if not period.get("close"):
            return [(0, WEEK_MINUTES)]
        end = _minute(period["close"])
        if end is None:
            continue
        if end <= start:
            end += WEEK_MINUTES
        intervals.append((start, end))
    return intervals


def _local_now(now=None):
    return now.astimezone(SINGAPORE) if now is not None else datetime.now(SINGAPORE)


def _today_index(now):
    return (now.weekday() + 1) % 7


def _fmt(minute):
    return f"{minute // 60:02d}:{minute % 60:02d}"


def open_now_from_weekly(hours, now=None):
    """Check saved regular opening hours against Singapore local time."""
    if not isinstance(hours, dict):
        return False
    now = _local_now(now)
    periods = hours.get(DAYS[_today_index(now)])
    if not isinstance(periods, list):
        return False
    if len(periods) == 2 and all(isinstance(part, str) for part in periods):
        periods = [periods]
    minute = now.hour * 60 + now.minute
    for period in periods:
        if (not isinstance(period, list) or len(period) != 2
                or any(not isinstance(part, str) or len(part) != 4
                       or not part.isdigit() for part in period)):
            continue
        start = int(period[0][:2]) * 60 + int(period[0][2:])
        end = int(period[1][:2]) * 60 + int(period[1][2:])
        if start <= minute < end or (end == 1439 and minute == 1439):
            return True
    return False


def today_hours_from_weekly(hours, now=None):
    """Describe today's saved hours for the offline result card."""
    if not isinstance(hours, dict):
        return "Hours unavailable"
    periods = hours.get(DAYS[_today_index(_local_now(now))])
    if periods is None:
        return "Hours unavailable"
    if not periods:
        return "Closed today"
    if len(periods) == 2 and all(isinstance(part, str) for part in periods):
        periods = [periods]
    if periods == [["0000", "2359"]]:
        return "Open 24 hours"
    return ", ".join(
        f"{pair[0][:2]}:{pair[0][2:]}–{pair[1][:2]}:{pair[1][2:]}"
        for pair in periods
        if isinstance(pair, list) and len(pair) == 2
        and all(isinstance(part, str) and len(part) == 4 for part in pair)
    ) or "Hours unavailable"


def weekly_opening_hours(hours):
    """Convert regular Google periods into a complete Monday–Sunday week.

    A single daily interval is [start, end]. Split shifts use a list of such
    pairs, and an empty list means Google listed that day as closed.
    """
    if not isinstance(hours, dict) or "periods" not in hours:
        return None
    week = {}
    for day_name in (*DAYS[1:], DAYS[0]):
        day_index = DAYS.index(day_name)
        day_start = day_index * 1440
        segments = set()
        for start, end in _intervals(hours):
            for shift in (-WEEK_MINUTES, 0, WEEK_MINUTES):
                left = max(day_start, start + shift)
                right = min(day_start + 1440, end + shift)
                if left < right:
                    local_start = left - day_start
                    local_end = right - day_start
                    segments.add((f"{local_start // 60:02d}{local_start % 60:02d}",
                                  "2359" if local_end == 1440 else
                                  f"{local_end // 60:02d}{local_end % 60:02d}"))
        intervals = [list(pair) for pair in sorted(segments)]
        week[day_name] = intervals[0] if len(intervals) == 1 else intervals
    return week


def today_hours(hours, now=None):
    """Display today's live hours, including overnight and 24-hour periods."""
    now = _local_now(now)
    day_start = _today_index(now) * 1440
    segments = []
    for start, end in _intervals(hours):
        for shift in (-WEEK_MINUTES, 0, WEEK_MINUTES):
            left = max(day_start, start + shift)
            right = min(day_start + 1440, end + shift)
            if left < right:
                segments.append((left - day_start, right - day_start))
    segments = sorted(set(segments))
    if segments == [(0, 1440)]:
        return "Open 24 hours"
    if not segments:
        if isinstance(hours, dict) and hours.get("periods") == []:
            return "Closed today"
        return "Hours unavailable"
    return ", ".join(
        f"{_fmt(start)}–{_fmt(end) if end < 1440 else '24:00'}"
        for start, end in segments)


def open_now(hours, now=None):
    """Prefer Google's special-hours-aware flag; otherwise check its periods."""
    if not isinstance(hours, dict):
        return None
    if type(hours.get("openNow")) is bool:
        return hours["openNow"]
    intervals = _intervals(hours)
    if not intervals:
        return False if "periods" in hours else None
    now = _local_now(now)
    minute = _today_index(now) * 1440 + now.hour * 60 + now.minute
    return any(start <= minute < end or start <= minute + WEEK_MINUTES < end
               for start, end in intervals)
