"""Procedural profile and search decisions and conversions."""

import math
import re
from copy import deepcopy
from difflib import SequenceMatcher

from sources.profile_schema import (
    CUISINES, CUISINE_FIELDS, MINUTES_PER_KM, OTHER_PREFERENCES,
    UNSUPPORTED_CUISINES,
    PREFERENCE_FIELDS, clean_text, validate_preferences, validate_updates,
    validate_value, validate_travel_minutes,
)

COORDINATES = re.compile(
    r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*"
)

SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "max_travel_minutes", "traffic_aware", "cuisine",
    "budget_per_person", OTHER_PREFERENCES,
    "dietary_requirements", "disliked_cuisines",
}


SEARCH_CLARIFICATION_PREFIX = "SEARCH_CLARIFICATION: "


def search_clarification_error(message):
    """Return a procedural clarification error for the interactive loop."""
    return ValueError(SEARCH_CLARIFICATION_PREFIX + message)


def is_search_clarification(error):
    """Identify clarification errors without defining an exception class."""
    return (isinstance(error, ValueError)
            and str(error).startswith(SEARCH_CLARIFICATION_PREFIX))


def clarification_message(error):
    """Remove the internal marker before displaying an error."""
    return str(error)[len(SEARCH_CLARIFICATION_PREFIX):]


def validate_special_request_text(text):
    """Check a short English request before BIS sends it for interpretation."""
    text = clean_text(text, 100)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ,.'!?/&()+\-]*", text):
        raise ValueError(
            "Write your special request in English letters and words, "
            "such as chicken rice or a quiet cafe.")
    words = re.findall(r"[A-Za-z]+", text)
    if not words or not any(len(word) > 1 for word in words):
        raise ValueError(
            "Describe your request in English words, or press Enter for none.")
    return text


def validate_search_request(request, ai_response=None):
    """Validate AI interpretation while protecting confirmed search choices."""
    confirmed = _validate_search_fields(request)
    if ai_response is None:
        return confirmed
    try:
        proposed = _validate_search_fields(ai_response)
    except ValueError as error:
        raise ValueError(
            "The AI returned an invalid search request. Please retry.") from error
    protected = SEARCH_FIELDS - {OTHER_PREFERENCES}
    if any(proposed[field] != confirmed[field] for field in protected):
        raise search_clarification_error(
            "The AI interpretation conflicts with a confirmed choice. "
            "Please clarify what you want today.")
    if not set(confirmed[OTHER_PREFERENCES]).issubset(
            proposed[OTHER_PREFERENCES]):
        raise search_clarification_error(
            "The AI removed a selected preference. Please clarify your request.")
    return proposed


def _validate_search_fields(request):
    """Normalize the exact ten-field BIS/BRNS search contract."""
    if not isinstance(request, dict) or set(request) != SEARCH_FIELDS:
        raise ValueError("Today's search has an invalid set of fields.")
    origin = request["origin"]
    if not isinstance(origin, dict) or set(origin) != {
        "query", "label", "latitude", "longitude"
    }:
        raise ValueError("Today's search needs a confirmed location.")
    latitude, longitude = origin["latitude"], origin["longitude"]
    if (type(latitude) not in (int, float)
            or type(longitude) not in (int, float)
            or not in_singapore(latitude, longitude)):
        raise ValueError("Today's search location must be in Singapore.")
    if request["mode"] not in ("walk", "drive", "transit"):
        raise ValueError("Choose walk, drive, or transit for today's search.")
    if request["cuisine"] not in (*CUISINES, "none"):
        raise ValueError("Choose a supported cuisine or none for today's search.")
    for field in (OTHER_PREFERENCES, "dietary_requirements",
                  "disliked_cuisines"):
        if not isinstance(request[field], list):
            raise ValueError(f"{field} must be a list.")
    distance = request["max_distance_km"]
    minutes = request["max_travel_minutes"]
    if (distance is None) == (minutes is None):
        raise ValueError("Choose exactly one travel limit: distance or time.")
    if request["mode"] == "transit" and distance is not None:
        raise ValueError("Transit searches use a time limit.")
    distance = (validate_value("max_distance_km", distance)
                if distance is not None else None)
    minutes = validate_travel_minutes(minutes) if minutes is not None else None
    traffic_aware = request["traffic_aware"]
    if type(traffic_aware) is not bool or (traffic_aware and
            (request["mode"] != "drive" or minutes is None)):
        raise ValueError("Live traffic is available only for driving time searches.")
    budget = validate_value("budget_per_person", request["budget_per_person"])
    if budget is None:
        raise ValueError("Today's search needs a travel limit and budget.")
    preferences = validate_value(
        OTHER_PREFERENCES, request[OTHER_PREFERENCES])
    return {
        "origin": {
            "query": clean_text(origin["query"], 200),
            "label": clean_text(origin["label"], 500),
            "latitude": latitude, "longitude": longitude,
        },
        "mode": request["mode"], "max_distance_km": distance,
        "max_travel_minutes": minutes, "traffic_aware": traffic_aware,
        "cuisine": request["cuisine"], "budget_per_person": budget,
        OTHER_PREFERENCES: preferences,
        "dietary_requirements": validate_value(
            "dietary_requirements", request["dietary_requirements"]),
        "disliked_cuisines": validate_value(
            "disliked_cuisines", request["disliked_cuisines"]),
    }


def in_singapore(latitude, longitude):
    """Reject locations outside the app's supported search area."""
    return (math.isfinite(latitude) and math.isfinite(longitude)
            and 1.15 <= latitude <= 1.48
            and 103.60 <= longitude <= 104.10)


def parse_coordinates(text):
    match = COORDINATES.fullmatch(text)
    if not match:
        return None
    latitude, longitude = map(float, match.groups())
    if not in_singapore(latitude, longitude):
        raise ValueError("Enter coordinates within Singapore.")
    return latitude, longitude


def is_direct_location_input(text):
    return parse_coordinates(text) is not None or bool(
        re.fullmatch(r"\d{5,6}", text)
    )


def estimate_travel_limits(updates):
    """Complete only this update's missing counterpart, never an old value."""
    updates = dict(updates)
    distance = updates.get("max_distance_km")
    minutes = updates.get("max_travel_time_minutes")
    if distance is not None and minutes is None:
        updates["max_travel_time_minutes"] = round(
            distance * MINUTES_PER_KM, 2)
    elif minutes is not None and distance is None:
        updates["max_distance_km"] = max(
            0.01, round(minutes / MINUTES_PER_KM, 2))
    return updates


def apply_updates(preferences, updates, location_action="add"):
    """Build a new profile; reject conflicts without mutating the old one."""
    if location_action not in {"add", "replace", "remove"}:
        raise ValueError("Choose add, replace, or remove for locations.")
    result = deepcopy(validate_preferences(preferences))
    updates = estimate_travel_limits(validate_updates(updates))
    if "location" in updates:
        old = result["location"] or []
        incoming = updates["location"]
        if location_action == "add":
            updates["location"] = list(dict.fromkeys(old + incoming))
        elif location_action == "remove":
            if any(item not in old for item in incoming):
                raise ValueError("That location is not in your saved list.")
            updates["location"] = [
                item for item in old if item not in incoming]
    result.update(updates)
    return validate_preferences(result)


def cuisine_conflicts(preferences, updates):
    proposed = dict(preferences)
    proposed.update(updates)
    return sorted(set(proposed.get("liked_cuisines") or []) & set(
        proposed.get("disliked_cuisines") or []
    ))


def cuisine_tokens(text, field):
    """Recognize simple cuisine lists without dropping unknown text."""
    text = text.strip().lower().rstrip(".!?")
    if text in {"none", "no preference", "no preferences"}:
        return []
    negative = re.match(
        r"(?:i\s+)?(?:don't like|do not like|dislike|avoid|hate)\b", text)
    positive = re.match(r"(?:i\s+)?(?:like|love|enjoy|prefer)\b", text)
    if negative and field == "liked_cuisines":
        raise ValueError("That describes dislikes. Enter cuisines you like.")
    if positive and field == "disliked_cuisines":
        raise ValueError("That describes likes. Enter cuisines you avoid.")
    text = re.sub(
        r"^(?:i\s+)?(?:don't like|do not like|dislike|avoid|hate|like|love|"
        r"enjoy|prefer)(?:\s+eating)?\s+", "", text,
    )
    parts = re.split(r"\s*(?:,|\band\b|&)\s*", text)
    tokens = []
    names = sorted(CUISINES + tuple(UNSUPPORTED_CUISINES),
                   key=len, reverse=True)
    name_pattern = re.compile("|".join(re.escape(name) for name in names))
    for part in parts:
        part = re.sub(r"\s+(?:food|cuisines?|dishes)$", "", part).strip()
        if not part or not re.fullmatch(r"[a-z]+(?:[ -][a-z]+)*", part):
            raise ValueError(
                "Describe cuisines you like or avoid, or enter none.")
        if part in names:
            found = [part]
        else:
            found = []
            remaining = part
            while remaining:
                match = name_pattern.match(remaining)
                if not match:
                    found = [part]
                    break
                found.append(match.group())
                remaining = remaining[match.end():]
                if remaining and not remaining.startswith(" "):
                    found = [part]
                    break
                remaining = remaining.strip()
        for token in found:
            if token not in tokens:
                tokens.append(token)
    return tokens


def cuisine_suggestions(token):
    """Suggest close matches; never correct automatically."""
    if len(token) < 4:
        return []
    ranked = sorted(
        ((SequenceMatcher(None, token, name).ratio(), name)
         for name in CUISINES),
        reverse=True,
    )
    best = ranked[0][0]
    if best < 0.78:
        return []
    return [name for score, name in ranked if score >= max(0.78, best - 0.08)]


def needs_cuisine_interpretation(text, field):
    """Use AI for complex phrasing; keep typo confirmations local."""
    tokens = cuisine_tokens(text, field)
    unresolved = any(
        token not in CUISINES and token not in UNSUPPORTED_CUISINES
        and not cuisine_suggestions(token) for token in tokens
    )
    known_mention = any(
        re.search(r"\b" + re.escape(name) + r"\b", text.lower())
        for name in CUISINES
    )
    return unresolved and known_mention and len(text.split()) >= 4


def parse_local_answer(text, field):
    """Produce a typed update; cuisine confirmations are handled by IO."""
    from sources.profile_schema import clean_text

    text = clean_text(text, 1000)
    if field in {"max_distance_km", "max_travel_time_minutes"}:
        match = re.fullmatch(
            r"(\d+(?:\.\d{1,2})?)\s*(km|mins?|minutes?)?", text.lower(),
        )
        if not match or (field == "max_distance_km" and match[2] is None):
            raise ValueError(
                "Enter a number with units, e.g. 1 km or 20 mins.")
        target = "max_distance_km" if match[2] == "km" else (
            "max_travel_time_minutes"
        )
        return estimate_travel_limits(
            validate_updates({target: float(match[1])}))
    if field == "budget_per_person":
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
            raise ValueError("Enter SGD as a number, e.g. 5 or 5.50.")
        return validate_updates({field: float(text)})
    if field == "location":
        return validate_updates({field: text.split(",")})
    if field == "dietary_requirements":
        lowered = text.lower()
        if lowered in {"none", "no restrictions", "no dietary requirements"}:
            items = []
        elif lowered == "both":
            items = ["halal", "vegetarian"]
        else:
            items = re.split(r"\s*(?:,|\band\b|&)\s*", lowered)
        return validate_updates({field: items})
    if field in CUISINE_FIELDS:
        return validate_updates({field: cuisine_tokens(text, field)})
    if field == OTHER_PREFERENCES:
        items = [] if text.lower() in {
            "none", "no preference", "no preferences",
        } else text.split(",")
        return validate_updates({field: items})
    raise ValueError("Choose a valid preference field.")


def next_field(preferences):
    for field in PREFERENCE_FIELDS:
        if preferences[field] is None:
            return field
    return None


def evaluate(record):
    """Apply profile business rules to one AI-enriched update record."""
    if not isinstance(record, dict) or not isinstance(
            record.get("preferences"), dict):
        raise ValueError("Logic evaluation needs preferences and AI updates.")
    updated = apply_updates(
        record["preferences"], record.get("updates", {}),
        record.get("location_action", "add"))
    return {"preferences": updated, "next_field": next_field(updated)}


def score(record):
    """Return a numeric profile-completeness score."""
    preferences = record.get("preferences") if isinstance(record, dict) else None
    preferences = validate_preferences(preferences)
    return sum(preferences[field] is not None for field in PREFERENCE_FIELDS)


def route(record):
    """Route an evaluated profile to completion or its next required field."""
    field = record.get("next_field") if isinstance(record, dict) else None
    return "profile_complete" if field is None else field
