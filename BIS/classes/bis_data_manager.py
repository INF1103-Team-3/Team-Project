"""Object boundary for BIS account and state persistence."""

from BIS.classes.bis_data_manager_interface import BISDataManagerInterface


class BISDataManager(BISDataManagerInterface):
    """Expose the persistence operations required by a BIS session."""

    def __init__(self, manager_module):
        self._manager = manager_module

    def save(self, record):
        return self._manager.save(record)

    def save_preferences(self, user_id, preferences, config):
        return self._manager.save_preferences(user_id, preferences, config)

    def get_state(self, section, user_id):
        return self._manager.get_state(section, user_id)

    def set_state(self, section, user_id, value):
        return self._manager.set_state(section, user_id, value)

    def serialize_search_request(self, request):
        return self._manager.serialize_search_request(request)
