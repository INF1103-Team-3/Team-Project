"""Compatibility façade for the object-oriented BIS Data Manager."""

import os
from pathlib import Path

from BIS import logic_manager
from BIS.classes.data_manager import DataManager
from BIS.classes.json_user_store import JsonUserStore
from BIS.classes.location_gateway import LocationGateway
from shared import geocode_cache


DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "profile_state.json"
GEOCODE_URL = os.getenv(
    "BITEFINDER_GEOCODE_URL",
    "https://maps.googleapis.com/maps/api/geocode/json",
)

_BACKEND = os.getenv("BITEFINDER_STORAGE", "json").strip().lower()
if _BACKEND == "json":
    _STORE = JsonUserStore(USERS_FILE, STATE_FILE)
elif _BACKEND == "mongo":
    from BIS.storage_dependencies import mongo_connection
    from BIS.classes.mongo_user_store import MongoUserStore
    _STORE = MongoUserStore(mongo_connection())
    _STORE.ensure_indexes()
else:
    raise ValueError("BITEFINDER_STORAGE must be json or mongo.")
_LOCATION_GATEWAY = LocationGateway(
    logic_manager, geocode_cache, GEOCODE_URL)
_MANAGER = DataManager(_STORE, _LOCATION_GATEWAY)
LAST_ERROR = None


def manager():
    """Return the configured BIS Data Manager used by compatibility calls."""
    return _MANAGER


def serialize_search_request(request):
    return _MANAGER.serialize_search_request(request)


def _read_json(path):
    return _STORE._read_json(path)


def _registry():
    return _STORE.registry()


def load():
    global LAST_ERROR
    records = _MANAGER.load()
    LAST_ERROR = _MANAGER.last_error
    return records


def query(filter_fn):
    return _MANAGER.query(filter_fn)


def _atomic_write(path, value):
    return _STORE._atomic_write(path, value)


def save(record):
    return _MANAGER.save(record)


def register_user(email, username):
    return _MANAGER.register_user(email, username)


def email_exists(email):
    return _MANAGER.email_exists(email)


def find_user(email):
    return _MANAGER.find_user(email)


def get_user(user_id):
    return _MANAGER.get_user(user_id)


def save_preferences(user_id, preferences, config):
    return _MANAGER.save_preferences(user_id, preferences, config)


def get_state(section, user_id):
    return _MANAGER.get_state(section, user_id)


def set_state(section, user_id, value):
    return _MANAGER.set_state(section, user_id, value)


def lookup_cached_location(query):
    return _MANAGER.lookup_cached_location(query)


def resolve_location(query, api_key):
    return _MANAGER.resolve_location(query, api_key)


def remember_location(queries, location):
    return _MANAGER.remember_location(queries, location)
