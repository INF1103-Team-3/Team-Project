"""Procedural profile and search decisions and conversions."""

import re
from difflib import SequenceMatcher

from sources.profile_schema import (
    CUISINES, CUISINE_FIELDS, MINUTES_PER_KM, OTHER_PREFERENCES,
    UNSUPPORTED_CUISINES,
    PREFERENCE_FIELDS, clean_text, validate_preferences, validate_updates,
    validate_value, validate_travel_minutes,
)
from BIS.classes.logic_manager import LogicManager

COORDINATES = re.compile(
    r"\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*"
)

SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "max_travel_minutes", "traffic_aware", "cuisine",
    "budget_per_person", OTHER_PREFERENCES,
    "dietary_requirements", "disliked_cuisines",
}


SEARCH_CLARIFICATION_PREFIX = "SEARCH_CLARIFICATION: "

_MANAGER = LogicManager()


def manager():
    """Return the configured BIS Logic Manager."""
    return _MANAGER


def search_clarification_error(message):
    """Return a procedural clarification error for the interactive loop."""
    return ValueError(SEARCH_CLARIFICATION_PREFIX + message)


def is_search_clarification(error):
    """Identify clarification errors without defining an exception class."""
    return _MANAGER.is_search_clarification(error)


def clarification_message(error):
    """Remove the internal marker before displaying an error."""
    return _MANAGER.clarification_message(error)


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
    return _MANAGER.validate_search_request(request, ai_response)


def in_singapore(latitude, longitude):
    """Reject locations outside the app's supported search area."""
    return _MANAGER.in_singapore(latitude, longitude)


def parse_coordinates(text):
    return _MANAGER.parse_coordinates(text)


def is_direct_location_input(text):
    return _MANAGER.is_direct_location_input(text)


def estimate_travel_limits(updates):
    """Complete only this update's missing counterpart, never an old value."""
    return _MANAGER.estimate_travel_limits(updates)


def apply_updates(preferences, updates, location_action="add"):
    """Build a new profile; reject conflicts without mutating the old one."""
    return _MANAGER.apply_updates(preferences, updates, location_action)


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
    return _MANAGER.next_field(preferences)


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


def apply_search_constraints(text, constraints):
    return _MANAGER.apply_search_constraints(text, constraints)
