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
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except OSError:
        return False


def _log_api_error(context, err):
    try:
        with open(config.API_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{context}: {type(err).__name__}: {err}\n")
    except OSError:
        pass


def _norm(name):
    return re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).strip()


# ---------- catalog (flat file) ----------

def load_restaurants(path=config.RESTAURANT_FILE):
    data = _load_json(path)
    return data if isinstance(data, list) else []


def filter_by_dietary(restaurants, dietary):
    return [r for r in restaurants if r.get("dietary") == dietary]


def find_by_name(restaurants, name):
    return [r for r in restaurants if name.lower() in r.get("name", "").lower()]


# ---------- HalalFreak ----------

def load_halal_certified(path=config.HALAL_FILE):
    """Load the HalalFreak scrape. Missing or corrupt -> empty list."""
    data = _load_json(path)
    return data if isinstance(data, list) else []


def _extract_postal(text):
    if not text:
        return None
    m = re.search(r"\b(\d{6})\b", text)
    return m.group(1) if m else None


def _name_overlap(a_norm, b_norm, min_ratio=0.75):
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm or a_norm in b_norm or b_norm in a_norm:
        return True
    ta, tb = set(a_norm.split()), set(b_norm.split())
    if not ta or not tb:
        return False
    return len(ta & tb) / max(len(ta), len(tb)) >= min_ratio


def _is_halal(place, halal_list):
    """Match a Google Places result against the HalalFreak list.
    Returns (matched: bool, confidence: float, entry: dict|None).

    Priority:
      postal + name   -> 1.0
      name only       -> 0.75
      postal only     -> 0.5 (below threshold, rejected)
    """
    place_name = _norm(place.get("name", ""))
    place_postal = _extract_postal(place.get("address", ""))

    best, best_score = None, 0.0
    for entry in halal_list:
        entry_name = _norm(entry.get("name", ""))
        entry_postal = entry.get("postal_code")

        name_ok = _name_overlap(place_name, entry_name)
        postal_ok = bool(place_postal) and bool(entry_postal) and place_postal == entry_postal

        if name_ok and postal_ok:
            score = 1.0
        elif name_ok:
            score = 0.75
        elif postal_ok:
            score = 0.5
        else:
            continue

        if score > best_score:
            best, best_score = entry, score

    if best and best_score >= 0.7:
        return True, best_score, best
    return False, 0.0, None


# ---------- price helpers ----------

BAND_THRESHOLDS = (8.0, 15.0, 30.0)


def price_to_band(avg_price):
    for band, upper in zip(("inexpensive", "moderate", "expensive"), BAND_THRESHOLDS):
        if avg_price <= upper:
            return band
    return "very_expensive"


def _money_to_float(money):
    if not isinstance(money, dict) or "units" not in money:
        return None
    try:
        return float(money["units"]) + (money.get("nanos", 0) or 0) / 1e9
    except (TypeError, ValueError):
        return None


def _fmt_price_range(pr):
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
    vals = [v for v in (start, end) if v is not None]
    if not vals:
        return None
    return price_to_band(sum(vals) / len(vals))


# ---------- Google Geocoding API ----------

def geocode_location(address_text):
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


# ---------- Google Places API (New) ----------

_CUISINE_MAP = {
    "cafe": "cafe",
    "bakery": "bakery",
    "bar": "bar",
    "meal_takeaway": "takeaway",
    "fast_food_restaurant": "fast food",
    "food_court": "food court",
    "american_restaurant": "western",
    "hamburger_restaurant": "western",
    "pizza_restaurant": "italian",
    "italian_restaurant": "italian",
    "french_restaurant": "french",
    "steak_house": "steakhouse",
    "barbecue_restaurant": "barbecue",
    "japanese_restaurant": "japanese",
    "sushi_restaurant": "japanese",
    "ramen_restaurant": "japanese",
    "chinese_restaurant": "chinese",
    "dim_sum_restaurant": "chinese",
    "cantonese_restaurant": "chinese",
    "korean_restaurant": "korean",
    "thai_restaurant": "thai",
    "vietnamese_restaurant": "vietnamese",
    "indian_restaurant": "indian",
    "malaysian_restaurant": "malaysian",
    "indonesian_restaurant": "indonesian",
    "singaporean_restaurant": "local",
    "seafood_restaurant": "seafood",
    "mediterranean_restaurant": "mediterranean",
    "greek_restaurant": "greek",
    "turkish_restaurant": "turkish",
    "middle_eastern_restaurant": "middle eastern",
    "lebanese_restaurant": "lebanese",
    "mexican_restaurant": "mexican",
    "spanish_restaurant": "spanish",
    "vegetarian_restaurant": "vegetarian",
    "vegan_restaurant": "vegan",
}

_CUISINE_TO_GOOGLE_TYPES = {
    "japanese":      ["japanese_restaurant", "sushi_restaurant", "ramen_restaurant"],
    "chinese":       ["chinese_restaurant", "dim_sum_restaurant", "cantonese_restaurant"],
    "korean":        ["korean_restaurant"],
    "thai":          ["thai_restaurant"],
    "vietnamese":    ["vietnamese_restaurant"],
    "indian":        ["indian_restaurant"],
    "malaysian":     ["malaysian_restaurant"],
    "indonesian":    ["indonesian_restaurant"],
    "italian":       ["italian_restaurant", "pizza_restaurant"],
    "western":       ["american_restaurant", "hamburger_restaurant"],
    "french":        ["french_restaurant"],
    "mexican":       ["mexican_restaurant"],
    "spanish":       ["spanish_restaurant"],
    "turkish":       ["turkish_restaurant"],
    "greek":         ["greek_restaurant"],
    "lebanese":      ["lebanese_restaurant"],
    "mediterranean": ["mediterranean_restaurant"],
    "seafood":       ["seafood_restaurant"],
    "cafe":          ["cafe"],
    "bakery":        ["bakery"],
    "bar":           ["bar"],
    "fast food":     ["fast_food_restaurant"],
    "takeaway":      ["meal_takeaway"],
    "food court":    ["food_court"],
    "local":         ["singaporean_restaurant"],
}

_GENERIC_TYPES = {"restaurant", "food", "point_of_interest", "establishment"}

_NON_CUISINE_TYPES = {
    "halal_restaurant",
    "kosher_restaurant",
    "vegetarian_restaurant",
    "vegan_restaurant",
}

_BLOCKED_CUISINE_WORDS = {
    "halal", "kosher", "vegetarian", "vegan",
    "restaurant", "food", "point of interest", "establishment",
}

_NAME_CUISINE_HINTS = [
    ("sushi", "japanese"), ("ramen", "japanese"), ("izakaya", "japanese"),
    ("yakitori", "japanese"), ("tempura", "japanese"), ("udon", "japanese"),
    ("soba", "japanese"), ("donburi", "japanese"), ("katsu", "japanese"),
    ("teriyaki", "japanese"), ("sashimi", "japanese"), ("omakase", "japanese"),
    ("japanese", "japanese"),
    ("korean", "korean"), ("kimchi", "korean"), ("bibimbap", "korean"),
    ("thai", "thai"), ("tom yum", "thai"),
    ("vietnamese", "vietnamese"), ("pho", "vietnamese"), ("banh mi", "vietnamese"),
    ("indian", "indian"), ("biryani", "indian"), ("tandoori", "indian"),
    ("prata", "indian"), ("mamak", "indian"),
    ("chinese", "chinese"), ("dim sum", "chinese"), ("hokkien", "chinese"),
    ("teochew", "chinese"), ("cantonese", "chinese"), ("bak kut teh", "chinese"),
    ("char kway teow", "chinese"), ("wanton", "chinese"), ("wonton", "chinese"),
    ("yong tau foo", "chinese"), ("ban mian", "chinese"), ("fish soup", "chinese"),
    ("malay", "malay"), ("nasi", "malay"), ("satay", "malay"),
    ("rendang", "malay"), ("padang", "indonesian"), ("indonesian", "indonesian"),
    ("italian", "italian"), ("pizza", "italian"), ("pasta", "italian"),
    ("burger", "western"), ("fish and chips", "western"), ("western", "western"),
    ("steak", "steakhouse"), ("barbecue", "barbecue"), ("bbq", "barbecue"),
    ("mexican", "mexican"), ("taco", "mexican"), ("burrito", "mexican"),
    ("mediterranean", "mediterranean"), ("middle eastern", "middle eastern"),
    ("turkish", "turkish"), ("lebanese", "lebanese"),
]


def _cuisine_from_google_type(t):
    if not t or t in _GENERIC_TYPES or t in _NON_CUISINE_TYPES:
        return None
    if t in _CUISINE_MAP:
        return _CUISINE_MAP[t]
    if t.endswith("_restaurant"):
        return t[: -len("_restaurant")].replace("_", " ")
    return None


def _cuisine_from_name(name):
    if not name:
        return None
    n = name.lower()
    for keyword, cuisine in _NAME_CUISINE_HINTS:
        if keyword in n:
            return cuisine
    return None


def _cuisines_from_types(types, primary_type=None, primary_display=None, name=None):
    out = []

    if primary_display:
        cleaned = primary_display.strip().lower()
        for suffix in (" restaurant", " food", " cuisine"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]
                break
        if cleaned and cleaned not in _BLOCKED_CUISINE_WORDS and cleaned not in out:
            out.append(cleaned)

    if primary_type:
        mapped = _cuisine_from_google_type(primary_type)
        if mapped and mapped not in out:
            out.append(mapped)

    for t in types or []:
        mapped = _cuisine_from_google_type(t)
        if mapped and mapped not in out:
            out.append(mapped)

    if not out and name:
        inferred = _cuisine_from_name(name)
        if inferred:
            out.append(inferred)

    return out


def _search_radius_m(req):
    walk = req.get("max_walk_minutes")
    return max(500, min((walk if walk else 15) * 100, 20000))


def _places_headers():
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": config.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,"
            "places.formattedAddress,"
            "places.location,"
            "places.rating,"
            "places.userRatingCount,"
            "places.priceLevel,"
            "places.priceRange,"
            "places.types,"
            "places.name,"
            "places.primaryType,"
            "places.primaryTypeDisplayName,"
            "places.nationalPhoneNumber,"
            "places.internationalPhoneNumber,"
            "places.regularOpeningHours,"
            "places.accessibilityOptions"
        ),
    }


def _parse_places_response(response):
    places = []
    for p in response.json().get("places", []):
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
            "user_rating_count": p.get("userRatingCount"),
            "price_level": (p.get("priceLevel") or "").replace("PRICE_LEVEL_", "").lower() or None,
            "price_start": _money_to_float(pr.get("startPrice")),
            "price_end": _money_to_float(pr.get("endPrice")),
            "price_range": _fmt_price_range(pr),
            "types": p.get("types", []),
            "primary_type": p.get("primaryType"),
            "primary_type_display": (p.get("primaryTypeDisplayName") or {}).get("text"),
            "phone": (p.get("nationalPhoneNumber")
                      or p.get("internationalPhoneNumber")),
            "regular_opening_hours": p.get("regularOpeningHours"),
            "accessibility_options": p.get("accessibilityOptions") or {},
        })
    return places


def fetch_nearby_restaurants(origin, req, debug=False):
    lat, lng = origin

    cuisine = (req.get("cuisine") or "").strip().lower()
    included = _CUISINE_TO_GOOGLE_TYPES.get(cuisine)
    if not included:
        included = ["restaurant", "cafe", "fast_food_restaurant"]

    body = {
        "includedTypes": included,
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "locationRestriction": {"circle": {
            "center": {"latitude": lat, "longitude": lng},
            "radius": _search_radius_m(req),
        }},
    }
    try:
        resp = requests.post(config.PLACES_URL, headers=_places_headers(), json=body, timeout=15)
        if debug:
            print("DEBUG status:", resp.status_code)
            print("DEBUG includedTypes:", included)
            print("DEBUG body:", resp.text[:500])
        resp.raise_for_status()
        return _parse_places_response(resp)
    except (requests.RequestException, KeyError, ValueError) as err:
        _log_api_error("places_nearby_search", err)
        return []


# ---------- enrichment: Places x catalog x HalalFreak ----------

def _match_catalog(place, catalog):
    p = _norm(place["name"])
    for entry in catalog:
        e = _norm(entry.get("name", ""))
        if e and (e == p or e in p or p in e):
            return entry
    return None


def enrich_place(place, catalog, halal_list=None):
    """Merge catalog + HalalFreak fields into a Places result."""
    entry = _match_catalog(place, catalog)

    cuisines_list = _cuisines_from_types(
        place.get("types", []),
        primary_type=place.get("primary_type"),
        primary_display=place.get("primary_type_display"),
        name=place.get("name"),
    )

    if entry:
        catalog_cuisine = (entry.get("cuisine") or "").strip().lower()
        if catalog_cuisine and catalog_cuisine not in cuisines_list:
            cuisines_list.append(catalog_cuisine)

    primary_cuisine = cuisines_list[0] if cuisines_list else "unknown"

    if entry:
        avg_price = entry.get("avg_price")
        band = (price_to_band(avg_price) if avg_price is not None
                else (place.get("price_level")
                      or _band_from_range(place.get("price_start"), place.get("price_end"))))
        result = {
            "name": entry.get("name", place["name"]),
            "address": place["address"],
            "lat": place["lat"], "lng": place["lng"],
            "cuisine": primary_cuisine,
            "cuisines": cuisines_list,
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
    else:
        result = {
            "name": place["name"],
            "address": place["address"],
            "lat": place["lat"], "lng": place["lng"],
            "cuisine": primary_cuisine,
            "cuisines": cuisines_list,
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

    # Carry through fields from Google
    result["phone"] = place.get("phone")
    result["user_rating_count"] = place.get("user_rating_count")
    result["regular_opening_hours"] = place.get("regular_opening_hours")
    result["accessibility_options"] = place.get("accessibility_options") or {}
    result["types"] = place.get("types", [])
    result["primary_type"] = place.get("primary_type")

    # NEW: parse hours into weekday dict for the logic layer.
    result["weekday_hours"] = _parse_opening_hours(place.get("regular_opening_hours"))

    # HalalFreak tagging
    if halal_list:
        is_halal, confidence, hf_entry = _is_halal(place, halal_list)
        result["halal_certified"] = is_halal
        result["halal_confidence"] = round(confidence, 2)
        result["halal_db_name"] = hf_entry["name"] if hf_entry else None
        if is_halal:
            result["certification"] = "MUIS Halal"
            if result["dietary"] in (None, "unknown", "non-halal"):
                result["dietary"] = "halal"
    else:
        result["halal_certified"] = None
        result["halal_confidence"] = 0.0
        result["halal_db_name"] = None

    return result


# ---------- Google Routes API ----------

def _haversine_km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _estimate_walk_minutes(origin, r):
    meters = _haversine_km(origin, (r["lat"], r["lng"])) * 1000 * 1.2
    return max(1, round(meters / 80))


def walk_times_matrix(origin, restaurants):
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
    return (f"https://www.google.com/maps/dir/?api=1"
            f"&origin={origin[0]},{origin[1]}"
            f"&destination={destination[0]},{destination[1]}&travelmode=walking")


# ---------- candidate builder ----------

def build_candidates(origin, req, catalog, halal_list=None):
    if not config.USE_LIVE_GOOGLE:
        return [dict(r) for r in catalog]

    places = fetch_nearby_restaurants(origin, req)
    if not places:
        return []

    candidates, seen = [], set()
    for p in places:
        c = enrich_place(p, catalog, halal_list=halal_list)
        key = _norm(c["name"])
        if key not in seen:
            seen.add(key)
            candidates.append(c)

    walk_times_matrix(origin, candidates)
    for r in candidates:
        if r.get("walk_minutes") is None:
            r["walk_minutes"] = _estimate_walk_minutes(origin, r)
            r["walk_source"] = "estimate"
    return candidates


# ============================================================
# OUTPUT SCHEMA — team format
# ============================================================

_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]

_GOOGLE_DAY_TO_NAME = {
    0: "sunday", 1: "monday", 2: "tuesday", 3: "wednesday",
    4: "thursday", 5: "friday", 6: "saturday",
}


def _fmt_hhmm(hour, minute):
    try:
        return f"{int(hour):02d}{int(minute):02d}"
    except (TypeError, ValueError):
        return "0000"


def _parse_opening_hours(regular_hours):
    """Convert Google's regularOpeningHours into the team's weekday format."""
    if not isinstance(regular_hours, dict) or "periods" not in regular_hours:
        return {d: None for d in _DAY_ORDER}

    periods = regular_hours.get("periods") or []
    if not periods:
        return {d: None for d in _DAY_ORDER}

    by_day = {d: [] for d in _DAY_ORDER}

    for period in periods:
        open_info = period.get("open") or {}
        close_info = period.get("close") or {}
        if "day" not in open_info:
            continue

        day_name = _GOOGLE_DAY_TO_NAME.get(open_info["day"])
        if day_name is None:
            continue

        open_h = open_info.get("hour", 0)
        open_m = open_info.get("minute", 0)
        close_h = close_info.get("hour", 0)
        close_m = close_info.get("minute", 0)
        close_day = close_info.get("day")

        is_24h = (open_h == 0 and open_m == 0
                  and close_h == 0 and close_m == 0
                  and close_day is not None
                  and close_day != open_info.get("day"))
        if is_24h:
            by_day[day_name].append(("0000", "2359"))
        else:
            by_day[day_name].append((_fmt_hhmm(open_h, open_m),
                                     _fmt_hhmm(close_h, close_m)))

    out = {}
    for day in _DAY_ORDER:
        entries = by_day[day]
        if not entries:
            out[day] = []
            continue
        if any(p == ("0000", "2359") for p in entries):
            out[day] = ["0000", "2359"]
            continue
        earliest_open = min(p[0] for p in entries)
        latest_close = max(p[1] for p in entries)
        out[day] = [earliest_open, latest_close]

    return out


def _build_dietary_list(candidate):
    dietary = []
    internal = (candidate.get("dietary") or "").strip().lower()
    cuisines_lower = {(c or "").lower() for c in (candidate.get("cuisines") or [])}
    types_lower = {(t or "").lower() for t in (candidate.get("types") or [])}

    if (candidate.get("halal_certified") is True
            or internal == "halal"
            or "halal" in cuisines_lower
            or "halal_restaurant" in types_lower):
        dietary.append("halal")

    if (internal == "vegan"
            or "vegan" in cuisines_lower
            or "vegan_restaurant" in types_lower):
        dietary.append("vegan")

    return dietary


def _build_halal_certification(candidate):
    cuisines_lower = {(c or "").lower() for c in (candidate.get("cuisines") or [])}
    types_lower = {(t or "").lower() for t in (candidate.get("types") or [])}

    if candidate.get("halal_certified") is True:
        return "official"
    if "halal" in cuisines_lower or "halal_restaurant" in types_lower:
        return "non-official"
    return []


def _clean_cuisine_list(candidate):
    raw = list(candidate.get("cuisines") or [])
    if not raw and candidate.get("cuisine"):
        raw = [candidate["cuisine"]]

    cleaned = []
    for c in raw:
        low = (c or "").strip().lower()
        if not low or low in _BLOCKED_CUISINE_WORDS:
            continue
        if low not in cleaned:
            cleaned.append(low)
    return cleaned


def build_output_record(candidate):
    addr = candidate.get("address") or ""
    postal = _extract_postal(addr) or ""

    accessibility = candidate.get("accessibility_options") or {}
    wheelchair = bool(accessibility.get("wheelchairAccessibleEntrance", False))

    rating = candidate.get("rating")
    reviews = candidate.get("user_rating_count")

    return {
        "name": candidate.get("name", ""),
        "postal_code": str(postal) if postal else "",
        "number": str(candidate.get("phone") or ""),
        "cuisine": _clean_cuisine_list(candidate),
        "dietary": _build_dietary_list(candidate),
        "opening_hours": candidate.get("weekday_hours")
                         or _parse_opening_hours(candidate.get("regular_opening_hours")),
        "wheelchair_accessible": wheelchair,
        "halal_certification": _build_halal_certification(candidate),
        "g_rating": str(rating) if rating is not None else "",
        "g_no_reviews": str(reviews) if reviews is not None else "",
    }


# ---------- search history ----------

def load_history(path=config.HISTORY_FILE):
    data = _load_json(path)
    return data if isinstance(data, list) else []


def save_history(entry, path=config.HISTORY_FILE):
    history = load_history(path)
    history.append(entry)
    return _save_json(path, history)