from __future__ import annotations

import logging
import math
from urllib.parse import urlencode

import requests

from models import SearchRequest

log = logging.getLogger(__name__)

CANDIDATES = 20  # most results Google returns per search
WALK_METERS_PER_MIN = 80.0
TIMEOUT = 20

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTES_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"

PLACES_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.priceRange",
        "places.rating",
        "places.userRatingCount",
        "places.regularOpeningHours",
        "places.primaryTypeDisplayName",
    ]
)


class PlacesError(Exception):
    """Raised when Google Maps data could not be fetched."""


def _check(resp: requests.Response, name: str):
    """Return parsed JSON, or raise PlacesError with a readable message."""
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok:
        message = ""
        if isinstance(data, dict):
            message = data.get("error", {}).get("message", "")
        raise PlacesError(f"{name} error {resp.status_code}: {message or resp.text[:200]}")
    return data


def geocode(location: str, api_key: str) -> tuple[float, float, str]:
    resp = requests.get(
        GEOCODE_URL,
        params={"address": location, "key": api_key},
        timeout=TIMEOUT,
    )
    data = _check(resp, "Geocoding")
    status = data.get("status")
    if status == "ZERO_RESULTS":
        raise PlacesError(f"Could not find a place called '{location}'.")
    if status != "OK":
        detail = data.get("error_message", "")
        raise PlacesError(f"Geocoding failed ({status}). {detail}".strip())
    top = data["results"][0]
    loc = top["geometry"]["location"]
    return loc["lat"], loc["lng"], top.get("formatted_address", location)


def search_places(query: str, lat: float, lng: float, radius_m: float, api_key: str) -> list[dict]:
    body = {
        "textQuery": query,
        "includedType": "restaurant",
        "maxResultCount": CANDIDATES,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
    }
    resp = requests.post(
        PLACES_URL,
        json=body,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": PLACES_FIELDS},
        timeout=TIMEOUT,
    )
    return _check(resp, "Places").get("places", [])


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walking_minutes(lat: float, lng: float, places: list[dict], api_key: str) -> list[int]:
    """Walking minutes to each place. Falls back to a straight-line estimate."""
    fallback = [
        max(
            1,
            math.ceil(
                _haversine_m(lat, lng, p["location"]["latitude"], p["location"]["longitude"])
                / WALK_METERS_PER_MIN
            ),
        )
        for p in places
    ]
    try:
        body = {
            "origins": [
                {"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lng}}}}
            ],
            "destinations": [
                {
                    "waypoint": {
                        "location": {
                            "latLng": {
                                "latitude": p["location"]["latitude"],
                                "longitude": p["location"]["longitude"],
                            }
                        }
                    }
                }
                for p in places
            ],
            "travelMode": "WALK",
        }
        resp = requests.post(
            ROUTES_URL,
            json=body,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "originIndex,destinationIndex,duration,condition",
            },
            timeout=TIMEOUT,
        )
        elements = _check(resp, "Routes")
        result = list(fallback)
        for el in elements:
            duration = el.get("duration")
            if duration:
                seconds = float(duration.rstrip("s"))
                result[el["destinationIndex"]] = max(1, math.ceil(seconds / 60))
        return result
    except Exception as exc:
        log.warning("Walking routes unavailable, using straight-line estimate: %s", exc)
        return fallback


_GOOGLE_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]  # Google numbers Sunday as 0
_WEEK_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _weekly_hours(place: dict) -> dict | None:
    """
    Opening hours for the whole week, e.g.
    {"mon": "0900 - 2100", "tue": "0900 - 2100", ..., "sun": "closed"}.
    Returns None when Google has no opening hours for the place.
    """
    periods = (place.get("regularOpeningHours") or {}).get("periods")
    if not periods:
        return None

    # Google marks a place that is always open as one period with no closing time.
    if len(periods) == 1 and not periods[0].get("close"):
        return {day: "open 24 hours" for day in _WEEK_ORDER}

    spans: dict[str, list[str]] = {day: [] for day in _WEEK_ORDER}
    for p in periods:
        opening = p.get("open") or {}
        day = opening.get("day")
        if not isinstance(day, int) or not 0 <= day <= 6:
            continue
        closing = p.get("close")
        start = f"{opening.get('hour', 0):02d}{opening.get('minute', 0):02d}"
        end = (
            f"{closing.get('hour', 0):02d}{closing.get('minute', 0):02d}"
            if closing
            else "2400"
        )
        spans[_GOOGLE_DAYS[day]].append(f"{start} - {end}")

    return {day: ", ".join(sorted(spans[day])) or "closed" for day in _WEEK_ORDER}


def _price_from_range(place: dict):
    price_range = place.get("priceRange")
    if not price_range:
        return None

    def amount(key):
        money = price_range.get(key)
        if not money:
            return None
        return float(money.get("units", 0)) + money.get("nanos", 0) / 1e9

    values = [v for v in (amount("startPrice"), amount("endPrice")) if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def directions_url(origin: str, lat: float, lng: float, place_id: str | None) -> str:
    """Google Maps link that opens walking directions from origin to the restaurant."""
    params = {
        "api": 1,
        "origin": origin,
        "destination": f"{lat},{lng}",
        "travelmode": "walking",
    }
    if place_id:
        params["destination_place_id"] = place_id
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def fetch_candidates(request: SearchRequest, api_key: str) -> tuple[str, list[dict]]:
    """
    Return (resolved_location, raw_records) for the request.

    Raw records hold only what Google knows. Filtering and decisions happen later,
    in the Logic Manager, after every record has passed through the AI Manager.
    """
    try:
        lat, lng, resolved = geocode(request.location, api_key)
        prefix = {"halal": "halal ", "vegetarian": "vegetarian "}.get(request.food_type, "")
        query = f"{prefix}restaurants near {resolved}"
        radius_m = min(50000.0, max(500.0, request.max_walk_min * WALK_METERS_PER_MIN))
        places = search_places(query, lat, lng, radius_m, api_key)
        places = [
            p
            for p in places
            if p.get("location") and (p.get("displayName") or {}).get("text")
        ]
        minutes = walking_minutes(lat, lng, places, api_key) if places else []
    except requests.RequestException as exc:
        log.exception("Network problem talking to Google Maps")
        raise PlacesError(f"Could not reach Google Maps: {exc}") from exc

    records = []
    for place, walk in zip(places, minutes):
        records.append(
            {
                "place_id": place.get("id"),
                "name": place["displayName"]["text"],
                "address": place.get("formattedAddress", ""),
                "latitude": place["location"]["latitude"],
                "longitude": place["location"]["longitude"],
                "search_location": resolved,
                "primary_type": (place.get("primaryTypeDisplayName") or {}).get("text", ""),
                "rating": place.get("rating"),
                "rating_count": place.get("userRatingCount"),
                "price_google": _price_from_range(place),
                "open_hours": _weekly_hours(place),
                "walk_minutes": walk,
                "directions_url": directions_url(
                    resolved,
                    place["location"]["latitude"],
                    place["location"]["longitude"],
                    place.get("id"),
                ),
            }
        )
    return resolved, records
