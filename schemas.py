"""Small procedural validators shared by the AI and domain boundaries."""

import math
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LIST_FIELDS = ("dietary_requirements", "allergies", "cuisines", "foods")
REQUEST_FIELDS = set(LIST_FIELDS) | {
    "budget_max", "walking_time_max", "location", "open_now",
    "requested_time", "restaurant_name", "unsupported_requirements",
}


def is_number(value, minimum=0):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and value >= minimum
    except OverflowError:
        return False


def is_text(value):
    return (isinstance(value, str) and 0 < len(value.strip()) <= 200
            and all(char.isprintable() for char in value))


def is_text_list(value):
    return (isinstance(value, list) and len(value) <= 30
            and all(is_text(item) for item in value))


def valid_coordinates(value):
    return (isinstance(value, list) and len(value) == 2
            and is_number(value[0], -90) and value[0] <= 90
            and is_number(value[1], -180) and value[1] <= 180)


def empty_request():
    return {
        "dietary_requirements": [], "allergies": [], "cuisines": [],
        "foods": [], "budget_max": None, "walking_time_max": None,
        "location": None, "open_now": False, "requested_time": None,
        "restaurant_name": "", "unsupported_requirements": [],
    }


def validate_request(request):
    """Require every field; never silently discard unknown AI constraints."""
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        return "Request fields are missing or unsupported."
    for field in LIST_FIELDS + ("unsupported_requirements",):
        if not is_text_list(request[field]):
            return "Preference fields must be lists of short non-empty text."
    for field in ("budget_max", "walking_time_max"):
        if request[field] is not None and not is_number(request[field]):
            return "Budget and walking limits must be finite positive numbers or zero."
    if request["location"] is not None and not valid_coordinates(request["location"]):
        return "Location must be [latitude, longitude] within valid ranges."
    if type(request["open_now"]) is not bool:
        return "Open-now must be true or false."
    if not isinstance(request["restaurant_name"], str):
        return "Restaurant name must be text."
    if len(request["restaurant_name"]) > 200:
        return "Restaurant name is too long."
    requested_time = request["requested_time"]
    if requested_time is not None:
        try:
            value = datetime.fromisoformat(requested_time)
            if value.utcoffset() is None:
                raise ValueError
        except (ValueError, TypeError):
            return "Requested time needs an ISO date, time and UTC offset."
    return None


def normalize_request(request):
    result = dict(request)
    for field in LIST_FIELDS:
        result[field] = sorted({item.strip().casefold() for item in request[field]})
    result["restaurant_name"] = request["restaurant_name"].strip()
    return result


def valid_evidence(value):
    return (isinstance(value, dict) and type(value.get("confirmed")) is bool
            and value.get("evidence_type") in {"official", "restaurant_reported"}
            and is_text_list(value.get("source_ids")) and bool(value["source_ids"]))


def validate_restaurant(record, source_ids):
    """Reject malformed records before filtering, including unsupported claims."""
    if not isinstance(record, dict):
        return False
    if not all(is_text(record.get(key)) for key in ("restaurant_id", "name", "address")):
        return False
    if not is_text_list(record.get("cuisines")):
        return False
    sources = record.get("source_ids")
    if not is_text_list(sources) or not sources or not set(sources) <= source_ids:
        return False
    location = record.get("location")
    if location is not None and not valid_coordinates(location):
        return False
    if not valid_opening_hours(record.get("opening_hours"), source_ids):
        return False
    if not isinstance(record.get("menu"), list):
        return False
    for item in record["menu"]:
        if not isinstance(item, dict) or not is_text(item.get("name")):
            return False
        if not is_text_list(item.get("food_tags", [])):
            return False
        if item.get("price") is not None and not is_number(item["price"]):
            return False
        if item.get("currency") != "SGD":
            return False
        if not is_text_list(item.get("source_ids")) or not item["source_ids"]:
            return False
        if not set(item["source_ids"]) <= source_ids:
            return False
        for field in ("dietary", "allergen_free"):
            claims = item.get(field, {})
            if not isinstance(claims, dict):
                return False
            for name, claim in claims.items():
                if not is_text(name) or not valid_evidence(claim):
                    return False
                if not set(claim["source_ids"]) <= source_ids:
                    return False
    return True


def valid_opening_hours(hours, source_ids):
    if hours is None:
        return True
    if not isinstance(hours, dict):
        return False
    if not is_text_list(hours.get("source_ids")) or not hours["source_ids"]:
        return False
    if not set(hours["source_ids"]) <= source_ids:
        return False
    try:
        ZoneInfo(hours["timezone"])
        weekly, exceptions = hours["weekly"], hours.get("exceptions", {})
        if not isinstance(weekly, dict) or not isinstance(exceptions, dict):
            return False
        if not set(weekly) <= set("0123456"):
            return False
        for date in exceptions:
            datetime.strptime(date, "%Y-%m-%d")
        for intervals in list(weekly.values()) + list(exceptions.values()):
            if not isinstance(intervals, list):
                return False
            for interval in intervals:
                if not isinstance(interval, list) or len(interval) != 2:
                    return False
                for value in interval:
                    datetime.strptime(value, "%H:%M")
        return True
    except (KeyError, ValueError, TypeError, ZoneInfoNotFoundError):
        return False


def valid_profile(profile):
    if not isinstance(profile, dict):
        return False
    for field in ("allergies", "dietary_requirements",
                  "preferred_cuisines", "preferred_foods"):
        if not is_text_list(profile.get(field, [])):
            return False
    selected = profile.get("selected_ids", [])
    if not isinstance(selected, list) or not all(is_text(item) for item in selected):
        return False
    counts = profile.get("cuisine_counts", {})
    return (isinstance(counts, dict) and all(is_text(key) and type(value) is int
            and 0 <= value <= 10 for key, value in counts.items()))
