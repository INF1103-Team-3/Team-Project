"""BRNS request boundary and output. BIS owns all user input."""

import json
import math
import sys
import re
import requests
from pathlib import Path

from BRNS import config, logic_manager
from shared import geocode_cache
from shared import debug_log as log
from shared import terminal_ui as ui
from BIS.sources.profile_schema import (
    CUISINES, clean_text, validate_travel_minutes, validate_value,
)

SEARCH_FIELDS = {
    "origin", "mode", "max_distance_km", "max_travel_minutes", "traffic_aware", "cuisine",
    "budget_per_person", "other_preferences",
    "dietary_requirements", "disliked_cuisines",
}
ORIGIN_FIELDS = {"query", "label", "latitude", "longitude"}


def display_debug(line):
    """Mirror shared operational logs to stderr when DEBUG is enabled."""
    print(line, file=sys.stderr)


def accept_bis_json(payload):
    """Validate one BIS search request without prompting or changing it."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise ValueError("BRNS requires valid BIS search JSON.") from error
    if not isinstance(payload, dict) or set(payload) != SEARCH_FIELDS:
        raise ValueError("BRNS requires the ten BIS search fields only.")
    origin = payload["origin"]
    if not isinstance(origin, dict) or set(origin) != ORIGIN_FIELDS:
        raise ValueError("BRNS requires a confirmed origin object.")
    query = clean_text(origin["query"], 200)
    label = clean_text(origin["label"], 500)
    latitude, longitude = origin["latitude"], origin["longitude"]
    if (type(latitude) not in (int, float)
            or type(longitude) not in (int, float)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not 1.15 <= latitude <= 1.48
            or not 103.60 <= longitude <= 104.10):
        raise ValueError("The search origin must be within Singapore.")
    if payload["mode"] not in ("walk", "drive", "transit"):
        raise ValueError("Choose walk, drive, or transit for the search.")
    distance = payload["max_distance_km"]
    minutes = payload["max_travel_minutes"]
    if (distance is None) == (minutes is None):
        raise ValueError("BRNS requires exactly one travel limit.")
    if payload["mode"] == "transit" and distance is not None:
        raise ValueError("Transit searches require a time limit.")
    distance = (validate_value("max_distance_km", distance)
                if distance is not None else None)
    minutes = validate_travel_minutes(minutes) if minutes is not None else None
    traffic_aware = payload["traffic_aware"]
    if type(traffic_aware) is not bool or (traffic_aware and
            (payload["mode"] != "drive" or minutes is None)):
        raise ValueError("Live traffic is available only for driving time searches.")
    if payload["budget_per_person"] is None:
        raise ValueError("Search budget is required.")
    if any(not isinstance(payload[field], list) for field in (
        "other_preferences", "dietary_requirements", "disliked_cuisines",
    )):
        raise ValueError("Search preferences and dietary requirements must be lists.")
    cuisine = payload["cuisine"]
    if not isinstance(cuisine, str) or cuisine not in (*CUISINES, "none"):
        raise ValueError("Choose a supported cuisine or none for the search.")
    other_preferences = validate_value(
        "other_preferences", payload["other_preferences"])
    logic_manager.minimum_rating(other_preferences)
    return {
        "origin": {
            "query": query, "label": label,
            "latitude": latitude, "longitude": longitude,
        },
        "mode": payload["mode"],
        "max_distance_km": distance,
        "max_travel_minutes": minutes, "traffic_aware": traffic_aware,
        "cuisine": cuisine,
        "budget_per_person": validate_value(
            "budget_per_person", payload["budget_per_person"]),
        "other_preferences": other_preferences,
        "dietary_requirements": validate_value(
            "dietary_requirements", payload["dietary_requirements"]),
        "disliked_cuisines": validate_value(
            "disliked_cuisines", payload["disliked_cuisines"]),
    }


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
    origin = (request["origin"]["latitude"],
              request["origin"]["longitude"])
    lookup = dict(request)
    lookup["free_text"] = _clean_free_text_query(
        request.get("other_preferences") or [])
    preferences = list(request["other_preferences"])
    preferences.sort(
        key=lambda item: not logic_manager.has_hard_preferences([item]))
    lookup["free_text"] = " ".join(preferences)
    saved_restaurants = load_saved_restaurants()
    log.debug_log(f"Loaded {len(saved_restaurants)} saved restaurants.", "DEBUG",
                  "BRNS.io_manager.find_candidates")
    candidates = build_candidates(origin, lookup, saved_restaurants)
    log.debug_log(f"Candidate builder returned {len(candidates)} records.",
                  "DEBUG", "BRNS.io_manager.find_candidates")
    return candidates


def show_results(results, announce_no_matches=True):
    """Display ranked restaurants without collecting any input."""
    matches = results["matches"]
    alternatives = results["alternatives"]
    if not matches and announce_no_matches:
        ui.message("No restaurants matched all your search choices.", "warning")
    if not matches and not alternatives:
        ui.message("No alternatives found either.", "warning")
        return
    number = 0
    for heading, items in (("Matches", matches), ("Alternatives", alternatives)):
        if not items:
            continue
        ui.section(f"{heading} ({len(items)})",
                   "match" if heading == "Matches" else "alternative")
        for item in items:
            number += 1
            _show_result(number, item, results,
                         "match" if heading == "Matches" else "alternative")


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
    number = 0
    for heading, items in (("Matches", results["matches"]),
                           ("Alternatives", results["alternatives"])):
        if not items:
            continue
        role = "match" if heading == "Matches" else "alternative"
        ui.section(f"{heading} ({len(items)})", role)
        for item in items:
            number += 1
            restaurant = item["restaurant"]
            mode = results["mode"]
            if results.get("limit_unit") == "minutes":
                minutes = restaurant.get(f"{mode}_minutes")
                distance = (f"{minutes:g} min by {mode}"
                            if minutes is not None else "travel time unavailable")
                if results.get("traffic_aware"):
                    distance += " (live traffic)"
            else:
                meters = restaurant.get(f"{mode}_meters")
                distance = (f"{meters / 1000:.2f} km by {mode}"
                            if meters is not None else "distance unavailable")
            rating = restaurant.get("rating")
            rating_text = (f" · Google {rating:g}/5"
                           if type(rating) in (int, float) else " · Google rating unavailable")
            ui.item(number, f"{restaurant['name']} · {distance}{rating_text}", role=role)


def show_no_matches(results):
    """Explain why the leading alternative is not a verified match."""
    ui.message("No fully verified matches for these search choices.",
               "warning")
    verification = results.get("halal_verification")
    if verification:
        if verification["errors"]:
            ui.message(
                "BRC could not complete official MUIS halal verification. "
                f"Google halal indications were used as an unofficial fallback "
                f"for {verification['google_fallback']} candidate(s).", "warning")
            if verification.get("database_missing"):
                ui.message(
                    "The cleaned BRC halal database is missing and its automatic "
                    "build failed. Run BRC/main.py to build it, then retry.",
                    "warning")
        elif (verification["verified"] == 0
              and verification["google_fallback"] == 0):
            ui.message(
                f"BRC checked {verification['checked']} candidate(s), but none "
                "matched an active official MUIS listing or had a Google halal "
                "indication.", "warning")
        elif verification["verified"]:
            ui.message(
                f"BRC verified {verification['verified']} halal candidate(s), "
                "but the remaining search requirements excluded them.",
                "warning")
    exclusions = results.get("excluded_reasons") or {}
    visible_exclusions = [
        (reason, count) for reason, count in exclusions.items()
        if reason != "MUIS halal certification not verified"
    ]
    if visible_exclusions:
        ui.line("  Excluded before results:", "warning")
        for reason, count in sorted(
                visible_exclusions, key=lambda item: item[1], reverse=True)[:3]:
            ui.line(f"    {count} — {reason[:1].upper()}{reason[1:]}",
                    "warning")
    alternatives = results["alternatives"]
    if not alternatives:
        if not verification:
            ui.message("No alternatives found. Try changing today's search.",
                       "warning")
        return
    cautions = [reason[2:] for reason in alternatives[0]["reasons"]
                if reason.startswith("! ")]
    if cautions:
        ui.message("Why the top alternative is not a match: "
                   + "; ".join(cautions[:3]) + ".", "warning")


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
    restaurant = item["restaurant"]
    cuisine = ", ".join(restaurant.get("cuisines") or []) or "Unavailable"
    dietary = ", ".join(
        item for item in restaurant.get("dietary_requirements") or []
        if item != "halal")
    halal = restaurant.get("halal_status")
    mode = results["mode"]
    source = restaurant.get(f"{mode}_source")
    if results.get("limit_unit") == "minutes":
        minutes = restaurant.get(f"{mode}_minutes")
        travel = (f"{minutes:g} min by {mode}"
                  if minutes is not None else "travel time unavailable")
        if results.get("traffic_aware"):
            travel += " (live traffic)"
        if source == "estimate":
            travel += " (estimate, unverified)"
    else:
        meters = restaurant.get(f"{mode}_meters")
        travel = (f"{meters / 1000:.2f} km by {mode}"
                  if meters is not None else "distance unavailable")
        if source == "estimate":
            travel += " (estimate, unverified)"
    average = restaurant.get("avg_price")
    starting = restaurant.get("price_start")
    price = (f"Average SGD {average:.2f}" if average is not None
             else f"From SGD {starting:.2f}" if starting is not None
             else "Unverified")
    ui.item(number, restaurant['name'], role=role)
    ui.line(f"     {restaurant.get('address') or 'Address unavailable'}", "muted")
    ui.field("Cuisine", cuisine, indent=5)
    ui.field("Price", price, indent=5)
    ui.field("Travel", travel, indent=5)
    rating = restaurant.get("rating")
    rating_count = restaurant.get("rating_count")
    rating_text = (f"{rating:g}/5" if type(rating) in (int, float)
                   else "Unavailable")
    if type(rating_count) is int and rating_count >= 0 and rating is not None:
        rating_text += f" ({rating_count:,} reviews)"
    ui.field("Google rating", rating_text, indent=5)
    ui.field("Hours today", restaurant.get("today_hours") or "Unavailable", indent=5)
    if dietary:
        ui.field("Dietary", dietary, indent=5)
    if halal == "official":
        ui.field("Halal", "Official MUIS certification verified",
                 indent=5, role="success")
    elif halal == "unofficial":
        ui.field("Halal", "Unofficial indication; not checked",
                 indent=5, role="warning")
    elif halal == "unverified" and "halal" in results["requested_dietary"]:
        ui.field("Halal", "Unverified", indent=5, role="warning")
    highlights = []
    checks = []
    for reason in item["reasons"]:
        if (reason == "! cuisine unavailable" and not restaurant.get("cuisines")):
            continue
        if (reason in ("! Halal (unofficial; not checked)",
                      "Halal (unofficial; not checked)") and halal == "unofficial"):
            continue
        if reason == "! halal status unverified" and halal == "unverified":
            continue
        caution = reason.startswith("! ")
        (checks if caution else highlights).append(
            reason[2:] if caution else reason)
    if highlights:
        ui.line("     Highlights:", "success")
        for reason in highlights:
            ui.line(f"       • {reason[:1].upper()}{reason[1:]}", "success")
    if checks:
        ui.line("     Things to check:", "warning")
        for reason in checks:
            ui.line(f"       • {reason[:1].upper()}{reason[1:]}", "warning")
    ui.line()


def show_route(name, route, link, mode, traffic_aware=False):
    ui.section(f"{mode.title()} route to {name}")
    if traffic_aware:
        ui.line("Travel time uses live traffic.", "muted")
    if route is not None:
        if mode == "transit":
            ui.field("Journey", f"{route['duration_min']} min by transit")
        else:
            ui.field("Journey", f"{route['distance_m']} m · "
                     f"{route['duration_min']} min")
        for step in route["steps"]:
            ui.line(f"  {step}")
    else:
        ui.line("  Detailed route unavailable; use this map link:", "warning")
    ui.field("Map", link)


# ---------- Google Places, geocoding, and routing (IO) ----------

def load_saved_restaurants(path=config.RESTAURANT_FILE):
    """Read only the current restaurant JSON format for search enrichment."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    restaurants = []
    for row in data:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        candidate = dict(row)
        cuisine = row.get("cuisine")
        candidate["cuisines"] = [cuisine] if cuisine in CUISINES else []
        candidate["dietary_requirements"] = [
            item for item in row.get("dietary") or []
            if item in ("halal", "vegetarian")]
        candidate["price_start"] = row.get("avg_price_low_sgd")
        candidate["price_end"] = row.get("avg_price_high_sgd")
        try:
            candidate["rating"] = float(row["g_rating"])
        except (KeyError, TypeError, ValueError):
            candidate["rating"] = None
        try:
            candidate["rating_count"] = int(row["g_no_reviews"])
        except (KeyError, TypeError, ValueError):
            candidate["rating_count"] = None
        candidate["halal_hint"] = row.get("halal_certification") == "unofficial"
        candidate["halal_certification"] = row.get("halal_certification")
        candidate["today_hours"] = logic_manager.today_hours_from_weekly(
            row.get("opening_hours"))
        restaurants.append(candidate)
    return restaurants


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

BAND_THRESHOLDS = (8.0, 15.0, 30.0)  # <=8 $, <=15 $$, <=30 $$$, else $$$$

def price_to_band(avg_price):
    for band, upper in zip(("inexpensive", "moderate", "expensive"), BAND_THRESHOLDS):
        if avg_price <= upper:
            return band
    return "very_expensive"


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
    """Derive a budget band from a price range (midpoint). None if no numbers."""
    vals = [v for v in (start, end) if v is not None]
    if not vals:
        return None
    return price_to_band(sum(vals) / len(vals))


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

_CUISINE_MAP = {
    "cafe": "cafe", "fast_food_restaurant": "fast food", "bakery": "bakery",
    "american_restaurant": "western", "pizza_restaurant": "western",
    "hamburger_restaurant": "western", "indian_restaurant": "indian",
    "malaysian_restaurant": "malaysian", "indonesian_restaurant": "indonesian",
}


def _cuisine_from_types(types):
    for t in types or []:
        if t in ("halal_restaurant", "vegetarian_restaurant", "vegan_restaurant"):
            continue
        if t in _CUISINE_MAP:
            return _CUISINE_MAP[t]
        if t.endswith("_restaurant"):
            return t[: -len("_restaurant")]
    return "unknown"

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

def _search_radius(req):
    """Choose a Places discovery radius; Routes decides actual eligibility."""
    if logic_manager.has_hard_preferences(
            req.get("other_preferences") or []):
        return 50000
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

def fetch_by_profile_text(origin, req):
    """Places Text Search scoped by dietary/cuisine and/or the user's
    free-text query (e.g. 'spicy', 'cafe', 'hawker centre').
    Returns [] on failure or when nothing is set."""
    lat, lng = origin
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
        return []
    log.debug_log("Text Places request started.", "INFO",
                  "BRNS.io_manager.fetch_by_profile_text")
    query = " ".join(terms)
    if not any(w in query for w in _VENUE_WORDS):
        query += " food"          # 'halal chinese' -> 'halal chinese food'
        # but 'hawker centre' stays as-is
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
    delta = _search_radius(req) / 111000.0   # meters -> degrees
    body = {
        "textQuery": query,
        "languageCode": "en",
        "pageSize": 20,
        "locationRestriction": {"rectangle": {
            "low": {"latitude": max(-90, lat - delta), "longitude": max(-180, lng - delta)},
            "high": {"latitude": min(90, lat + delta), "longitude": min(180, lng + delta)},
        }},
    }
    try:
        resp = requests.post(config.TEXT_SEARCH_URL, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        places = []
        for p in resp.json().get("places", []):
            parsed = _parse_place(p)
            if parsed:
                places.append(parsed)
        log.debug_log(f"Text Places returned {len(places)} usable records.",
                      "INFO", "BRNS.io_manager.fetch_by_profile_text")
        return places
    except (requests.RequestException, KeyError, ValueError) as err:
        _log_api_error("places_profile_text", err)
        return []

# ---------- enrichment: Places results x saved restaurants ----------

def _norm(name):
    return re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).strip()


def _match_saved_restaurant(place, saved_restaurants):
    p = _norm(place["name"])
    for entry in saved_restaurants:
        e = _norm(entry.get("name", ""))
        if e != p:
            continue
        address = _norm(entry.get("address", ""))
        if not address or address != _norm(place.get("address", "")):
            continue
        return entry
    return None


def enrich_place(place, saved_restaurants):
    """Merge saved fields into a Places result. Missing data stays
    None/'unknown' — never invented (business rule)."""
    entry = _match_saved_restaurant(place, saved_restaurants)
    live_fields = {
        "google_place_id": place.get("google_place_id"),
        "postal_code": place.get("postal_code"),
        "number": place.get("number"),
        "rating_count": place.get("rating_count"),
        "serves_vegetarian_food": place.get("serves_vegetarian_food") is True,
        "halal_hint": place.get("halal_hint") is True,
        "wheelchair_accessible": place.get("wheelchair_accessible"),
        "open_now": place.get("open_now"),
        "today_hours": place.get("today_hours"),
        "opening_hours": place.get("opening_hours"),
    }
    if entry:
        avg_price = entry.get("avg_price")
        saved_cuisines = [cuisine for cuisine in (
            entry.get("cuisines") or
            ([entry["cuisine"]] if entry.get("cuisine") else []))
            if cuisine in CUISINES]
        saved_dietary = (entry.get("dietary_requirements")
                         or entry.get("dietary") or [])
        band = (price_to_band(avg_price) if avg_price is not None
                else (place.get("price_level")
                      or _band_from_range(place.get("price_start"), place.get("price_end"))))
        return {**live_fields,
            "name": entry.get("name", place["name"]),
            "address": place["address"],
            "lat": place["lat"], "lng": place["lng"],
            "cuisines": saved_cuisines or [_cuisine_from_types(place["types"])],
            "dietary_requirements": sorted(set(
                saved_dietary
                + (["vegetarian"] if place.get("serves_vegetarian_food") else []))),
            "avg_price": avg_price,
            "price_band": band,
            "price_start": place.get("price_start"),
            "price_end": place.get("price_end"),
            "price_range": place.get("price_range"),
            "rating": place.get("rating"),
            "open_hours": entry.get("open_hours"),
            "spicy_options": entry.get("spicy_options"),
            "certification": entry.get("certification", "unknown"),
            "walk_minutes": None, "walk_meters": None,
            "drive_minutes": None, "drive_meters": None,
            "transit_minutes": None, "transit_meters": None,
            "source": "saved + google places",
        }
    return {**live_fields,
        "name": place["name"],
        "address": place["address"],
        "lat": place["lat"], "lng": place["lng"],
        "cuisines": [_cuisine_from_types(place["types"])],
        "dietary_requirements": (
            ["vegetarian"] if place.get("serves_vegetarian_food") else []),
        "avg_price": None,
        "price_band": (place.get("price_level")
                       or _band_from_range(place.get("price_start"), place.get("price_end"))),
        "price_start": place.get("price_start"),
        "price_end": place.get("price_end"),
        "price_range": place.get("price_range"),
        "rating": place.get("rating"),
        "open_hours": None,
        "spicy_options": None,
        "certification": "unknown",
        "walk_minutes": None, "walk_meters": None,
        "drive_minutes": None, "drive_meters": None,
        "transit_minutes": None, "transit_meters": None,
        "source": "google places",
    }


# ---------- Google Routes API ----------

def _haversine_km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _estimate_travel_minutes(origin, r, mode):
    """Straight-line distance / speed, +20% street factor. Labeled estimate.
    Walk: 80 m/min. Drive: ~500 m/min (~30 km/h urban SG average)."""
    if mode not in {"walk", "drive"}:
        raise ValueError("Transit journey times require a real route.")
    speed = 80 if mode == "walk" else 500
    meters = _haversine_km(origin, (r["lat"], r["lng"])) * 1000 * 1.2
    return max(1, round(meters / speed))


def travel_times_matrix(origin, restaurants, mode, traffic_aware=False):
    """ONE request for ALL restaurants, for ONE mode.
    Writes r[f'{mode}_minutes'] and r[f'{mode}_meters'].
    mode = 'walk' | 'drive' | 'transit'. Transit has no speed estimate.
    NOTE: computeRouteMatrix returns a bare JSON ARRAY."""
    if not restaurants:
        return
    log.debug_log(f"Route matrix requested for {len(restaurants)} candidates.",
                  "INFO", "BRNS.io_manager.travel_times_matrix")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("originIndex,destinationIndex,duration,"
                             "distanceMeters,status,condition"),
    }
    body = {
        "origins": [{"waypoint": {"location": {"latLng": {
            "latitude": origin[0], "longitude": origin[1]}}}}],
        "destinations": [{"waypoint": {"location": {"latLng": {
            "latitude": r["lat"], "longitude": r["lng"]}}}} for r in restaurants],
        "travelMode": {"walk": "WALK", "drive": "DRIVE",
                       "transit": "TRANSIT"}[mode],
    }
    if traffic_aware and mode == "drive":
        body["routingPreference"] = "TRAFFIC_AWARE"
    try:
        resp = requests.post(config.MATRIX_URL, headers=headers, json=body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        elements = data if isinstance(data, list) else data.get("elements", [])
        for el in elements:
            try:
                idx = el["destinationIndex"]
                if el.get("condition") == "ROUTE_NOT_FOUND":
                    continue
                status_code = (el.get("status") or {}).get("code", 0)
                if status_code not in (0, None):
                    continue
                restaurants[idx][f"{mode}_minutes"] = int(el["duration"].rstrip("s")) / 60
                restaurants[idx][f"{mode}_meters"] = int(el["distanceMeters"])
                restaurants[idx][f"{mode}_source"] = "route"
            except (KeyError, ValueError, TypeError):
                continue
    except (requests.RequestException, AttributeError, KeyError, ValueError) as err:
        _log_api_error(f"routes_matrix_{mode}", err)
    routed = sum(r.get(f"{mode}_source") == "route" for r in restaurants)
    log.debug_log(f"Route matrix supplied {routed} routes.", "INFO",
                  "BRNS.io_manager.travel_times_matrix")


def _fill_travel_estimates(origin, restaurants):
    """Per-mode fallback: fill missing walk/drive times with labeled estimates."""
    for r in restaurants:
        for mode in ("walk", "drive"):
            if r.get(f"{mode}_minutes") is None:
                r[f"{mode}_minutes"] = _estimate_travel_minutes(origin, r, mode)
                r[f"{mode}_meters"] = int(_haversine_km(origin, (r["lat"], r["lng"])) * 1000)
                r[f"{mode}_source"] = "estimate"


def format_transit_step(step):
    """Summarize a Google transit step without inventing missing stop facts."""
    details = step.get("transitDetails") or {}
    if not details:
        return step.get("navigationInstruction", {}).get("instructions")
    line = details.get("transitLine") or {}
    vehicle = (line.get("vehicle") or {}).get("name") or {}
    service = (line.get("nameShort") or line.get("name")
               or vehicle.get("text") or "Transit")
    text = f"Take {service}"
    if details.get("headsign"):
        text += f" toward {details['headsign']}"
    stops = details.get("stopDetails") or {}
    departure = (stops.get("departureStop") or {}).get("name")
    arrival = (stops.get("arrivalStop") or {}).get("name")
    if departure:
        text += f" from {departure}"
    if arrival:
        text += f" to {arrival}"
    if details.get("stopCount"):
        text += f" ({details['stopCount']} stops)"
    return text


def get_route(origin, destination, mode, traffic_aware=False):
    """ONE on-demand call for the chosen restaurant. None on failure."""
    log.debug_log("Directions request started.", "INFO",
                  "BRNS.io_manager.get_route")
    body = {
        "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}}},
        "travelMode": {"walk": "WALK", "drive": "DRIVE",
                       "transit": "TRANSIT"}[mode],
    }
    if traffic_aware and mode == "drive":
        body["routingPreference"] = "TRAFFIC_AWARE"
    field_mask = ("routes.duration,routes.distanceMeters,"
                  "routes.legs.steps.navigationInstruction")
    if mode == "transit":
        field_mask += (",routes.legs.steps.travelMode,"
                       "routes.legs.steps.transitDetails")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": field_mask,
    }
    try:
        resp = requests.post(config.ROUTES_URL, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        routes = resp.json().get("routes", [])
        if not routes:
            log.debug_log("Directions returned no route.", "WARNING",
                          "BRNS.io_manager.get_route")
            return None
        route = routes[0]
        steps = []
        for leg in route.get("legs", []):
            for s in leg.get("steps", []):
                text = (format_transit_step(s) if mode == "transit"
                        else s.get("navigationInstruction", {}).get(
                            "instructions"))
                if text:
                    steps.append(text)
        log.debug_log("Directions route returned.", "INFO",
                      "BRNS.io_manager.get_route")
        return {"duration_min": round(int(route["duration"].rstrip("s")) / 60),
                "distance_m": route["distanceMeters"],
                "steps": steps}
    except (requests.RequestException, KeyError, ValueError) as err:
        _log_api_error("get_route", err)
        return None


def build_maps_link(origin, destination, mode):
    """Free, no API call — opens the route in Google Maps (mode-aware)."""
    travelmode = {"walk": "walking", "drive": "driving",
                  "transit": "transit"}[mode]
    return (f"https://www.google.com/maps/dir/?api=1"
            f"&origin={origin[0]},{origin[1]}"
            f"&destination={destination[0]},{destination[1]}&travelmode={travelmode}")


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
    if not places:
        return []
    candidates, seen = [], set()
    for p in places:
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
