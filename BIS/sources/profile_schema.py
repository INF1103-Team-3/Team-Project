"""Shared account and preference contract; no IO or persistence."""

import math
import re

OTHER_PREFERENCES = "other_preferences"
PREFERENCE_FIELDS = (
    "location", "max_distance_km", "max_travel_time_minutes",
    "budget_per_person", "dietary_requirements", "liked_cuisines",
    "disliked_cuisines", OTHER_PREFERENCES,
)
USER_FIELDS = {"userID", "email", "email_verified", "username", "preferences"}
CUISINES = (
    "chinese", "malay", "indian", "peranakan", "indonesian", "thai",
    "vietnamese", "filipino", "japanese", "korean", "western", "italian",
    "french", "american", "mexican", "turkish", "middle eastern",
    "mediterranean", "fusion", "lebanese",
)
DIETARY_CHOICES = ("halal", "vegetarian")
CUISINE_FIELDS = ("liked_cuisines", "disliked_cuisines")
NUMBER_LIMITS = {
    "max_distance_km": (0.01, 100),
    "max_travel_time_minutes": (0.1, 2000),
    "budget_per_person": (0.01, 1000),
}
PROFILE_NUMBER_LIMITS = {
    "max_distance_km": (0.01, 50.0),
    "max_travel_time_minutes": (1.0, 150.0),
    "budget_per_person": (0.01, 1000.0),
}
SEARCH_MODE_LIMITS = {
    "walk": {"max_distance_km": (0.01, 15.0), "max_travel_minutes": (1.0, 90.0)},
    "drive": {"max_distance_km": (0.01, 50.0), "max_travel_minutes": (1.0, 120.0)},
    "transit": {"max_distance_km": (0.01, 50.0), "max_travel_minutes": (1.0, 150.0)},
}
MINUTES_PER_KM = 20
TRANSIT_MINUTES_RANGE = (1, 150)
_COORDINATE_TEXT = re.compile(r"^\s*[+-]?\d+(?:\.\d+)?\s*,\s*[+-]?\d+(?:\.\d+)?\s*$")
_WISH_ALLOWED_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ,.'!?/&()+\-]*")
_WISH_ACRONYMS = {
    "bbq", "byob", "msg", "cbd", "mrt", "hrs", "gym", "nth", "sgd", "ac", "tv", "vip", "wfh",
}
_WISH_KEYBOARD_MASH = (
    "asdf", "sdfg", "dfgh", "fghj", "ghjk", "hjkl",
    "qwer", "wert", "erty", "tyui", "uiop",
    "zxcv", "xcvb", "cvbn", "vbnm",
)
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


def empty_preferences():
    """Null means unanswered; an empty list means explicitly none."""
    return dict.fromkeys(PREFERENCE_FIELDS)


def clean_text(value, maximum=200, allow_empty=False):
    """Validate strings without guessing, coercing, or truncating."""
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError("Enter text without control characters.")
    value = value.strip()
    if not value and allow_empty:
        return ""
    if not value or len(value) > maximum or not any(c.isalnum()
                                                    for c in value):
        raise ValueError(f"Enter 1–{maximum} characters of meaningful text.")
    return value


def normalize_username(value):
    """The account display name is separate from preferences."""
    return clean_text(value, 50)


def normalize_email(value):
    """Normalize email for unique lookup and validate practical syntax."""
    if not isinstance(value, str):
        raise ValueError("Enter a valid email address.")
    value = value.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    local = value.split("@", 1)[0]
    if len(local) > 64 or local.startswith(".") or local.endswith("."):
        raise ValueError("Enter a valid email address.")
    if ".." in local:
        raise ValueError("Enter a valid email address.")
    return value


def normalize_list(value, choices=None, required=False, allow_coordinates=False):
    """Require lists and keep all entries or reject the entire answer."""
    if not isinstance(value, list):
        raise ValueError("Expected a list of text entries.")
    result = []
    for item in value:
        item = clean_text(item, 100).lower()
        if not any(c.isalpha() for c in item) and not (
            allow_coordinates and _COORDINATE_TEXT.fullmatch(item)
        ):
            raise ValueError("List entries must contain letters.")
        if choices is not None and item not in choices:
            raise ValueError("Choose from: " + ", ".join(choices) + ".")
        if item not in result:
            result.append(item)
    if required and not result:
        raise ValueError("Enter at least one location.")
    return result


def validate_english_preferences(items, field_label="Special requests"):
    """Require proper meaningful English text for special wishes or requests."""
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 100 or not _WISH_ALLOWED_TEXT.fullmatch(text):
            raise ValueError(
                f"{field_label} must use proper English letters and words "
                "(e.g. quiet seating, spicy food)."
            )
        words = re.findall(r"[A-Za-z]+", text)
        if not words or not any(len(word) > 1 for word in words):
            raise ValueError(
                f"{field_label} must contain meaningful English words "
                "(e.g. quiet seating, spicy food)."
            )
        for word in words:
            low = word.lower()
            if (
                re.search(r"(.)\1\1", low)
                or any(seq in low for seq in _WISH_KEYBOARD_MASH)
                or (len(low) >= 3 and low not in _WISH_ACRONYMS and not any(ch in "aeiouy" for ch in low))
                or re.search(r"[bcdfghjklmnpqrstvwxz]{6,}", low)
            ):
                raise ValueError(
                    f"{field_label} must contain proper English words, "
                    f"not '{word}'."
                )
    return items


def validate_value(field, value, profile_mode=False, allow_empty_location=False,
                   clamp_legacy_limits=False):
    """Validate the exact agreed field type, returning normalized values."""
    if field not in PREFERENCE_FIELDS:
        raise ValueError(f"Unsupported preference field: {field}.")
    if value is None:
        return None
    if field in NUMBER_LIMITS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be a number.")
        if not math.isfinite(value):
            raise ValueError(f"{field} must be a finite number.")
        if profile_mode:
            minimum, maximum = PROFILE_NUMBER_LIMITS[field]
            if clamp_legacy_limits:
                legacy_min = NUMBER_LIMITS[field][0]
                if value < legacy_min:
                    raise ValueError(
                        f"{field} must be between {minimum:g} and {maximum:g}.")
                return round(max(minimum, min(maximum, float(value))), 2)
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{field} must be between {minimum:g} and {maximum:g}.")
            return round(float(value), 2)
        minimum, maximum = NUMBER_LIMITS[field]
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{field} must be between {minimum} and {maximum}.")
        return round(value, 2)
    if field == "location":
        return normalize_list(
            value, required=not allow_empty_location, allow_coordinates=True)
    if field == "dietary_requirements":
        return normalize_list(value, DIETARY_CHOICES)
    if field == OTHER_PREFERENCES:
        return normalize_list(value)
    if field in CUISINE_FIELDS:
        return normalize_list(value, CUISINES)
    return clean_text(value, 1000, allow_empty=True)


def validate_search_distance(value, mode=None):
    """Validate a search-only maximum distance in kilometres for a mode."""
    limits = SEARCH_MODE_LIMITS.get(mode) if mode else None
    low, high = limits["max_distance_km"] if limits else (0.01, 50.0)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f"max_distance_km must be between {low:g} and {high:g}.")
    return round(float(value), 2)


def validate_travel_minutes(value, mode=None):
    """Validate a search-only maximum journey time in minutes."""
    limits = SEARCH_MODE_LIMITS.get(mode) if mode else None
    low, high = limits["max_travel_minutes"] if limits else TRANSIT_MINUTES_RANGE
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high):
        raise ValueError(f"Travel time must be between {low:g} and {high:g} minutes.")
    return round(value, 2)


def validate_updates(updates, profile_mode=False, allow_empty_location=False):
    """Reject obsolete keys even if null; null updates never erase answers."""
    if not isinstance(updates, dict):
        raise ValueError("Preference updates must be a dictionary.")
    normalized = {}
    for field, value in updates.items():
        value = validate_value(
            field, value, profile_mode=profile_mode,
            allow_empty_location=allow_empty_location,
        )
        if value is not None:
            normalized[field] = value
    return normalized


def validate_preferences(preferences, clamp_legacy_limits=False):
    """Validate a full persisted preference record without adding fields."""
    if not isinstance(preferences, dict) or set(preferences) != set(
        PREFERENCE_FIELDS
    ):
        raise ValueError("Saved profile does not match the current BIS schema.")
    result = {
        key: validate_value(
            key, value, profile_mode=True, allow_empty_location=True,
            clamp_legacy_limits=clamp_legacy_limits,
        )
        for key, value in preferences.items()
    }
    overlap = set(result["liked_cuisines"] or []) & set(
        result["disliked_cuisines"] or []
    )
    if overlap:
        raise ValueError("Resolve cuisines listed as both liked and disliked.")
    return result


def validate_user(user, clamp_legacy_limits=False):
    """Require the exact account and preference schema."""
    if not isinstance(user, dict) or set(user) != USER_FIELDS:
        raise ValueError("Saved account does not match the current BIS schema.")
    if not isinstance(user["userID"], str) or not user["userID"]:
        raise ValueError("Invalid userID.")
    if type(user["email_verified"]) is not bool:
        raise ValueError("email_verified must be a boolean.")
    return {
        "userID": user["userID"],
        "email": normalize_email(user["email"]),
        "email_verified": user["email_verified"],
        "username": (normalize_username(user["username"])
                     if user["username"] is not None else None),
        "preferences": validate_preferences(
            user["preferences"], clamp_legacy_limits=clamp_legacy_limits
        ),
    }


# Recognition-only unsupported cuisine names.
UNSUPPORTED_CUISINES = {
    "spanish", "greek", "brazilian", "ethiopian", "german",
    "british", "pakistani", "bangladeshi", "nepalese", "sri lankan",
    "cambodian", "laotian", "burmese", "taiwanese", "singaporean",
}
