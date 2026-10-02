import os
import re
import json
import time
import difflib
import requests
import geo_utils

OUTPUT_FILE = os.path.join("food_data", "sg_restaurants.json")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

MUIS_HALAL_DIRECTORY_URL = (
    "https://raw.githubusercontent.com/msocietyhq/muis-datasets-unofficial/"
    "main/halal-directory/data.json"
)

MUIS_MATCH_POSTAL_NAME_THRESHOLD = 0.60
MUIS_MATCH_NO_POSTAL_NAME_THRESHOLD = 0.75
MUIS_MATCH_MAX_DISTANCE_M = 60

COMPANY_SUFFIX_PATTERN = re.compile(
    r"\b(pte\.?\s*ltd\.?|private\s+limited|llp|ltd\.?|inc\.?)\b", re.IGNORECASE
)
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9\s]")

AMENITY_TYPES = ["restaurant", "food_court", "cafe", "fast_food", "hawker_centre", "pub"]
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 120

DIET_TAG_MAP = {
    "diet:halal": "halal",
    "diet:vegetarian": "vegetarian",
    "diet:vegan": "vegan",
    "diet:gluten_free": "gluten_free",
    "diet:kosher": "kosher",
    "diet:lactose_free": "lactose_free",
}

PRICE_TAG_CANDIDATES = ["charge", "fee", "price_level", "cost"]


def build_overpass_query(amenity):
    return f"""
    [out:json][timeout:100];
    area["ISO3166-1"="SG"][admin_level=2]->.sg;
    nwr["amenity"="{amenity}"](area.sg);
    out center;
    """


def fetch_amenity_with_backoff(amenity):
    headers = {
        "User-Agent": "BiteFinderStudentApp/2.0 (+https://github.com/INF1103-Team-3/Team-Project)"
    }
    query = build_overpass_query(amenity)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            res = requests.post(
                OVERPASS_URL, data={"data": query}, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as e:
            wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"  [!] Network error on '{amenity}' ({e}). Retry {attempt}/{MAX_RETRIES} in {wait}s...")
            time.sleep(wait)
            continue
        if res.status_code == 200:
            try:
                return res.json().get("elements", [])
            except ValueError:
                print(f"  [!] '{amenity}': 200 response was not valid JSON.")
                return []
        if res.status_code in (429, 504):
            wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            print(f"  [!] '{amenity}' server busy (HTTP {res.status_code}). Retry {attempt}/{MAX_RETRIES} in {wait}s...")
            time.sleep(wait)
            continue
        print(f"  [!] Skipped '{amenity}': HTTP {res.status_code}")
        return []
    return []


def extract_coordinates(element):
    if element.get("type") == "node":
        return element.get("lat"), element.get("lon")
    center = element.get("center", {})
    return center.get("lat"), center.get("lon")


def extract_declared_dietary_tags(tags):
    declared = []
    for osm_key, app_label in DIET_TAG_MAP.items():
        if tags.get(osm_key) == "yes":
            declared.append(app_label)
    if tags.get("halal") == "yes" and "halal" not in declared:
        declared.append("halal")
    if tags.get("vegetarian") == "yes" and "vegetarian" not in declared:
        declared.append("vegetarian")
    return declared


def extract_price(tags):
    for tag in PRICE_TAG_CANDIDATES:
        raw = tags.get(tag)
        if raw:
            try:
                return round(float(raw), 2)
            except (TypeError, ValueError):
                pass
    return None


def build_address(tags):
    house = tags.get("addr:housenumber", "")
    block = tags.get("addr:block_number", tags.get("addr:block", ""))
    street = tags.get("addr:street", "")
    postal = tags.get("addr:postcode", "")
    number_part = block or house
    parts = [p for p in [number_part, street] if p]
    address = " ".join(parts)
    if postal:
        address = f"{address}, Singapore {postal}".strip(", ")
    return address or "Singapore", postal or None


def normalise_name(name):
    if not name:
        return ""
    n = name.lower()
    n = COMPANY_SUFFIX_PATTERN.sub(" ", n)
    n = NON_ALNUM_PATTERN.sub(" ", n)
    return " ".join(n.split())


def name_similarity(a, b):
    return difflib.SequenceMatcher(None, normalise_name(a), normalise_name(b)).ratio()


def fetch_muis_halal_directory():
    """In-memory fetch of MUIS halal directory without writing extra JSON files."""
    try:
        res = requests.get(MUIS_HALAL_DIRECTORY_URL, timeout=30)
    except requests.RequestException as e:
        return [], f"Network error fetching MUIS directory: {e}"
    if res.status_code != 200:
        return [], f"MUIS directory fetch failed: HTTP {res.status_code}"
    try:
        payload = res.json()
    except ValueError:
        return [], "MUIS directory response was not valid JSON."
    establishments = payload.get("establishments", [])
    if not isinstance(establishments, list) or not establishments:
        return [], "MUIS directory contained no establishments."
    return establishments, None


def _index_by_postal_code(establishments):
    index = {}
    for est in establishments:
        postal = (est.get("postal_code") or "").strip()
        if postal:
            index.setdefault(postal, []).append(est)
    return index


def match_against_muis(osm_record, establishments, postal_index):
    postal = (osm_record.get("postal_code") or "").strip()
    name = osm_record.get("name", "")
    if postal and postal in postal_index:
        best, best_score = None, 0.0
        for est in postal_index[postal]:
            score = name_similarity(name, est.get("name", ""))
            if score > best_score:
                best, best_score = est, score
        if best is not None and best_score >= MUIS_MATCH_POSTAL_NAME_THRESHOLD:
            return best
        return None

    lat, lon = osm_record.get("latitude"), osm_record.get("longitude")
    if lat is None or lon is None:
        return None
    best, best_score = None, 0.0
    for est in establishments:
        coords = est.get("coordinates") or {}
        if coords.get("lat") is None or coords.get("lng") is None:
            continue
        dist_m = geo_utils.haversine_distance_km(lat, lon, coords["lat"], coords["lng"]) * 1000
        if dist_m > MUIS_MATCH_MAX_DISTANCE_M:
            continue
        score = name_similarity(name, est.get("name", ""))
        if score > best_score:
            best, best_score = est, score
    if best is not None and best_score >= MUIS_MATCH_NO_POSTAL_NAME_THRESHOLD:
        return best
    return None


def apply_muis_cross_check(records):
    establishments, error = fetch_muis_halal_directory()
    if error:
        print(f"  [!] Skipping MUIS cross-check: {error}")
        return 0, 0
    postal_index = _index_by_postal_code(establishments)
    matched_count = 0
    for r in records:
        match = match_against_muis(r, establishments, postal_index)
        if match is not None:
            matched_count += 1
            r["dietary"] = "halal"
            r["certification"] = "officially verified by MUIS"
            r["cert_id"] = match.get("certificate_number")
        elif r.get("dietary") == "halal":
            r["certification"] = "unconfirmed"
        else:
            r["certification"] = "none"
    return matched_count, len(records)


def fetch_and_save_all_singapore():
    seen_osm_ids = set()
    records = []
    next_index = 1

    print("Fetching live, island-wide Singapore venues from OpenStreetMap...\n")
    for amenity in AMENITY_TYPES:
        print(f"Querying amenity type: {amenity}...")
        elements = fetch_amenity_with_backoff(amenity)
        added = 0
        for element in elements:
            osm_id = f"{element.get('type')}/{element.get('id')}"
            if osm_id in seen_osm_ids:
                continue
            tags = element.get("tags", {})
            name = tags.get("name")
            if not name:
                continue
            lat, lon = extract_coordinates(element)
            if lat is None or lon is None:
                continue

            seen_osm_ids.add(osm_id)
            cuisine = tags.get("cuisine", "").replace("_", " ").lower() or "unspecified"
            dietary_tags = extract_declared_dietary_tags(tags)
            price = extract_price(tags)
            address, postal_code = build_address(tags)

            # Construct new target dictionary schema
            records.append({
                # Mandatory/User Requested Fields
                "name": name,
                "cuisine": cuisine,
                "dietary": dietary_tags[0] if dietary_tags else "none",
                "avg_price": price if price is not None else 0.0,
                "allergens": [],  # OSM does not provide dish-level allergens natively
                "walk_minutes": 5, # Default walk estimate placeholder
                "open_hours": tags.get("opening_hours") or "Unknown",
                "spicy_options": True if "spicy" in cuisine else False,
                "certification": "community" if dietary_tags else "none",
                "cert_id": None,

                # Additional necessary fields for application logic
                "id": f"OSM{next_index:05d}",
                "osm_id": osm_id,
                "amenity_type": amenity,
                "address": address,
                "postal_code": postal_code,
                "latitude": lat,
                "longitude": lon,
                "data_source": "openstreetmap"
            })
            next_index += 1
            added += 1
        print(f"  -> Added {added} records.\n")
        time.sleep(1)

    print("Cross-checking halal status against MUIS's official certification registry...")
    matched_count, checked_count = apply_muis_cross_check(records)
    if checked_count:
        print(f"  -> {matched_count}/{checked_count} venues matched to a live MUIS halal certificate.\n")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    # Save purely as a list of restaurant dictionaries into ONE single file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Done. Saved {len(records)} restaurants to single file: {OUTPUT_FILE}.")


if __name__ == "__main__":
    fetch_and_save_all_singapore()