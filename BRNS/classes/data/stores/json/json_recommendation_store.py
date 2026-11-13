"""JSON-backed restaurant facts and search-history persistence."""

import re
import json
from pathlib import Path

from BRNS.classes.data.stores.contracts.base_json_store import BaseJsonStore
from BRNS.classes.data.helpers.recommendation_record_mapper import RecommendationRecordMapper
from BRNS.classes.data.stores.contracts.record_store_interface import RecordStoreInterface


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
        return RecommendationRecordMapper.restaurant_record(candidate)
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
        return self.save_history(RecommendationRecordMapper.search_summary(request, results, source))
    def save(self, record):
        if not isinstance(record, dict):
            raise ValueError("Saved BRNS records must be dictionaries.")
        return self.save_history(record)

    def load(self):
        return self.load_history()

    def query(self, filter_fn):
        return [record for record in self.load() if filter_fn(record)]
