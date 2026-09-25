"""Data layer — system memory + all external data sources (Google APIs).
No printing, no AI, no business rules. Every function fails gracefully."""
import json
import os
import re
import math
import requests
import config


# ---------- generic helpers ----------

def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError:
        return False


def _log_api_error(context, err):
    """Spec requirement: handle API failure gracefully - log and continue, never crash."""
    try:
        with open("data/api_errors.log", "a", encoding="utf-8") as f:
            f.write(f"{context}: {type(err).__name__}: {err}\n")
    except OSError:
        pass


# ---------- catalog (flat file) ----------

def load_restaurants(path=config.RESTAURANT_FILE):
    """Load all records on startup. Missing or corrupt file -> empty list."""
    data = _load_json(path)
    return data if isinstance(data, list) else []


def filter_by_dietary(restaurants, dietary):
    return [r for r in restaurants if r.get("dietary") == dietary]


def find_by_name(restaurants, name):
    return [r for r in restaurants if name.lower() in r.get("name", "").lower()]


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
    """'postal code' / 'landmark' -> (lat, lng) or None. Cached forever."""
    key = (address_text or "").strip().lower()
    if not key:
        return None
    cache = _load_json(config.GEOCODE_CACHE_FILE)
    if not isinstance(cache, dict):
        cache = {}
    if key in cache:
        return tuple(cache[key])
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
        cache[key] = [loc["lat"], loc["lng"]]
        _save_json(config.GEOCODE_CACHE_FILE, cache)
        return loc["lat"], loc["lng"]
    except (requests.RequestException, KeyError, ValueError):
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
    Also builds the weekly opening-hours map (Google day index: 0=Sunday)."""
    name = p.get("displayName", {}).get("text")
    if not name:
        return None
    pr = p.get("priceRange") or {}
    weekly = {}
    for period in (p.get("regularOpeningHours") or {}).get("periods", []):
        open_info = period.get("open", {})
        close_info = period.get("close", {}) or {"hour": 23, "minute": 59}
        o = f"{open_info.get('hour', 0):02d}:{open_info.get('minute', 0):02d}"
        c = f"{close_info['hour']:02d}:{close_info['minute']:02d}"
        weekly[open_info.get("day", -1)] = f"{o}-{c}"
    return {
        "name": name,
        "address": p.get("formattedAddress", "unavailable"),
        "lat": p["location"]["latitude"],
        "lng": p["location"]["longitude"],
        "rating": p.get("rating"),
        "price_level": (p.get("priceLevel") or "").replace("PRICE_LEVEL_", "").lower() or None,
        "price_start": _money_to_float(pr.get("startPrice")),
        "price_end": _money_to_float(pr.get("endPrice")),
        "price_range": _fmt_price_range(pr),
        "types": p.get("types", []),
        "weekly_hours": weekly if weekly else None,
    }

def _search_radius(req):
    """Search extent from travel input. Walk: ~100 m/min. Drive: km -> meters,
    scaled by ~0.8 (roads are longer than straight lines), clamped to 50 km."""
    if req.get("mode") == "drive" and req.get("max_drive_km"):
        return max(1000, min(int(req["max_drive_km"] * 1000 * 0.8), 50000))
    walk = req.get("max_walk_minutes")
    return max(500, min((walk if walk else 15) * 100, 20000))


def fetch_nearby_restaurants(origin, req, debug=False):
    """ONE Places request per search (up to 20 places). [] on failure."""
    lat, lng = origin
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("places.displayName,places.formattedAddress,"
                             "places.location,places.rating,places.priceLevel,"
                             "places.priceRange,places.types,"
                             "places.regularOpeningHours"),
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
            print("DEBUG status:", resp.status_code)
            print("DEBUG body:", resp.text[:500])
        resp.raise_for_status()
        places = []
        for p in resp.json().get("places", []):
            parsed = _parse_place(p)
            if parsed:
                places.append(parsed)
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
    dietary = (req.get("dietary") or "none").strip()
    free_text = (req.get("free_text") or "").strip().lower()[:30]
    terms = []
    if dietary not in ("none", ""):
        terms.append(dietary)
    if cuisine not in ("any", ""):
        terms.append(cuisine)
    if free_text:
        terms.append(free_text)
    if not terms:
        return []
    query = " ".join(terms)
    if not any(w in query for w in _VENUE_WORDS):
        query += " food"          # 'halal chinese' -> 'halal chinese food'
        # but 'hawker centre' stays as-is
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("places.displayName,places.formattedAddress,"
                             "places.location,places.rating,places.priceLevel,"
                             "places.priceRange,places.types,"
                             "places.regularOpeningHours"),
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
        return places
    except (requests.RequestException, KeyError, ValueError) as err:
        _log_api_error("places_profile_text", err)
        return []

# ---------- enrichment: Places results x catalog ----------

def _norm(name):
    return re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).strip()


def _match_catalog(place, catalog):
    p = _norm(place["name"])
    for entry in catalog:
        e = _norm(entry.get("name", ""))
        if e and (e == p or e in p or p in e):
            return entry
    return None


def enrich_place(place, catalog):
    """Merge catalog fields into a Places result. Missing data stays
    None/'unknown' — never invented (business rule)."""
    entry = _match_catalog(place, catalog)
    if entry:
        avg_price = entry.get("avg_price")
        band = (price_to_band(avg_price) if avg_price is not None
                else (place.get("price_level")
                      or _band_from_range(place.get("price_start"), place.get("price_end"))))
        return {
            "name": entry.get("name", place["name"]),
            "address": place["address"],
            "lat": place["lat"], "lng": place["lng"],
            "cuisine": entry.get("cuisine") or _cuisine_from_types(place["types"]),
            "dietary": entry.get("dietary", "unknown"),
            "allergens": entry.get("allergens"),
            "avg_price": avg_price,
            "price_band": band,
            "price_start": place.get("price_start"),
            "price_end": place.get("price_end"),
            "price_range": place.get("price_range"),
            "rating": place.get("rating"),
            "open_hours": entry.get("open_hours"),
            "weekly_hours": place.get("weekly_hours"),
            "spicy_options": entry.get("spicy_options"),
            "certification": entry.get("certification", "unknown"),
            "walk_minutes": None, "walk_meters": None,
            "drive_minutes": None, "drive_meters": None,
            "source": "catalog + google places",
        }
    return {
        "name": place["name"],
        "address": place["address"],
        "lat": place["lat"], "lng": place["lng"],
        "cuisine": _cuisine_from_types(place["types"]),
        "dietary": "unknown",
        "allergens": None,
        "avg_price": None,
        "price_band": (place.get("price_level")
                       or _band_from_range(place.get("price_start"), place.get("price_end"))),
        "price_start": place.get("price_start"),
        "price_end": place.get("price_end"),
        "price_range": place.get("price_range"),
        "rating": place.get("rating"),
        "open_hours": None,
        "weekly_hours": place.get("weekly_hours"),
        "spicy_options": None,
        "certification": "unknown",
        "walk_minutes": None, "walk_meters": None,
        "drive_minutes": None, "drive_meters": None,
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
    speed = 80 if mode == "walk" else 500
    meters = _haversine_km(origin, (r["lat"], r["lng"])) * 1000 * 1.2
    return max(1, round(meters / speed))


def travel_times_matrix(origin, restaurants, mode):
    """ONE request for ALL restaurants, for ONE mode.
    Writes r[f'{mode}_minutes'] and r[f'{mode}_meters'].
    mode = 'walk' | 'drive'. NOTE: computeRouteMatrix returns a bare JSON ARRAY."""
    if not restaurants:
        return
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
        "travelMode": "WALK" if mode == "walk" else "DRIVE",
    }
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
                restaurants[idx][f"{mode}_minutes"] = round(int(el["duration"].rstrip("s")) / 60)
                restaurants[idx][f"{mode}_meters"] = int(el.get("distanceMeters", 0))
            except (KeyError, ValueError, TypeError):
                continue
    except (requests.RequestException, AttributeError, KeyError, ValueError) as err:
        _log_api_error(f"routes_matrix_{mode}", err)


def _fill_travel_estimates(origin, restaurants):
    """Per-mode fallback: fill missing walk/drive times with labeled estimates."""
    for r in restaurants:
        for mode in ("walk", "drive"):
            if r.get(f"{mode}_minutes") is None:
                r[f"{mode}_minutes"] = _estimate_travel_minutes(origin, r, mode)
                r[f"{mode}_meters"] = int(_haversine_km(origin, (r["lat"], r["lng"])) * 1000)
                r[f"{mode}_source"] = "estimate"


def get_route(origin, destination, mode):
    """ONE on-demand call for the chosen restaurant. None on failure."""
    body = {
        "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}}},
        "travelMode": "WALK" if mode == "walk" else "DRIVE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": ("routes.duration,routes.distanceMeters,"
                             "routes.legs.steps.navigationInstruction"),
    }
    try:
        resp = requests.post(config.ROUTES_URL, headers=headers, json=body, timeout=15)
        resp.raise_for_status()
        routes = resp.json().get("routes", [])
        if not routes:
            return None
        route = routes[0]
        steps = []
        for leg in route.get("legs", []):
            for s in leg.get("steps", []):
                text = s.get("navigationInstruction", {}).get("instructions")
                if text:
                    steps.append(text)
        return {"duration_min": round(int(route["duration"].rstrip("s")) / 60),
                "distance_m": route["distanceMeters"],
                "steps": steps}
    except (requests.RequestException, KeyError, ValueError):
        return None


def build_maps_link(origin, destination, mode):
    """Free, no API call — opens the route in Google Maps (mode-aware)."""
    travelmode = "walking" if mode == "walk" else "driving"
    return (f"https://www.google.com/maps/dir/?api=1"
            f"&origin={origin[0]},{origin[1]}"
            f"&destination={destination[0]},{destination[1]}&travelmode={travelmode}")


# ---------- candidate builder ----------

def build_candidates(origin, req, catalog):
    """Live mode: profile-scoped search (dietary + cuisine + free text) ->
    catalog enrichment -> BOTH walk and drive times. Offline: catalog only."""
    if not config.USE_LIVE_GOOGLE:
        return [dict(r) for r in catalog]
    cuisine = (req.get("cuisine") or "any").lower()
    dietary = (req.get("dietary") or "none").lower()
    free_text = (req.get("free_text") or "").strip()
    places = []
    if cuisine not in ("any", "") or dietary not in ("none", "") or free_text:
        places = fetch_by_profile_text(origin, req)      # trigger lives HERE
    if not places:                       # fallback: generic nearby search
        places = fetch_nearby_restaurants(origin, req)
    if not places:
        return []
    candidates, seen = [], set()
    for p in places:
        if not isinstance(p, dict) or "name" not in p:
            _log_api_error("candidate_build", f"malformed place skipped: {p}")
            continue
        c = enrich_place(p, catalog)
        key = _norm(c["name"])
        if key not in seen:
            seen.add(key)
            candidates.append(c)
    for mode in ("walk", "drive"):       # dual mode: BOTH matrices
        travel_times_matrix(origin, candidates, mode)
    _fill_travel_estimates(origin, candidates)
    return candidates


# ---------- search history ----------

def load_history(path=config.HISTORY_FILE):
    data = _load_json(path)
    return data if isinstance(data, list) else []


def save_history(entry, path=config.HISTORY_FILE):
    history = load_history(path)
    history.append(entry)
    return _save_json(path, history)
