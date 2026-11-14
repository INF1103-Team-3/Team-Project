"""Rank BRNS candidates against a validated BIS search request."""

import json
import re
import sys
from BRNS.classes.logic.evaluation.recommendation_context import RecommendationContext
from datetime import datetime, timedelta, timezone

from BRNS import config
from BRNS.classes.logic.logic_manager import LogicManager
from BRNS.classes.logic.evaluation.budget_fit_policy import BudgetFitPolicy
from BRNS.classes.logic.evaluation.restaurant_outcome_policy import RestaurantOutcomePolicy
from BRNS.classes.logic.evaluation.opening_hours_service import OpeningHoursService
from common import debug_log as log


_RATING_FLOOR = re.compile(
    r"\b(?:minimum|min\.?|at least|no less than|above|over)\s*"
    r"(?:rating\s*(?:of\s*)?|rated\s*)?"
    r"(\d+(?:\.\d+)?)\s*(?:stars?|/\s*5|rating)\b"
    r"|\b(\d+(?:\.\d+)?)\s*(?:stars?|/\s*5)\s*"
    r"(?:or higher|or above|and up|minimum|\+)(?!\w)"
    r"|\b(\d+(?:\.\d+)?)\s*\+\s*(?:stars?|/\s*5)\b",
    re.IGNORECASE,
)
_ANY_RATING = re.compile(
    r"\b(?:rating\s*(?:of\s*)?|rated\s*)"
    r"([1-5](?:\.\d+)?)\s*(?:stars?|/\s*5)?\b"
    r"|\b([1-5](?:\.\d+)?)\s*(?:stars?|/\s*5|rating)\b",
    re.IGNORECASE,
)
_HARD_LANGUAGE = re.compile(
    r"\b(?:only|must|required|hard requirement|minimum|at least|"
    r"no less than|exclusively)\b", re.IGNORECASE,
)

_MANAGER = None
_OUTCOME_POLICY = None


def _outcome_policy():
    global _OUTCOME_POLICY
    if _OUTCOME_POLICY is None:
        _OUTCOME_POLICY = RestaurantOutcomePolicy(sys.modules[__name__])
    return _OUTCOME_POLICY


def manager():
    """Return the configured BRNS Logic Manager."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LogicManager(
            normalize_candidate,
            _outcome_policy().evaluate,
            _grounded_ai_reasons,
            lambda: config.MAX_MATCHES_SHOWN,
            lambda: config.MAX_ALTERNATIVES_SHOWN,
            minimum_rating,
            has_hard_preferences,
            today_hours_from_weekly,
            RecommendationContext(sys.modules[__name__]),
            confidence_rating=confidence_adjusted_rating,
        )
    return _MANAGER


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


def preferred_rating(preferences):
    """Read any stated star preference, including a soft bare rating."""
    ratings = [
        float(next(group for group in match.groups() if group))
        for preference in preferences
        for match in _ANY_RATING.finditer(preference)
    ]
    if any(not 1 <= rating <= 5 for rating in ratings):
        raise ValueError("Preferred Google rating must be between 1 and 5 stars.")
    return max(ratings, default=None)


def hard_required_cuisines(preferences):
    """Read canonical hard cuisines confirmed by BIS."""
    required = []
    for preference in preferences:
        text = preference.casefold()
        for cuisine in _SUPPORTED_CUISINES:
            escaped = re.escape(cuisine)
            if (re.search(rf"\bonly\s+{escaped}(?:\s+cuisine)?\b", text)
                    or re.search(rf"\b{escaped}\s+(?:cuisine\s+)?only\b", text)
                    or re.search(rf"\b(?:must be|exclusively)\s+{escaped}\b",
                                 text)):
                if cuisine not in required:
                    required.append(cuisine)
    return required


def has_hard_preferences(preferences):
    return any(_HARD_LANGUAGE.search(item) for item in preferences)


def confidence_adjusted_rating(rating, review_count):
    """Shrink small review samples toward 4/5 for ranking comparisons."""
    if (type(rating) not in (int, float) or not 1 <= rating <= 5
            or type(review_count) is not int or review_count < 0):
        return None
    return round((rating * review_count + 4 * 100) / (review_count + 100), 3)


def sort_results(results, sort_by):
    """Sort matches and alternatives while preserving their classifications."""
    return manager().sort_results(results, sort_by)


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
    certification = candidate.get("halal_certification")
    muis_check = candidate.get("muis_check")
    officially_verified = (
        certification == "official" and isinstance(muis_check, dict)
        and muis_check.get("status") == "verified")
    candidate["halal_status"] = (
        "official" if officially_verified
        else "unofficial" if candidate.get("halal_hint")
        or certification == "unofficial"
        or "halal" in candidate["dietary_requirements"] else "unverified")
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
    """Preserve the function API through the shared outcome policy."""
    return _outcome_policy().evaluate(restaurant, request)



def _grounded_ai_reasons(restaurant, request, codes, candidate_id=None):
    """Translate only AI reason codes proven by candidate facts."""
    mode = request["mode"]
    budget = request["budget_per_person"]
    average = restaurant.get("avg_price")
    range_end = restaurant.get("price_end")
    range_start = restaurant.get("price_start")
    budget_kind, budget_reason = BudgetFitPolicy.evaluate_budget(restaurant, budget)
    budget_within_limit = budget_kind == "reason"
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
            budget_within_limit,
            budget_reason if budget_within_limit
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
    if (not isinstance(codes, list)
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


def recommendation_order(restaurants, recommendations):
    """Validate the complete AI ordering before another manager uses it."""
    return manager().recommendation_order(restaurants, recommendations)


def rank_restaurants(restaurants, request, recommendations=None,
                     previous_restaurants=()):
    """Verify AI IDs and reasons, then enforce requirements on every candidate."""
    return manager().rank_restaurants(
        restaurants, request, recommendations, previous_restaurants)


# ---------- Opening-hours decisions (Logic) ----------

_OPENING_HOURS = OpeningHoursService()
SINGAPORE = _OPENING_HOURS.SINGAPORE
DAYS = _OPENING_HOURS.DAYS
WEEK_MINUTES = _OPENING_HOURS.WEEK_MINUTES


def _minute(point):
    return _OPENING_HOURS._minute(point)


def _intervals(hours):
    return _OPENING_HOURS._intervals(hours)


def _local_now(now=None):
    return _OPENING_HOURS._local_now(now)


def _today_index(now):
    return _OPENING_HOURS._today_index(now)


def _fmt(minute):
    return _OPENING_HOURS._fmt(minute)


def open_now_from_weekly(hours, now=None):
    """Check saved regular opening hours against Singapore local time."""
    return _OPENING_HOURS.open_now_from_weekly(hours, now)


def today_hours_from_weekly(hours, now=None):
    """Describe today's saved hours for the offline result card."""
    return _OPENING_HOURS.today_hours_from_weekly(hours, now)


def weekly_opening_hours(hours):
    """Convert regular Google periods into a Monday–Sunday week."""
    return _OPENING_HOURS.weekly_opening_hours(hours)


def today_hours(hours, now=None):
    """Display today's live hours, including overnight periods."""
    return _OPENING_HOURS.today_hours(hours, now)


def open_now(hours, now=None):
    """Prefer Google's flag; otherwise evaluate its regular periods."""
    return _OPENING_HOURS.open_now(hours, now)


def evaluate(record):
    """Apply all BRNS business rules to one AI-ordered restaurant."""
    if not isinstance(record, dict):
        raise ValueError("Logic evaluation needs a record dictionary.")
    restaurant = normalize_candidate(record["restaurant"])
    status, numeric_score, reasons = decide_outcome(
        restaurant, record["request"])
    return {"restaurant": restaurant, "decision": status,
            "score": numeric_score, "reasons": reasons}


def score(record):
    """Return the numeric score from an evaluated BRNS record."""
    evaluated = record if "decision" in record else evaluate(record)
    return evaluated["score"]


def route(record):
    """Route an evaluated restaurant to match, alternative, or rejection."""
    evaluated = record if "decision" in record else evaluate(record)
    return evaluated["decision"]
