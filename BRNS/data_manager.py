"""Compatibility façade for the object-oriented BRNS Data Manager."""

import os
from BRNS import config
from BRNS.classes.data.helpers.search_history_scope import SearchHistoryScope
from BRNS.classes.data.data_manager import DataManager
from BRNS.classes.data.stores.json.json_recommendation_store import JsonRecommendationStore


history_scope = SearchHistoryScope()
_BACKEND = os.getenv("BITEFINDER_STORAGE", "json").strip().lower()
if _BACKEND == "json":
    _STORE = JsonRecommendationStore(config.RESTAURANT_FILE, config.HISTORY_FILE)
elif _BACKEND == "mongo":
    from common.storage_dependencies import mongo_connection
    from BRNS.classes.data.stores.mongo.mongo_recommendation_store import MongoRecommendationStore
    _STORE = MongoRecommendationStore(mongo_connection(), history_scope)
    _STORE.ensure_indexes()
else:
    raise ValueError("BITEFINDER_STORAGE must be json or mongo.")
_MANAGER = DataManager(_STORE)


def manager():
    return _MANAGER


def _load_json(path):
    return _STORE._load_json(path)


def _save_json(path, data, *, compact_hours=False):
    return _STORE._save_json(path, data, compact_hours=compact_hours)


def load_restaurants(path=None):
    return _MANAGER.load_restaurants(path)


def _restaurant_record(candidate):
    return _STORE.restaurant_record(candidate)


def save_restaurants(candidates, path=None):
    return _MANAGER.save_restaurants(candidates, path)


def load_history(path=None):
    return _MANAGER.load_history(path)


def save_history(entry, path=None):
    return _MANAGER.save_history(entry, path)


def save_search_results(request, results, source):
    return _MANAGER.save_search_results(request, results, source)


def save(record):
    return _MANAGER.save(record)


def load():
    return _MANAGER.load()


def query(filter_fn):
    return _MANAGER.query(filter_fn)
