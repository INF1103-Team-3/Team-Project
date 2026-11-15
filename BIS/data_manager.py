"""Compatibility façade for the object-oriented BIS Data Manager."""

import os
from pathlib import Path

from BIS import logic_manager
from BIS.classes.data.data_manager import DataManager
from BIS.classes.data.stores.json.json_user_store import JsonUserStore
from common import geocode_cache


DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "profile_state.json"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"
GEOCODE_URL = os.getenv(
    "BITEFINDER_GEOCODE_URL",
    "https://maps.googleapis.com/maps/api/geocode/json",
)

_BACKEND = os.getenv("BITEFINDER_STORAGE", "json").strip().lower()
if _BACKEND == "json":
    from BIS.classes.data.stores.json.json_credential_store import (
        JsonCredentialStore,
    )

    _STORE = JsonUserStore(USERS_FILE, STATE_FILE)
    _CREDENTIALS = JsonCredentialStore(CREDENTIALS_FILE)
elif _BACKEND == "mongo":
    from common.storage_dependencies import mongo_connection
    from BIS.classes.data.stores.mongo.mongo_user_store import MongoUserStore
    from BIS.classes.data.stores.mongo.mongo_credential_store import (
        MongoCredentialStore,
    )

    _CONNECTION = mongo_connection()
    _STORE = MongoUserStore(_CONNECTION)
    _STORE.ensure_indexes()
    _CREDENTIALS = MongoCredentialStore(_CONNECTION)
else:
    raise ValueError("BITEFINDER_STORAGE must be json or mongo.")
_MANAGER = DataManager(_STORE, credentials=_CREDENTIALS)
LAST_ERROR = None


def manager():
    """Return the configured BIS Data Manager used by compatibility calls."""
    return _MANAGER


def serialize_search_request(request):
    return _MANAGER.serialize_search_request(request)


def _registry():
    return _STORE.registry()


def load():
    global LAST_ERROR
    records = _MANAGER.load()
    LAST_ERROR = _MANAGER.last_error
    return records


def query(filter_fn):
    return _MANAGER.query(filter_fn)


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


def get_credentials(user_id):
    return _MANAGER.get_credentials(user_id)


def save_credentials(user_id, credential):
    return _MANAGER.save_credentials(user_id, credential)


def save_preferences(user_id, preferences, config):
    preferences = logic_manager.manager().prepare_preferences_save(
        _MANAGER.get_user(user_id), preferences, config
    )
    return _MANAGER.save_preferences(user_id, preferences, config)


def get_state(section, user_id):
    return _MANAGER.get_state(section, user_id)


def set_state(section, user_id, value):
    return _MANAGER.set_state(section, user_id, value)
