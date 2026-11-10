"""JSON-backed restaurant facts and search-history persistence."""

import re
import json
from pathlib import Path

from BRNS.classes.base_json_store import BaseJsonStore
from BRNS.classes.record_store_interface import RecordStoreInterface


class JsonRecommendationStore(BaseJsonStore, RecordStoreInterface):
    """Preserve BRNS restaurant and history JSON formats."""

    def __init__(self, restaurant_path, history_path):
        super().__init__(history_path)
        self._restaurant_path = restaurant_path

    def load_restaurants(self, path=None):
        data = self._load_json(path or self._restaurant_path)
        return data if isinstance(data, list) else []

    def load_candidate_records(self, path=None):
        """Read raw candidate records with the legacy silent empty fallback."""
        try:
            data = json.loads(Path(self._restaurant_path if path is None else path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [row for row in data if isinstance(row, dict) and row.get("name")] if isinstance(data, list) else []

    @staticmethod
    def restaurant_record(candidate):
        place_id = candidate.get("google_place_id")
        if (not isinstance(place_id, str) or not place_id
                or not candidate.get("name")):
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
            match = re.search(
                r"\bSingapore\s+(\d{6})\b", address, re.IGNORECASE)
            postal = match.group(1) if match else None
        cuisines = candidate.get("cuisines") or []
        rating = candidate.get("rating")
        reviews = candidate.get("rating_count")
        wheelchair = candidate.get("wheelchair_accessible")
        muis_check = candidate.get("muis_check")
        officially_verified = (
            candidate.get("halal_certification") == "official"
            and isinstance(muis_check, dict)
            and muis_check.get("status") == "verified"
        )
        return {
            "google_place_id": place_id,
            "name": candidate["name"],
            "postal_code": postal,
            "address": address if address != "unavailable" else None,
            "number": candidate.get("number"),
            "g_rating": (
                str(rating) if type(rating) in (int, float) else None),
            "g_no_reviews": str(reviews) if type(reviews) is int else None,
            "cuisine": (
                cuisines[0]
                if cuisines and cuisines[0] != "unknown" else None),
            "dietary": sorted(dietary),
            "avg_price_low_sgd": candidate.get("price_start"),
            "avg_price_high_sgd": candidate.get("price_end"),
            "opening_hours": candidate.get("opening_hours"),
            "wheelchair_accessible": (
                wheelchair if type(wheelchair) is bool else None),
            "halal_certification": (
                "official" if officially_verified
                else "unofficial" if "halal" in dietary else "none"),
        }

    def save_restaurants(self, candidates, path=None):
        path = path or self._restaurant_path
        restaurants = self.load_restaurants(path)
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
            record = self.restaurant_record(candidate)
            if record is None:
                continue
            place_id = record["google_place_id"]
            if place_id in by_id:
                index = by_id[place_id]
                old = restaurants[index]
                record = {
                    key: old.get(key) if value is None else value
                    for key, value in record.items()
                }
                if restaurants[index] != record:
                    restaurants[index] = record
                    changed = True
            else:
                by_id[place_id] = len(restaurants)
                restaurants.append(record)
                changed = True
            saved += 1
        if changed and not self._save_json(
                path, restaurants, compact_hours=True):
            return None
        return saved

    def load_history(self, path=None):
        data = self._load_json(path or self._records_path)
        return data if isinstance(data, list) else []

    def save_history(self, entry, path=None):
        path = path or self._records_path
        history = self.load_history(path)
        history.append(entry)
        return self._save_json(path, history)

    def save_search_results(self, request, results, source):
        origin = request["origin"]
        entry = {
            "mode": source,
            "origin": [origin["latitude"], origin["longitude"]],
            "travel_mode": request["mode"],
            "cuisine": request["cuisine"],
        }
        if source == "live-google":
            entry["top_match_place_ids"] = [
                item["restaurant"]["google_place_id"]
                for item in results["matches"]
                if item["restaurant"].get("google_place_id")
            ]
        else:
            entry["top_matches"] = [
                item["restaurant"]["name"] for item in results["matches"]
            ]
        return self.save_history(entry)

    def save(self, record):
        if not isinstance(record, dict):
            raise ValueError("Saved BRNS records must be dictionaries.")
        return self.save_history(record)

    def load(self):
        return self.load_history()

    def query(self, filter_fn):
        return [record for record in self.load() if filter_fn(record)]
