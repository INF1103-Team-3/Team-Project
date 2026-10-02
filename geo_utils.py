"""
geo_utils.py
============
Small, dependency-free geo helpers used by logic_manager to compute
walking time between the user's query-time location and each
restaurant's coordinates. Pulled out of logic_manager to keep that
module focused on business rules, not math/network plumbing.

Not one of the four required managers -- it's a shared utility, the way
a "helpers" module would be in any procedural codebase. No classes.
"""

import json
import math
import urllib.request
import urllib.parse

EARTH_RADIUS_KM = 6371.0
ASSUMED_WALK_SPEED_KMH = 4.8  # ~ average adult walking pace
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_TIMEOUT_SECONDS = 10


def haversine_distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def estimate_walk_minutes(distance_km):
    """
    Straight-line-distance walk time estimate. This deliberately UNDER-
    estimates real walk time (no roads/detours), so it should be treated
    as a lower bound, not a routed ETA. Swap this out for a real routing
    API (e.g. OneMap Singapore's routing service) for production-grade
    walking times; the function boundary here is exactly where that
    would plug in without touching logic_manager.
    """
    hours = distance_km / ASSUMED_WALK_SPEED_KMH
    return round(hours * 60)


def geocode_location(location_text):
    """
    Resolve a free-text location (address / postal code / landmark) to
    (lat, lon) using the free OpenStreetMap Nominatim geocoder.

    Returns:
        (coords, error) tuple. coords is (lat, lon) tuple or None.
        error is a human-readable string or None.

    Never raises -- network failure, no results, or malformed responses
    are all reported as (None, error) so the caller can degrade
    gracefully (e.g. skip walk-time filtering rather than crash).
    """
    if not location_text or not location_text.strip():
        return None, "No location text provided."

    query = urllib.parse.urlencode({
        "q": f"{location_text}, Singapore",
        "format": "json",
        "limit": 1,
    })
    url = f"{NOMINATIM_URL}?{query}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "BiteFinderStudentApp/1.0 (educational project)"}
    )

    try:
        with urllib.request.urlopen(request, timeout=GEOCODE_TIMEOUT_SECONDS) as resp:
            results = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # network/timeout/HTTP/JSON errors all land here
        return None, f"Geocoding failed: {e}"

    if not results:
        return None, f"Could not find a location matching '{location_text}'."

    try:
        lat = float(results[0]["lat"])
        lon = float(results[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None, "Geocoding service returned an unexpected format."

    return (lat, lon), None


def walking_minutes_to_restaurant(user_coords, restaurant):
    """
    Compute walking minutes from the user's resolved coordinates to a
    restaurant record. Falls back to a legacy static field (kept for the
    original Yishun-only seed dataset) if the restaurant has no
    latitude/longitude on record.

    Returns:
        int|None -- minutes, or None if it genuinely cannot be determined
        (never guessed).
    """
    lat, lon = restaurant.get("latitude"), restaurant.get("longitude")
    if user_coords is not None and lat is not None and lon is not None:
        distance_km = haversine_distance_km(user_coords[0], user_coords[1], lat, lon)
        return estimate_walk_minutes(distance_km)

    # Legacy fallback for the original static Yishun seed data.
    legacy = restaurant.get("walking_minutes_from_yishun_mrt")
    if legacy is not None:
        return legacy

    return None
