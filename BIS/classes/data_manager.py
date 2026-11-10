"""BIS Data Manager: account, session-state, and location persistence."""

import json

from BIS.classes.bis_data_manager_interface import BISDataManagerInterface


class DataManager(BISDataManagerInterface):
    """Coordinate BIS repositories without owning UI or business rules."""

    def __init__(self, user_store, location_gateway, sessions=None, favorites=None, credentials=None, proposals=None):
        self._proposals = proposals
        self._sessions, self._favorites, self._credentials = sessions, favorites, credentials
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

    def get_credentials(self, user_id):
        return self._credentials.get(user_id)

    def save_credentials(self, user_id, credential):
        return self._credentials.save(user_id, credential)

    def issue_session(self, user_id):
        return self._sessions.create(user_id)

    def resolve_session(self, token):
        return self._sessions.resolve(token)

    def revoke_session(self, token):
        return self._sessions.revoke(token)

    def load_favorites(self, user_id):
        return self._favorites.load(user_id)

    def save_favorite(self, user_id, key, restaurant):
        return self._favorites.set(user_id, key, restaurant)

    def delete_favorite(self, user_id, key):
        return self._favorites.delete(user_id, key)

    def create_search_proposal(self, owner, request):
        return self._proposals.create(owner, request)

    def consume_search_proposal(self, owner, token):
        return self._proposals.consume(owner, token)
