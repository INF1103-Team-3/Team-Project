"""Bounded Google Places API (New) discovery; place content stays in memory."""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from debug import debug_log
from schemas import is_number, valid_coordinates, valid_google_place_id

BASE_URL = "https://places.googleapis.com/v1/places"
SEARCH_FIELDS = (
    "id", "displayName", "formattedAddress", "location", "googleMapsUri",
    "primaryType", "businessStatus", "attributions",
)
DETAIL_FIELDS = SEARCH_FIELDS + (
    "websiteUri", "regularOpeningHours.weekdayDescriptions",
    "currentOpeningHours.openNow", "priceLevel",
)
MAX_RESPONSE_BYTES = 1_000_000


def request_google_json(url, config, fields, body=None):
    """One HTTP call, no automatic retries; credentials never enter URLs/logs."""
    key = config.get("google_maps_key")
    if not key:
        return None, "Set GOOGLE_MAPS_API_KEY with Places API (New) enabled."
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": ",".join(fields)}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, allow_nan=False).encode()
    request = Request(url, data=data, headers=headers,
                      method="POST" if body is not None else "GET")
    debug_log("places_started")
    try:
        with urlopen(request, timeout=config.get("timeout", 20)) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        if "error" in payload:
            debug_log("places_failed", "error")
            return None, "Google Places returned an error; check API access and quotas."
        debug_log("places_received")
        return payload, None
    except HTTPError as error:
        debug_log("places_failed", "error", error.code)
        if error.code == 429:
            return None, "Google Places quota exceeded. No automatic retry was made."
        if error.code in (401, 403):
            return None, "Google Places access denied. Check key restrictions, API enablement and billing."
        return None, f"Google Places request failed (HTTP {error.code})."
    except (OSError, URLError, HTTPException, ValueError, TypeError, RecursionError):
        debug_log("places_failed", "error")
        return None, "Google Places is unavailable or returned an invalid response."


def display_text(value, maximum=500):
    if (isinstance(value, str) and 0 < len(value) <= maximum
            and value.isprintable()):
        return value
    return None


def public_link(value):
    if not display_text(value, 2000):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in ("http", "https") and parsed.hostname
                and not parsed.username and not parsed.password):
            return value
    except ValueError:
        pass
    return None


def parse_google_place(raw):
    """Validate useful fields without inventing menu or safety evidence."""
    if not isinstance(raw, dict) or not valid_google_place_id(raw.get("id")):
        return None
    name = raw.get("displayName")
    location = raw.get("location")
    coordinates = None
    if isinstance(location, dict):
        candidate = [location.get("latitude"), location.get("longitude")]
        if valid_coordinates(candidate):
            coordinates = candidate
    result = {
        "place_id": raw["id"],
        "name": display_text(name.get("text")) if isinstance(name, dict) else None,
        "address": display_text(raw.get("formattedAddress")),
        "location": coordinates,
        "maps_url": public_link(raw.get("googleMapsUri")),
        "website": public_link(raw.get("websiteUri")),
        "type": display_text(raw.get("primaryType")),
        "business_status": display_text(raw.get("businessStatus")),
        "price_level": display_text(raw.get("priceLevel")),
        "attributions": [], "opening_hours": [], "open_now": None,
    }
    attributions = raw.get("attributions", [])
    if not isinstance(attributions, list):
        return None
    for attribution in attributions:
        if not isinstance(attribution, dict):
            return None
        provider = display_text(attribution.get("provider"))
        if not provider:
            return None
        result["attributions"].append({"provider": provider,
                                       "url": public_link(attribution.get("providerUri"))})
    hours = raw.get("regularOpeningHours")
    if isinstance(hours, dict):
        descriptions = hours.get("weekdayDescriptions")
        if (isinstance(descriptions, list) and len(descriptions) <= 7
                and all(display_text(value) for value in descriptions)):
            result["opening_hours"] = descriptions
    current = raw.get("currentOpeningHours")
    if isinstance(current, dict) and type(current.get("openNow")) is bool:
        result["open_now"] = current["openNow"]
    return result


def search_nearby_restaurants(origin, radius_m, limit, config):
    if not valid_coordinates(origin):
        return [], "Enter valid latitude and longitude."
    if not is_number(radius_m, 1) or radius_m > 50000:
        return [], "Radius must be between 1 and 50000 metres."
    if type(limit) is not int or not 1 <= limit <= 20:
        return [], "Result limit must be an integer between 1 and 20."
    body = {
        "includedTypes": ["restaurant"], "maxResultCount": limit,
        "rankPreference": "DISTANCE", "languageCode": "en",
        "locationRestriction": {"circle": {
            "center": {"latitude": origin[0], "longitude": origin[1]},
            "radius": radius_m,
        }},
    }
    payload, error = request_google_json(
        BASE_URL + ":searchNearby", config,
        ["places." + field for field in SEARCH_FIELDS], body)
    if error:
        return [], error
    records = payload.get("places", [])
    if not isinstance(records, list) or len(records) > limit:
        return [], "Google Places returned an invalid result list."
    places, seen = [], set()
    for record in records:
        place = parse_google_place(record)
        if place is None:
            return [], "Google Places returned a malformed place or attribution."
        if place["place_id"] not in seen:
            places.append(place)
            seen.add(place["place_id"])
    return places, None


def get_place_details(place_id, config):
    if not valid_google_place_id(place_id):
        return None, "Invalid Google place ID."
    payload, error = request_google_json(
        BASE_URL + "/" + quote(place_id, safe=""), config, DETAIL_FIELDS)
    if error:
        return None, error
    place = parse_google_place(payload)
    if place is None or place["place_id"] != place_id:
        return None, "Google Places returned invalid or mismatched details."
    return place, None
