"""BRNS Data Manager: restaurant and recommendation-history persistence."""

from BRNS.classes.data.contracts.brns_data_manager_interface import BRNSDataManagerInterface


class DataManager(BRNSDataManagerInterface):
    """Coordinate BRNS persistence through an injected record store."""

    def __init__(self, store):
        self._store = store

    def load_candidate_records(self, path=None):
        return self._store.load_candidate_records(path)

    def load_restaurants(self, path=None):
        return self._store.load_restaurants(path)

    def save_restaurants(self, candidates, path=None):
        return self._store.save_restaurants(candidates, path)

    def load_history(self, path=None):
        return self._store.load_history(path)

    def save_history(self, entry, path=None):
        return self._store.save_history(entry, path)

    def save_search_results(self, request, results, source):
        return self._store.save_search_results(request, results, source)

    def save(self, record):
        return self._store.save(record)

    def load(self):
        return self._store.load()

    def query(self, filter_fn):
        return self._store.query(filter_fn)

    def load_user_history(self, user_id):
        return self._store.load_user_history(user_id)

    def clear_user_history(self, user_id):
        return self._store.clear_user_history(user_id)
