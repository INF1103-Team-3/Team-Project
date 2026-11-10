"""Account persistence and location data lookup. No terminal IO or AI."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from shared import geocode_cache
from BIS.classes.json_user_store import JsonUserStore
from BIS.classes.location_gateway import LocationGateway

import logic_manager
from shared.debug_log import debug_log
from sources.profile_schema import (
    MINUTES_PER_KM, empty_preferences, normalize_email,
    normalize_username, validate_user, validate_preferences,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "profile_state.json"
GEOCODE_URL = os.getenv(
    "BITEFINDER_GEOCODE_URL",
    "https://maps.googleapis.com/maps/api/geocode/json",
)
LAST_ERROR = None
_STORE = JsonUserStore(USERS_FILE, STATE_FILE)
_LOCATION_GATEWAY = LocationGateway(logic_manager, geocode_cache, GEOCODE_URL)


def serialize_search_request(request):
    """Produce the exact JSON object handed from BIS to BRNS IO."""
    return json.dumps(request, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _read_json(path):
    return _STORE._read_json(path)


def _registry():
    return _STORE.registry()


def load():
    """Return validated accounts, or [] if saved data cannot be read."""
    global LAST_ERROR
    records = _STORE.load()
    LAST_ERROR = _STORE.last_error
    return records


def query(filter_fn):
    return _STORE.query(filter_fn)


def _atomic_write(path, value):
    return _STORE._atomic_write(path, value)


def save(record):
    """Save one validated account, retaining every other account."""
    return _STORE.save(record)


def register_user(email, username):
    return _STORE.register_user(email, username)


def email_exists(email):
    return _STORE.email_exists(email)


def find_user(email):
    return _STORE.find_user(email)


def get_user(user_id):
    return _STORE.get_user(user_id)


def save_preferences(user_id, preferences, config):
    return _STORE.save_preferences(user_id, preferences, config)


def get_state(section, user_id):
    return _STORE.get_state(section, user_id)


def set_state(section, user_id, value):
    return _STORE.set_state(section, user_id, value)


def lookup_cached_location(query):
    return _LOCATION_GATEWAY.lookup_cached(query)


def resolve_location(query, api_key):
    """Retrieve an origin from coordinates, cache, or Google Geocoding."""
    return _LOCATION_GATEWAY.resolve(query, api_key)


def remember_location(queries, location):
    """Save aliases for a resolved location in the shared cache."""
    return _LOCATION_GATEWAY.remember(queries, location)
