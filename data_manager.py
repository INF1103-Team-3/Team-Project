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
    """priceRange object -> display string like '$20–70'. None if absent."""
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
    return f"${start:.0f}–{end:.0f}"


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


# ---------- Google Places API (New): nearby search ----------

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


def _search_radius_m(req):
    """~80 m/min walking + buffer, clamped to Places limits (500-20000)."""
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
                             "places.priceRange,places.types"),
    }
    body = {
        "includedTypes": ["restaurant", "cafe", "fast_food_restaurant"],
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "locationRestriction": {"circle": {
            "center": {"latitude": lat, "longitude": lng},
            "radius": _search_radius_m(req),
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
            name = p.get("displayName", {}).get("text")
            if not name:
                continue
            pr = p.get("priceRange") or {}
            places.append({
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
            })
        return places
    except (requests.RequestException, KeyError, ValueError) as err:
        _log_api_error("places_search", err)
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
            "spicy_options": entry.get("spicy_options"),
            "certification": entry.get("certification", "unknown"),
            "walk_minutes": None,
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
        "spicy_options": None,
        "certification": "unknown",
        "walk_minutes": None,
        "source": "google places",
    }


# ---------- Google Routes API ----------

def _haversine_km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _estimate_walk_minutes(origin, r):
    """Straight-line distance / 80 m per min, +20% street factor. Labeled estimate."""
    meters = _haversine_km(origin, (r["lat"], r["lng"])) * 1000 * 1.2
    return max(1, round(meters / 80))


def walk_times_matrix(origin, restaurants):
    """ONE request for ALL restaurants. Sets r['walk_minutes'] (minutes or None).
    NOTE: computeRouteMatrix returns a bare JSON ARRAY (not the usual Google envelope)."""
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
        "travelMode": "WALK",
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
                minutes = round(int(el["duration"].rstrip("s")) / 60)
                restaurants[idx]["walk_minutes"] = minutes
                restaurants[idx]["walk_source"] = "routes-api"
            except (KeyError, ValueError, TypeError):
                continue
    except (requests.RequestException, AttributeError, KeyError, ValueError) as err:
        _log_api_error("routes_matrix", err)


def get_walking_route(origin, destination):
    """ONE on-demand call for the user's chosen restaurant. None on failure."""
    body = {
        "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
        "destination": {"location": {"latLng": {"latitude": destination[0], "longitude": destination[1]}}},
        "travelMode": "WALK",
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


def build_maps_link(origin, destination):
    """Free, no API call — opens the walking route in Google Maps."""
    return (f"https://www.google.com/maps/dir/?api=1"
            f"&origin={origin[0]},{origin[1]}"
            f"&destination={destination[0]},{destination[1]}&travelmode=walking")


# ---------- candidate builder ----------

def build_candidates(origin, req, catalog):
    """Live mode: Places -> catalog enrichment -> Routes walk times.
    Offline mode: catalog only (deterministic; demo backup)."""
    if not config.USE_LIVE_GOOGLE:
        return [dict(r) for r in catalog]
    places = fetch_nearby_restaurants(origin, req)
    if not places:
        return []
    candidates, seen = [], set()
    for p in places:
        c = enrich_place(p, catalog)
        key = _norm(c["name"])
        if key not in seen:
            seen.add(key)
            candidates.append(c)
    walk_times_matrix(origin, candidates)
    for r in candidates:                      # fallback if matrix fails
        if r.get("walk_minutes") is None:
            r["walk_minutes"] = _estimate_walk_minutes(origin, r)
            r["walk_source"] = "estimate"
    return candidates


# ---------- search history ----------

def load_history(path=config.HISTORY_FILE):
    data = _load_json(path)
    return data if isinstance(data, list) else []


def save_history(entry, path=config.HISTORY_FILE):
    history = load_history(path)
    history.append(entry)
    return _save_json(path, history)
