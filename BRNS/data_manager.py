"""Compatibility façade for the object-oriented BRNS Data Manager."""

from BRNS import config
from BRNS.classes.data_manager import DataManager
from BRNS.classes.json_recommendation_store import JsonRecommendationStore


_STORE = JsonRecommendationStore(
    config.RESTAURANT_FILE, config.HISTORY_FILE)
_MANAGER = DataManager(_STORE)


def manager():
    return _MANAGER


def _load_json(path):
    return _STORE._load_json(path)


def _save_json(path, data, *, compact_hours=False):
    return _STORE._save_json(path, data, compact_hours=compact_hours)


def load_restaurants(path=config.RESTAURANT_FILE):
    return _MANAGER.load_restaurants(path)


def _restaurant_record(candidate):
    return _STORE.restaurant_record(candidate)


def save_restaurants(candidates, path=config.RESTAURANT_FILE):
    return _MANAGER.save_restaurants(candidates, path)


def load_history(path=config.HISTORY_FILE):
    return _MANAGER.load_history(path)


def save_history(entry, path=config.HISTORY_FILE):
    return _MANAGER.save_history(entry, path)


def save_search_results(request, results, source):
    return _MANAGER.save_search_results(request, results, source)


def save(record):
    return _MANAGER.save(record)


def load():
    return _MANAGER.load()


def query(filter_fn):
    return _MANAGER.query(filter_fn)
