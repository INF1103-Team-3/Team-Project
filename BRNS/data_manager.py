"""Store searched BRNS restaurants and approved search history."""
import json
import os
import re
from BRNS import config
from BRNS.classes.json_recommendation_store import JsonRecommendationStore
from shared.debug_log import debug_log


_STORE = JsonRecommendationStore(config.RESTAURANT_FILE, config.HISTORY_FILE)


# ---------- generic helpers ----------

def _load_json(path):
    return _STORE._load_json(path)


def _save_json(path, data, *, compact_hours=False):
    return _STORE._save_json(path, data, compact_hours=compact_hours)


# ---------- restaurants (flat file) ----------

def load_restaurants(path=config.RESTAURANT_FILE):
    """Load all records on startup. Missing or corrupt file -> empty list."""
    return _STORE.load_restaurants(path)


def _restaurant_record(candidate):
    """Map a live candidate to the restaurant file's public fact fields."""
    return _STORE.restaurant_record(candidate)


def save_restaurants(candidates, path=config.RESTAURANT_FILE):
    """Upsert all searched live restaurants by Google place ID."""
    return _STORE.save_restaurants(candidates, path)


# ---------- search history ----------

def load_history(path=config.HISTORY_FILE):
    return _STORE.load_history(path)


def save_history(entry, path=config.HISTORY_FILE):
    return _STORE.save_history(entry, path)


def save_search_results(request, results, source):
    """Keep only validated search facts in the history file."""
    return _STORE.save_search_results(request, results, source)


def save(record):
    """Append one evaluated search-history record."""
    return _STORE.save(record)


def load():
    """Load persisted BRNS search records, returning [] on file errors."""
    return _STORE.load()


def query(filter_fn):
    """Return persisted BRNS records accepted by a caller filter."""
    return _STORE.query(filter_fn)
