"""BIS Data Manager: account, session-state, and location persistence."""

import json

from BIS.classes.bis_data_manager_interface import BISDataManagerInterface


class DataManager(BISDataManagerInterface):
    """Coordinate BIS repositories without owning UI or business rules."""

    def __init__(self, user_store, location_gateway):
        self._user_store = user_store
        self._location_gateway = location_gateway

    @property
    def last_error(self):
        return self._user_store.last_error

    def serialize_search_request(self, request):
        return json.dumps(
            request, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"))

    def load(self):
        return self._user_store.load()

    def query(self, filter_fn):
        return self._user_store.query(filter_fn)

    def save(self, record):
        return self._user_store.save(record)

    def register_user(self, email, username):
        return self._user_store.register_user(email, username)

    def email_exists(self, email):
        return self._user_store.email_exists(email)

    def find_user(self, email):
        return self._user_store.find_user(email)

    def get_user(self, user_id):
        return self._user_store.get_user(user_id)

    def save_preferences(self, user_id, preferences, config):
        return self._user_store.save_preferences(
            user_id, preferences, config)

    def get_state(self, section, user_id):
        return self._user_store.get_state(section, user_id)

    def set_state(self, section, user_id, value):
        return self._user_store.set_state(section, user_id, value)

    def lookup_cached_location(self, query):
        return self._location_gateway.lookup_cached(query)

    def resolve_location(self, query, api_key):
        return self._location_gateway.resolve(query, api_key)

    def remember_location(self, queries, location):
        return self._location_gateway.remember(queries, location)
