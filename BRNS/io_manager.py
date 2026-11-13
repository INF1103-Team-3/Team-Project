"""BRNS request boundary and output. BIS owns all user input."""

import json
import math
import sys
import re
import requests
from pathlib import Path

from BRNS import config, logic_manager
from BRNS.classes.io.gateways.google.google_route_gateway import GoogleRouteGateway
from BRNS.classes.io.adapters.io_manager import IOManager
from BRNS.classes.logic.evaluation.restaurant_enricher import RestaurantEnricher
from common import geocode_cache
from common import debug_log as log
from common import recommendation_ui
from common import terminal_ui as ui
from BIS.sources.profile_schema import (
    CUISINES, clean_text, validate_travel_minutes, validate_value,
)

SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "max_travel_minutes", "traffic_aware", "cuisine",
    "budget_per_person", "other_preferences",
    "dietary_requirements", "disliked_cuisines",
}
ORIGIN_FIELDS = {"query", "label", "latitude", "longitude"}
_MANAGER = None
_ENRICHER = RestaurantEnricher()


def manager():
    """Return the configured BRNS IO Manager."""
    global _MANAGER
    if _MANAGER is None:
        from BRNS import data_manager
        from BRNS.classes.io.gateways.google.candidate_search import CandidateSearch
        search = CandidateSearch(data_manager.manager(), logic_manager.manager(),
                                 sys.modules[__name__], log)
        _MANAGER = IOManager(
            sys.modules[__name__], logic_manager.manager(), log, search)
    return _MANAGER


def display_debug(line):
    """Mirror shared operational logs to stderr when DEBUG is enabled."""
    print(line, file=sys.stderr)


def accept_bis_json(payload):
    """Validate one BIS search request without prompting or changing it."""
    return manager().accept_bis_json(payload)


def _clean_free_text_query(preferences):
    """Exclude rating floor patterns from Places search text."""
    cleaned = []
    for pref in preferences:
        stripped = logic_manager._RATING_FLOOR.sub("", pref).strip()
        stripped = re.sub(r"\b(?:and|with)\b", " ", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"^[,\s&/]+|[,\s&/]+$", "", stripped).strip()
        if stripped:
            cleaned.append(stripped)
    return " ".join(cleaned)


def find_candidates(request):
    """Collect restaurant facts through Places or saved records."""
    return manager().find_candidates(request)


def show_results(results, announce_no_matches=True):
    """Display ranked restaurants without collecting any input."""
    recommendation_ui.show_results(results, announce_no_matches)


def display_record(record):
    """Display one ranked restaurant record."""
    display_result({"matches": [record], "alternatives": [], "mode": "walk"})


def display_list(records):
    """Display a validated collection of ranked restaurant records."""
    display_result({"matches": list(records), "alternatives": [],
                    "mode": "walk"})


def display_result(result):
    """Display one complete BRNS result dictionary."""
    show_results(result, announce_no_matches=False)


def show_result_list(results):
    """Show a compact numbered list before optional details or routing."""
    recommendation_ui.show_result_list(results)


def show_no_matches(results):
    """Explain why the leading alternative is not a verified match."""
    recommendation_ui.show_no_matches(results)


def show_halal_verification_start(candidate_count, database_missing=False):
    """Show the official halal check stage before potentially slow BRC work."""
    ui.message(
        f"BRC is checking {candidate_count} candidate(s) against official "
        "MUIS halal records.")
    if database_missing:
        ui.message(
            "BRC is preparing its cleaned MUIS database; the first check may "
            "take longer.", "warning")


def show_ai_ranking_start(candidate_count, timeout_seconds):
    """Tell the user what happens during the bounded AI ranking stage."""
    ui.message(
        f"BRNS found {candidate_count} candidate(s). AI is ranking them "
        f"(up to {timeout_seconds:g} seconds).")


def show_halal_verification_summary(summary):
    """Show how many candidates BRC accepted or rejected."""
    ui.message(
        f"BRC halal check: {summary['verified']} verified, "
        f"{summary['not_verified']} not verified.")
    if summary["google_fallback"]:
        ui.message(
            f"Using {summary['google_fallback']} Google-indicated halal "
            "candidate(s) as unofficial fallback results.", "warning")
    if summary["errors"]:
        ui.message(
            f"BRC encountered {summary['errors']} "
            f"{summary['error_type']} error"
            f"{'s' if summary['errors'] != 1 else ''} during individual "
            "checks; it continued checking the other candidates and used "
            "Google halal information where available. "
            f"{summary['excluded']} candidate(s) had no accepted halal "
            "evidence. Details: logs/bitefinder.log.", "warning")


def _show_result(number, item, results, role):
    """Print one restaurant card with the evidence behind its ranking."""
    recommendation_ui.show_result_card(number, item, results, role)


def show_route(name, route, link, mode, traffic_aware=False):
    recommendation_ui.show_route(name, route, link, mode, traffic_aware)


# ---------- Google Places, geocoding, and routing (IO) ----------

def load_saved_restaurants(path=config.RESTAURANT_FILE):
    """Preserve the saved-enrichment API through Data and Logic owners."""
    from BRNS import data_manager
    return logic_manager.manager().saved_candidates(
        data_manager.manager().load_candidate_records(path))


def _log_api_error(context, err):
    """Record only error type and HTTP status, never URL or response body."""
    if isinstance(err, str):
        kind = "invalid response"
        status = None
    else:
        kind = type(err).__name__
        status = getattr(getattr(err, "response", None), "status_code", None)
    detail = f"{kind}; HTTP {status}" if status is not None else kind
    log.debug_log(detail, "WARNING", f"BRNS.io_manager.{context}")


# ---------- price helpers ----------

BAND_THRESHOLDS = RestaurantEnricher.BAND_THRESHOLDS  # <=8 $, <=15 $$, <=30 $$$, else $$$$

def price_to_band(avg_price):
    return _ENRICHER.price_to_band(avg_price)



def _money_to_float(money):
    """Google Money object -> float (e.g. {'units': '20', 'nanos': 0} -> 20.0)."""
    if not isinstance(money, dict) or "units" not in money:
        return None
    try:
        return float(money["units"]) + (money.get("nanos", 0) or 0) / 1e9
    except (TypeError, ValueError):
        return None


def _fmt_price_range(pr):
    """priceRange object -> display string like '$20-70'. None if absent."""
    if not isinstance(pr, dict):
        return None
    start = _money_to_float(pr.get("startPrice"))
    end = _money_to_float(pr.get("endPrice"))
    if start is None and end is None:
        return None
    if start is None:
        return f"up to ${end:.0f}"
    if end is None or end <= start:
        return f"from ${start:.0f}"
    return f"${start:.0f}-{end:.0f}"


def _band_from_range(start, end):
    return _ENRICHER._band_from_range(start, end)



# ---------- Google Geocoding API (classic, with permanent cache) ----------

def geocode_location(address_text):
    """'postal code' / 'landmark' -> (lat, lng) or None. Cached globally."""
    key = (address_text or "").strip()
    if not key:
        return None
    cached = geocode_cache.lookup(key)
    if cached:
        log.debug_log("Geocode cache hit.", "DEBUG",
                      "BRNS.io_manager.geocode_location")
        return cached
    log.debug_log("Geocoding request started.", "INFO",
                  "BRNS.io_manager.geocode_location")
    try:
        resp = requests.get(
            config.GEOCODE_URL,
            params={"address": address_text, "key": config.GOOGLE_MAPS_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        geocode_cache.remember((key,), loc["lat"], loc["lng"])
        log.debug_log("Geocoding result cached.", "INFO",
                      "BRNS.io_manager.geocode_location")
        return loc["lat"], loc["lng"]
    except (requests.RequestException, KeyError, ValueError, RuntimeError) as err:
        _log_api_error("geocode_location", err)
        return None


# ---------- Google Places API (New): nearby + profile text search ----------

_CUISINE_MAP = RestaurantEnricher.CUISINE_MAP


def _cuisine_from_types(types):
    return _ENRICHER._cuisine_from_types(types)


def _weekday_index(name):
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    return days.index(name.lower()) if name.lower() in days else None


def _hours_string_for_day(regular_hours, weekday_index):
    """regularOpeningHours.periods -> 'HH:MM-HH:MM' for the given day, or None.
    Google weekday index: 0=Sunday..6=Saturday. Handles past-midnight closes
    by using the period's OPEN day (e.g. Fri 18:00-02:00 shows under Friday)."""
    if not isinstance(regular_hours, dict):
        return None
    for period in regular_hours.get("periods", []):
        open_info = period.get("open", {})
        close_info = period.get("close", {})
        if open_info.get("day") != weekday_index:
            continue
        o_h, o_m = open_info.get("hour", 0), open_info.get("minute", 0)
        if close_info:
            c_h, c_m = close_info.get("hour", 0), close_info.get("minute", 0)
        else:                       # open-ended (rare)
            c_h, c_m = 23, 59
        return (f"{o_h:02d}:{o_m:02d}-{c_h:02d}:{c_m:02d}")
    return None

def _parse_place(p):
    """Raw Google place object -> our normalized dict (or None if unusable).
    Also converts regular hours into the full weekly schedule."""
    name = (p.get("displayName") or {}).get("text")
    point = p.get("location") or {}
    if not name or "latitude" not in point or "longitude" not in point:
        return None
    pr = p.get("priceRange") or {}
    current_hours = p.get("currentOpeningHours")
    regular_hours = p.get("regularOpeningHours")
    weekly = logic_manager.weekly_opening_hours(regular_hours)
    return {
        "google_place_id": p.get("id"),
        "name": name,
        "address": p.get("formattedAddress", "unavailable"),
        "postal_code": (p.get("postalAddress") or {}).get("postalCode"),
        "number": p.get("nationalPhoneNumber"),
        "lat": point["latitude"],
        "lng": point["longitude"],
        "rating": p.get("rating"),
        "rating_count": p.get("userRatingCount"),
        "serves_vegetarian_food": (
            p.get("servesVegetarianFood") is True
            or "vegetarian_restaurant" in (p.get("types") or [])
            or "vegan_restaurant" in (p.get("types") or [])),
        "halal_hint": "halal_restaurant" in (p.get("types") or []),
        "wheelchair_accessible": (p.get("accessibilityOptions") or {}).get(
            "wheelchairAccessibleEntrance"),
        "open_now": logic_manager.open_now(current_hours),
        "today_hours": logic_manager.today_hours(
            current_hours if current_hours is not None else regular_hours),
        "price_level": (p.get("priceLevel") or "").replace("PRICE_LEVEL_", "").lower() or None,
        "price_start": _money_to_float(pr.get("startPrice")),
        "price_end": _money_to_float(pr.get("endPrice")),
        "price_range": _fmt_price_range(pr),
        "types": p.get("types", []),
        "opening_hours": weekly,
    }

def _travel_radius(req):
    """Radius in meters implied by the user's travel mode and limit."""
    if req.get("max_travel_minutes") is not None:
        speed = {"walk": 100, "drive": 650, "transit": 650}[req["mode"]]
        return max(500, min(int(req["max_travel_minutes"] * speed), 50000))
    if req.get("mode") == "drive" and req.get("max_drive_km"):
        return max(1000, min(int(req["max_drive_km"] * 1000 * 0.8), 50000))
    distance = req.get("max_distance_km")
    if distance is not None:
        return max(500, min(int(distance * 1000), 20000))
    walk = req.get("max_walk_minutes")
    return max(500, min((walk if walk else 15) * 100, 20000))


def _search_radius(req):
    """Choose a Places discovery radius; Routes decides actual eligibility."""
    if logic_manager.has_hard_preferences(
            req.get("other_preferences") or []):
        return 50000
    return _travel_radius(req)


def fetch_nearby_restaurants(origin, req, debug=False):
    """ONE Places request per search (up to 20 places). [] on failure."""
    log.debug_log("Nearby Places request started.", "INFO",
                  "BRNS.io_manager.fetch_nearby_restaurants")
    lat, lng = origin
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("places.id,places.displayName,places.formattedAddress,"
                             "places.location,places.rating,places.priceLevel,"
                             "places.priceRange,places.types,places.userRatingCount,"
                             "places.currentOpeningHours,places.regularOpeningHours,"
                             "places.nationalPhoneNumber,places.postalAddress,"
                             "places.accessibilityOptions,places.servesVegetarianFood"),
    }
    body = {
        "includedTypes": ["restaurant", "cafe", "fast_food_restaurant"],
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "locationRestriction": {"circle": {
            "center": {"latitude": lat, "longitude": lng},
            "radius": _search_radius(req),
        }},
    }
    try:
        resp = requests.post(config.PLACES_URL, headers=headers, json=body, timeout=15)
        if debug:
            log.debug_log(f"Nearby Places HTTP {resp.status_code}.", "DEBUG",
                          "BRNS.io_manager.fetch_nearby_restaurants")
        resp.raise_for_status()
        places = []
        for p in resp.json().get("places", []):
            parsed = _parse_place(p)
            if parsed:
                places.append(parsed)
        log.debug_log(f"Nearby Places returned {len(places)} usable records.",
                      "INFO", "BRNS.io_manager.fetch_nearby_restaurants")
        return places
    except (requests.RequestException, KeyError, ValueError) as err:
        _log_api_error("places_search", err)
        return []


_VENUE_WORDS = ("food", "cafe", "hawker", "restaurant", "centre", "center",
                "court", "market", "kopi", "canteen", "bakery", "bar")


def _build_text_query(req, default_query=None):
    """Build a Places Text Search query from dietary, cuisine, and free-text terms."""
    cuisine = (req.get("cuisine") or "").strip()
    dietary = req.get("dietary_requirements") or []
    raw_free_text = (req.get("free_text") or "").strip()
    free_text = logic_manager._RATING_FLOOR.sub("", raw_free_text).strip()
    free_text = re.sub(r"\b(?:and|with)\b", " ", free_text, flags=re.IGNORECASE)
    free_text = re.sub(r"^[,\s&/]+|[,\s&/]+$", "", free_text).strip().lower()[:200]
    terms = list(dietary)
    if cuisine not in ("any", "none", ""):
        terms.append(cuisine)
    if free_text:
        terms.append(free_text)
    if not terms:
        return default_query
    query = " ".join(terms)
    if not any(w in query for w in _VENUE_WORDS):
        query += " food"          # 'halal chinese' -> 'halal chinese food'
    return query


def _run_text_search(origin, query, radius_m, error_tag, max_pages=1):
    """Execute Google Places Text Search anchored by DISTANCE bias around origin."""
    lat, lng = origin
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("places.id,places.displayName,places.formattedAddress,"
                             "places.location,places.rating,places.priceLevel,"
                             "places.priceRange,places.types,places.userRatingCount,"
                             "places.currentOpeningHours,places.regularOpeningHours,"
                             "places.nationalPhoneNumber,places.postalAddress,"
                             "places.accessibilityOptions,places.servesVegetarianFood,"
                             "nextPageToken"),
    }
    # A circle *bias* anchors DISTANCE ranking on origin (a rectangle restriction
    # does not and scatters results island-wide for drive/transit searches).
    body = {
        "textQuery": query,
        "languageCode": "en",
        "pageSize": 20,
        "openNow": True,
        "rankPreference": "DISTANCE",
        "locationBias": {"circle": {
            "center": {"latitude": lat, "longitude": lng},
            "radius": radius_m,
        }},
    }
    places = []
    try:
        for _ in range(max_pages):
            resp = requests.post(config.TEXT_SEARCH_URL, headers=headers,
                                 json=body, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for p in data.get("places", []):
                parsed = _parse_place(p)
                if parsed and _haversine_km(origin, (parsed["lat"], parsed["lng"])) * 1000 <= radius_m:
                    places.append(parsed)
            token = data.get("nextPageToken")
            if not token:
                break
            body = dict(body, pageToken=token)
    except (requests.RequestException, KeyError, ValueError, AttributeError) as err:
        _log_api_error(error_tag, err)
        return []
    return places


def fetch_by_profile_text(origin, req):
    """Places Text Search scoped by dietary/cuisine and/or the user's
    free-text query (e.g. 'spicy', 'cafe', 'hawker centre').
    Returns [] on failure or when nothing is set."""
    query = _build_text_query(req, default_query=None)
    if not query:
        return []
    log.debug_log("Text Places request started.", "INFO",
                  "BRNS.io_manager.fetch_by_profile_text")
    radius_m = float(min(_search_radius(req), 50000))
    places = _run_text_search(origin, query, radius_m, "places_profile_text", max_pages=1)
    log.debug_log(f"Text Places returned {len(places)} usable records.",
                  "INFO", "BRNS.io_manager.fetch_by_profile_text")
    return places


OPEN_SEARCH_MAX_PAGES = 1   # 1 page x 20 open places keeps AI ranking fast and within token limits


def fetch_open_places(origin, req):
    """Text Search restricted to places open right now, nearest first.

    Nearby Search returns only the 20 closest places and cannot filter by
    opening status, so late at night most of them are closed and discarded.
    When Nearby Search drops closed slots, asking Text Search for openNow=True
    with DISTANCE ranking fills the candidate pool with nearby open venues.
    """
    query = _build_text_query(req, default_query="restaurants")
    log.debug_log("Open-now Text Places request started.", "INFO",
                  "BRNS.io_manager.fetch_open_places")
    radius_m = float(min(_travel_radius(req), 50000))
    places = _run_text_search(
        origin, query, radius_m, "places_open_text", max_pages=OPEN_SEARCH_MAX_PAGES)
    log.debug_log(f"Open-now Text Places returned {len(places)} usable records.",
                  "INFO", "BRNS.io_manager.fetch_open_places")
    return places

# ---------- enrichment: Places results x saved restaurants ----------

def _norm(name):
    return _ENRICHER._norm(name)



def _match_saved_restaurant(place, saved_restaurants):
    return _ENRICHER._match_saved_restaurant(place, saved_restaurants)



def enrich_place(place, saved_restaurants):
    """Compatibility entry point for the domain enrichment policy."""
    return logic_manager.manager().enrich_place(place, saved_restaurants)



# ---------- Google Routes API ----------

_ROUTE_GATEWAY = GoogleRouteGateway(config, log, _log_api_error)


def _haversine_km(first, second):
    return _ROUTE_GATEWAY.haversine_km(first, second)


def _estimate_travel_minutes(origin, restaurant, mode):
    return _ROUTE_GATEWAY.estimate_travel_minutes(
        origin, restaurant, mode)


def travel_times_matrix(origin, restaurants, mode, traffic_aware=False):
    return _ROUTE_GATEWAY.travel_times_matrix(
        origin, restaurants, mode, traffic_aware)


def _fill_travel_estimates(origin, restaurants):
    return _ROUTE_GATEWAY.fill_travel_estimates(origin, restaurants)


def format_transit_step(step):
    return _ROUTE_GATEWAY.format_transit_step(step)


def get_route(origin, destination, mode, traffic_aware=False):
    return _ROUTE_GATEWAY.get_route(
        origin, destination, mode, traffic_aware)


def build_maps_link(origin, destination, mode):
    return _ROUTE_GATEWAY.build_maps_link(origin, destination, mode)


# ---------- candidate builder ----------

def build_candidates(origin, req, saved_restaurants):
    """Live Places search with saved enrichment or offline saved records."""
    if not config.USE_LIVE_GOOGLE:
        open_restaurants = [
            restaurant for restaurant in saved_restaurants
            if logic_manager.open_now_from_weekly(restaurant.get("opening_hours"))
        ]
        log.debug_log(f"Saved fallback returned {len(open_restaurants)} open candidates.",
                      "INFO", "BRNS.io_manager.build_candidates")
        return [dict(r, source="offline restaurants")
                for r in open_restaurants]
    cuisine = (req.get("cuisine") or "any").lower()
    dietary = req.get("dietary_requirements") or []
    free_text = (req.get("free_text") or "").strip()
    places = []
    if cuisine not in ("any", "none", "") or dietary or free_text:
        places = fetch_by_profile_text(origin, req)
        if places and not any(
                isinstance(place, dict) and place.get("open_now") is True
                for place in places):
            log.debug_log("Text search found no confirmed open places; trying nearby.",
                          "INFO", "BRNS.io_manager.build_candidates")
            places = []
    if not places:                       # fallback: generic nearby search
        log.debug_log("Text search empty; trying nearby Places.", "INFO",
                      "BRNS.io_manager.build_candidates")
        places = fetch_nearby_restaurants(origin, req)
        # Nearby Search returns at most 20 closest venues without an openNow
        # filter. When closed venues consume those slots, supplement with
        # openNow=True Text Search so surrounding open places are discovered.
        if any(isinstance(p, dict) and p.get("open_now") is not True for p in places):
            places = list(places) + fetch_open_places(origin, req)
    if not places:
        return []
    candidates, seen = [], set()
    for p in places:
        if len(candidates) >= 20:
            break
        if not isinstance(p, dict) or "name" not in p:
            _log_api_error("candidate_build", "malformed place skipped")
            continue
        if p.get("open_now") is not True:
            log.debug_log("Skipped a place without confirmed open status.",
                          "INFO", "BRNS.io_manager.build_candidates")
            continue
        c = enrich_place(p, saved_restaurants)
        c["google_search_rank"] = len(candidates) + 1
        key = _norm(c["name"])
        if key not in seen:
            seen.add(key)
            candidates.append(c)
    travel_times_matrix(origin, candidates, req.get("mode", "walk"),
                        req.get("traffic_aware", False))
    _fill_travel_estimates(origin, candidates)
    estimated = sum(c.get(f"{req.get('mode', 'walk')}_source") == "estimate"
                    for c in candidates)
    log.debug_log(
        f"Built {len(candidates)} unique candidates; "
        f"{estimated} travel estimates.", "INFO",
        "BRNS.io_manager.build_candidates")
    return candidates
