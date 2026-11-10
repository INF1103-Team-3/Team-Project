"""Mongo restaurant/history persistence with JSON-compatible domain records."""
from datetime import datetime, timezone
from uuid import uuid4
from BRNS.classes.record_store_interface import RecordStoreInterface
from BRNS.classes.recommendation_record_mapper import RecommendationRecordMapper


class MongoRecommendationStore(RecordStoreInterface):
    def __init__(self, connection, history_scope):
        self._connection, self._scope = connection, history_scope

    @staticmethod
    def _check_path(path):
        if path is not None:
            raise ValueError("JSON path overrides are unavailable in Mongo mode.")

    def ensure_indexes(self):
        self._connection.execute(lambda db: db.search_history.create_index(
            [("user_id", 1), ("timestamp", -1)]))

    def load_restaurants(self, path=None):
        self._check_path(path)
        return self._connection.execute(lambda db: list(db.restaurants.find({}, {"_id": 0})))

    def load_candidate_records(self, path=None):
        self._check_path(path)
        return [r for r in self.load_restaurants() if r.get("name")]

    def save_restaurants(self, candidates, path=None):
        self._check_path(path)
        saved = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            record = RecommendationRecordMapper.restaurant_record(candidate)
            if record is None:
                continue
            key = record["google_place_id"]
            old = self._connection.execute(lambda db: db.restaurants.find_one({"_id": key})) or {}
            record = {k: old.get(k) if v is None else v for k, v in record.items()}
            self._connection.execute(lambda db: db.restaurants.replace_one(
                {"_id": key}, dict(record, _id=key), upsert=True))
            saved += 1
        return saved

    def load_history(self, path=None):
        self._check_path(path)
        return self._connection.execute(lambda db: list(db.search_history.find({}, {"_id": 0})))

    def save_history(self, entry, path=None):
        self._check_path(path)
        self._connection.execute(lambda db: db.search_history.insert_one(dict(entry, _id=str(uuid4()))))
        return True

    def save_search_results(self, request, results, source):
        entry = RecommendationRecordMapper.search_summary(request, results, source)
        entry.update(user_id=self._scope.get(), timestamp=datetime.now(timezone.utc).isoformat(),
                     request=request, matches_count=len(results["matches"]),
                     alternatives_count=len(results["alternatives"]))
        return self.save_history(entry)

    def load_user_history(self, user_id):
        return self._connection.execute(lambda db: list(db.search_history.find(
            {"user_id": user_id}).sort("timestamp", -1).limit(20)))

    def clear_user_history(self, user_id):
        return self._connection.execute(lambda db: db.search_history.delete_many({"user_id": user_id})).deleted_count

    def save(self, record):
        if not isinstance(record, dict):
            raise ValueError("Saved BRNS records must be dictionaries.")
        return self.save_history(record)

    def load(self):
        return self.load_history()

    def query(self, filter_fn):
        return [record for record in self.load() if filter_fn(record)]
