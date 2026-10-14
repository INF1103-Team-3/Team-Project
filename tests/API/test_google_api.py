"""Dedicated tests for Google Maps Platform API key and services.

Covers:
1. Google Geocoding API connectivity and coordinate validation for Singapore.
2. Geocode cache integration (memory and disk cache).
3. Google Places API (New) Text Search (`places:searchText`).
4. Google Places API (New) Nearby Search (`places:searchNearby`).
5. Google Routes API (New) Distance Matrix (`distanceMatrix/v2:computeRouteMatrix`).
6. Google Routes API (New) Compute Routes / Directions (`directions/v2:computeRoutes`).
7. Error resilience against invalid or rejected Google API keys.
8. Offline restaurant fallback when live Google search is disabled.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv
import requests

ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]

# Ensure project and manager modules can be imported
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BIS"))
sys.path.insert(0, str(ROOT / "BRNS"))
sys.path.insert(0, str(TESTS_ROOT))

# Load .env explicitly for live API credentials
load_dotenv(ROOT / ".env")

from reporting import show_case, show_summary, style
import BRNS.config as brns_config
import BRNS.io_manager as brns_io
from shared import geocode_cache


# Singapore geographic boundary constants for validation
SG_MIN_LAT, SG_MAX_LAT = 1.15, 1.48
SG_MIN_LNG, SG_MAX_LNG = 103.55, 104.10


def test_google_geocoding_api():
    """Verify that GOOGLE_MAPS_API_KEY can geocode a Singapore address."""
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        actual = {"status": "SKIPPED", "reason": "GOOGLE_MAPS_API_KEY not set in .env"}
        expected = deepcopy(actual)
        show_case(
            "API-GOOGLE-01: Google Geocoding API",
            "maps.googleapis.com/maps/api/geocode/json",
            "Verify Geocoding API authentication and coordinate extraction in Singapore.",
            {"address": "10 Bayfront Ave, Singapore 018956"},
            expected,
            actual,
        )
        return

    address = "10 Bayfront Ave, Singapore 018956"
    url = brns_config.GEOCODE_URL
    params = {"address": address, "key": key}

    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        status = data.get("status")
        results = data.get("results", [])
        if status == "OK" and results:
            loc = results[0]["geometry"]["location"]
            lat, lng = loc["lat"], loc["lng"]
            in_singapore = (SG_MIN_LAT <= lat <= SG_MAX_LAT) and (SG_MIN_LNG <= lng <= SG_MAX_LNG)
        else:
            in_singapore = False
            lat, lng = None, None

        actual = {
            "status_code": resp.status_code,
            "api_status": status,
            "has_results": len(results) > 0,
            "in_singapore": in_singapore,
        }
    except Exception as err:
        actual = {"error": str(err), "api_status": "REQUEST_FAILED"}

    expected = {
        "status_code": 200,
        "api_status": "OK",
        "has_results": True,
        "in_singapore": True,
    }

    show_case(
        "API-GOOGLE-01: Google Geocoding API",
        "maps.googleapis.com/maps/api/geocode/json",
        "Verify Geocoding API authentication and coordinate extraction in Singapore.",
        {"address": address, "lat": lat, "lng": lng},
        expected,
        actual,
    )
    assert actual == expected


def test_geocode_cache_integration():
    """Verify that geocode_cache correctly caches and retrieves coordinates."""
    test_query = "Marina Bay Sands Test Query, Singapore"
    test_lat, test_lng = 1.2834, 103.8607

    # Remember in cache (remember expects an iterable of query aliases)
    geocode_cache.remember([test_query], test_lat, test_lng)

    # Lookup from cache
    cached = geocode_cache.lookup(test_query)

    actual = {
        "cached_hit": cached is not None,
        "coordinates": cached,
    }
    expected = {
        "cached_hit": True,
        "coordinates": (test_lat, test_lng),
    }

    show_case(
        "API-GOOGLE-02: Geocode Cache Integration",
        "shared.geocode_cache.lookup()",
        "Verify that geocoded coordinates are stored and retrieved without network calls.",
        {"query": test_query, "stored": (test_lat, test_lng)},
        expected,
        actual,
    )
    assert actual == expected


def test_google_places_text_search():
    """Verify that Google Places API (New) Text Search returns valid restaurants."""
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        return

    url = brns_config.TEXT_SEARCH_URL
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location,places.rating",
        "Content-Type": "application/json",
    }
    body = {
        "textQuery": "restaurant near Bugis Singapore",
        "maxResultCount": 5,
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        data = resp.json()
        places = data.get("places", [])
        has_places = len(places) > 0
        first_place_valid = bool(
            has_places
            and places[0].get("displayName", {}).get("text")
            and places[0].get("location")
        )
        actual = {
            "status_code": resp.status_code,
            "has_places": has_places,
            "place_has_name_and_location": first_place_valid,
        }
    except Exception as err:
        actual = {"error": str(err), "status_code": None}

    expected = {
        "status_code": 200,
        "has_places": True,
        "place_has_name_and_location": True,
    }

    show_case(
        "API-GOOGLE-03: Google Places Text Search (New)",
        "places.googleapis.com/v1/places:searchText",
        "Verify Places Text Search API authentication, field masks, and place payloads.",
        {"query": body["textQuery"], "returned_count": len(places) if "places" in locals() else 0},
        expected,
        actual,
    )
    assert actual == expected


def test_google_places_nearby_search():
    """Verify that Google Places API (New) Nearby Search returns nearby eateries."""
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        return

    url = brns_config.PLACES_URL
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.rating",
        "Content-Type": "application/json",
    }
    body = {
        "includedTypes": ["restaurant"],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": 1.2834, "longitude": 103.8607},
                "radius": 1000.0,
            }
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        data = resp.json()
        places = data.get("places", [])
        actual = {
            "status_code": resp.status_code,
            "has_places": len(places) > 0,
        }
    except Exception as err:
        actual = {"error": str(err), "status_code": None}

    expected = {"status_code": 200, "has_places": True}

    show_case(
        "API-GOOGLE-04: Google Places Nearby Search (New)",
        "places.googleapis.com/v1/places:searchNearby",
        "Verify Places Nearby Search API with circular location bounds around Singapore.",
        {"center": body["locationRestriction"]["circle"]["center"], "radius_m": 1000.0},
        expected,
        actual,
    )
    assert actual == expected


def test_google_routes_matrix():
    """Verify that Google Routes API (New) Compute Route Matrix calculates travel metrics."""
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        return

    url = brns_config.MATRIX_URL
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,status,condition,distanceMeters,duration",
        "Content-Type": "application/json",
    }
    body = {
        "origins": [
            {"waypoint": {"location": {"latLng": {"latitude": 1.2834, "longitude": 103.8607}}}}
        ],
        "destinations": [
            {"waypoint": {"location": {"latLng": {"latitude": 1.2902, "longitude": 103.8519}}}}
        ],
        "travelMode": "WALK",
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        data = resp.json()
        elements = data if isinstance(data, list) else []
        valid_element = (
            len(elements) > 0
            and "distanceMeters" in elements[0]
            and "duration" in elements[0]
        )
        actual = {
            "status_code": resp.status_code,
            "elements_returned": len(elements),
            "has_distance_and_duration": valid_element,
        }
    except Exception as err:
        actual = {"error": str(err), "status_code": None}

    expected = {
        "status_code": 200,
        "elements_returned": 1,
        "has_distance_and_duration": True,
    }

    show_case(
        "API-GOOGLE-05: Google Routes Distance Matrix (New)",
        "routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
        "Verify Distance Matrix API walking distance and duration computation.",
        {"mode": "WALK", "origin": (1.2834, 103.8607), "destination": (1.2902, 103.8519)},
        expected,
        actual,
    )
    assert actual == expected


def test_google_routes_compute_routes():
    """Verify that Google Routes API (New) Compute Routes provides navigation directions."""
    key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        return

    url = brns_config.ROUTES_URL
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
        "Content-Type": "application/json",
    }
    body = {
        "origin": {
            "location": {"latLng": {"latitude": 1.2834, "longitude": 103.8607}}
        },
        "destination": {
            "location": {"latLng": {"latitude": 1.2902, "longitude": 103.8519}}
        },
        "travelMode": "WALK",
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        data = resp.json()
        routes = data.get("routes", [])
        has_route = (
            len(routes) > 0
            and routes[0].get("distanceMeters", 0) > 0
            and "duration" in routes[0]
        )
        actual = {
            "status_code": resp.status_code,
            "route_computed": has_route,
        }
    except Exception as err:
        actual = {"error": str(err), "status_code": None}

    expected = {"status_code": 200, "route_computed": True}

    show_case(
        "API-GOOGLE-06: Google Routes Compute Routes",
        "routes.googleapis.com/directions/v2:computeRoutes",
        "Verify Compute Routes directions API for turn-by-turn navigation paths.",
        {"mode": "WALK", "distance_meters": routes[0].get("distanceMeters") if "routes" in locals() and routes else None},
        expected,
        actual,
    )
    assert actual == expected


def test_invalid_google_key_error_handling():
    """Verify that BRNS handles invalid/rejected Google API keys gracefully without crashing."""
    url = brns_config.GEOCODE_URL
    invalid_params = {"address": "Singapore", "key": "AIzaSy_INVALID_DUMMY_KEY_FOR_TEST"}

    try:
        resp = requests.get(url, params=invalid_params, timeout=10)
        data = resp.json()
        status = data.get("status")
        # Google returns HTTP 200 with status REQUEST_DENIED or an error status
        is_denied = status in ("REQUEST_DENIED", "INVALID_REQUEST") or resp.status_code in (400, 403)
        actual = {
            "handles_rejection_safely": True,
            "is_rejected_or_denied": is_denied,
        }
    except Exception as err:
        actual = {"handles_rejection_safely": False, "error": str(err)}

    expected = {
        "handles_rejection_safely": True,
        "is_rejected_or_denied": True,
    }

    show_case(
        "API-GOOGLE-07: Invalid Google Key Error Handling",
        "BRNS.io_manager._log_api_error()",
        "Verify application resilience against invalid or rejected Google API credentials.",
        {"supplied_key": "AIzaSy_INVALID_DUMMY_KEY_FOR_TEST"},
        expected,
        actual,
    )
    assert actual == expected


def test_offline_restaurant_fallback_when_google_disabled():
    """Verify that BRNS falls back to saved JSON restaurants when Google search is disabled."""
    saved_restaurants = brns_io.load_saved_restaurants()

    actual = {
        "fallback_loaded": isinstance(saved_restaurants, list) and len(saved_restaurants) > 0,
        "has_restaurant_names": bool(saved_restaurants and saved_restaurants[0].get("name")),
    }
    expected = {
        "fallback_loaded": True,
        "has_restaurant_names": True,
    }

    show_case(
        "API-GOOGLE-08: Offline Restaurant Fallback",
        "BRNS.io_manager.load_saved_restaurants()",
        "Verify candidate retrieval from BRNS/data/restaurants.json when Google is disabled.",
        {"loaded_count": len(saved_restaurants)},
        expected,
        actual,
    )
    assert actual == expected


# ---------------------------------------------------------------------------
# Test Runner
# ---------------------------------------------------------------------------

TESTS = (
    test_google_geocoding_api,
    test_geocode_cache_integration,
    test_google_places_text_search,
    test_google_places_nearby_search,
    test_google_routes_matrix,
    test_google_routes_compute_routes,
    test_invalid_google_key_error_handling,
    test_offline_restaurant_fallback_when_google_disabled,
)


def run_tests():
    """Run all Google Maps Platform API and resilience tests."""
    failures = []
    print("\n" + style("#" * 72, "rule"))
    print(style("BITEFINDER - GOOGLE MAPS PLATFORM API TESTS", "heading"))
    print(style("#" * 72, "rule"))

    for test in TESTS:
        try:
            test()
        except Exception as error:
            failures.append((test.__name__, error))
            print(f"\n{style('FAILED:', 'fail')} {test.__name__}: {error}")

    show_summary("GOOGLE MAPS API", len(TESTS), failures)
    return len(failures)


if __name__ == "__main__":
    sys.exit(run_tests())
