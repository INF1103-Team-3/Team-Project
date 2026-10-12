"""Store searched BRNS restaurants and approved search history."""
import json
import os
import re
from BRNS import config


# ---------- generic helpers ----------

def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_json(path, data, *, compact_hours=False):
    try:
        if compact_hours:
            ordered = []
            weekdays = ("monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday")
            for row in data:
                if not isinstance(row, dict):
                    ordered.append(row)
                    continue
                record = dict(row)
                hours = record.get("opening_hours")
                if isinstance(hours, dict):
                    record["opening_hours"] = {
                        day: hours[day] for day in weekdays if day in hours
                    }
                ordered.append(record)
            data = ordered
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        if compact_hours:
            formatted = re.sub(
                r'\[\n[ \t]*"(\d{4})",\n[ \t]*"(\d{4})"\n[ \t]*\]',
                r'["\1", "\2"]', formatted)
            formatted = re.sub(
                r'\[\n(?:[ \t]*\["\d{4}", "\d{4}"\],?\n)+[ \t]*\]',
                lambda match: "[" + ", ".join(re.findall(
                    r'\["\d{4}", "\d{4}"\]', match.group(0))) + "]",
                formatted)
        with open(path, "w", encoding="utf-8") as f:
            f.write(formatted + "\n")
        return True
    except OSError:
        return False


# ---------- restaurants (flat file) ----------

def load_restaurants(path=config.RESTAURANT_FILE):
    """Load all records on startup. Missing or corrupt file -> empty list."""
    data = _load_json(path)
    return data if isinstance(data, list) else []


def _restaurant_record(candidate):
    """Map a live candidate to the restaurant file's public fact fields."""
    place_id = candidate.get("google_place_id")
    if not isinstance(place_id, str) or not place_id or not candidate.get("name"):
        return None
    dietary = {
        item for item in candidate.get("dietary_requirements") or []
        if item in ("halal", "vegetarian")
    }
    if candidate.get("halal_hint"):
        dietary.add("halal")
    address = candidate.get("address")
    postal = candidate.get("postal_code")
    if not postal and isinstance(address, str):
        match = re.search(r"\bSingapore\s+(\d{6})\b", address, re.IGNORECASE)
        postal = match.group(1) if match else None
    cuisines = candidate.get("cuisines") or []
    rating = candidate.get("rating")
    reviews = candidate.get("rating_count")
    wheelchair = candidate.get("wheelchair_accessible")
    muis_check = candidate.get("muis_check")
    officially_verified = (
        candidate.get("halal_certification") == "official"
        and isinstance(muis_check, dict)
        and muis_check.get("status") == "verified")
    return {
        "google_place_id": place_id,
        "name": candidate["name"],
        "postal_code": postal,
        "address": address if address != "unavailable" else None,
        "number": candidate.get("number"),
        "g_rating": str(rating) if type(rating) in (int, float) else None,
        "g_no_reviews": str(reviews) if type(reviews) is int else None,
        "cuisine": cuisines[0] if cuisines and cuisines[0] != "unknown" else None,
        "dietary": sorted(dietary),
        "avg_price_low_sgd": candidate.get("price_start"),
        "avg_price_high_sgd": candidate.get("price_end"),
        "opening_hours": candidate.get("opening_hours"),
        "wheelchair_accessible": wheelchair if type(wheelchair) is bool else None,
        "halal_certification": (
            "official" if officially_verified
            else "unofficial" if "halal" in dietary else "none"),
    }


def save_restaurants(candidates, path=config.RESTAURANT_FILE):
    """Upsert all searched live restaurants by Google place ID."""
    restaurants = load_restaurants(path)
    by_id = {
        row.get("google_place_id"): index
        for index, row in enumerate(restaurants)
        if isinstance(row, dict) and row.get("google_place_id")
    }
    changed = False
    saved = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        record = _restaurant_record(candidate)
        if record is None:
            continue
        place_id = record["google_place_id"]
        if place_id in by_id:
            index = by_id[place_id]
            old = restaurants[index]
            record = {key: old.get(key) if value is None else value
                      for key, value in record.items()}
            if restaurants[index] != record:
                restaurants[index] = record
                changed = True
        else:
            by_id[place_id] = len(restaurants)
            restaurants.append(record)
            changed = True
        saved += 1
    if changed and not _save_json(path, restaurants, compact_hours=True):
        return None
    return saved


# ---------- search history ----------

def load_history(path=config.HISTORY_FILE):
    data = _load_json(path)
    return data if isinstance(data, list) else []


def save_history(entry, path=config.HISTORY_FILE):
    history = load_history(path)
    history.append(entry)
    return _save_json(path, history)


def save_search_results(request, results, source):
    """Keep only validated search facts in the history file."""
    origin = request["origin"]
    entry = {
        "mode": source,
        "origin": [origin["latitude"], origin["longitude"]],
        "travel_mode": request["mode"],
        "cuisine": request["cuisine"],
    }
    if source == "live-google":
        entry["top_match_place_ids"] = [
            item["restaurant"]["google_place_id"] for item in results["matches"]
            if item["restaurant"].get("google_place_id")]
    else:
        entry["top_matches"] = [
            item["restaurant"]["name"] for item in results["matches"]]
    return save_history(entry)
