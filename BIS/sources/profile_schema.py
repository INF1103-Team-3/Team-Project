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
MINUTES_PER_KM = 20
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
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


def normalize_list(value, choices=None, required=False):
    """Require lists and keep all entries or reject the entire answer."""
    if not isinstance(value, list):
        raise ValueError("Expected a list of text entries.")
    result = []
    for item in value:
        item = clean_text(item, 100).lower()
        if not any(c.isalpha() for c in item):
            raise ValueError("List entries must contain letters.")
        if choices is not None and item not in choices:
            raise ValueError("Choose from: " + ", ".join(choices) + ".")
        if item not in result:
            result.append(item)
    if required and not result:
        raise ValueError("Enter at least one location.")
    return result


def validate_value(field, value):
    """Validate the exact agreed field type, returning normalized values."""
    if field not in PREFERENCE_FIELDS:
        raise ValueError(f"Unsupported preference field: {field}.")
    if value is None:
        return None
    if field in NUMBER_LIMITS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be a number.")
        minimum, maximum = NUMBER_LIMITS[field]
        if not minimum <= value <= maximum or not math.isfinite(value):
            raise ValueError(
                f"{field} must be between {minimum} and {maximum}.")
        return round(value, 2)
    if field == "location":
        return normalize_list(value, required=True)
    if field == "dietary_requirements":
        return normalize_list(value, DIETARY_CHOICES)
    if field == OTHER_PREFERENCES:
        return normalize_list(value)
    if field in CUISINE_FIELDS:
        return normalize_list(value, CUISINES)
    return clean_text(value, 1000, allow_empty=True)


def validate_updates(updates):
    """Reject obsolete keys even if null; null updates never erase answers."""
    if not isinstance(updates, dict):
        raise ValueError("Preference updates must be a dictionary.")
    normalized = {}
    for field, value in updates.items():
        value = validate_value(field, value)
        if value is not None:
            normalized[field] = value
    return normalized


def validate_preferences(preferences):
    """Validate a full persisted preference record without adding fields."""
    if not isinstance(preferences, dict) or set(preferences) != set(
        PREFERENCE_FIELDS
    ):
        raise ValueError("Saved profile does not match the current BIS schema.")
    result = {key: validate_value(key, value)
              for key, value in preferences.items()}
    overlap = set(result["liked_cuisines"] or []) & set(
        result["disliked_cuisines"] or []
    )
    if overlap:
        raise ValueError("Resolve cuisines listed as both liked and disliked.")
    return result


def validate_user(user):
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
        "preferences": validate_preferences(user["preferences"]),
    }


# Recognition-only unsupported cuisine names.
UNSUPPORTED_CUISINES = {
    "spanish", "greek", "brazilian", "ethiopian", "german",
    "british", "pakistani", "bangladeshi", "nepalese", "sri lankan",
    "cambodian", "laotian", "burmese", "taiwanese", "singaporean",
}
