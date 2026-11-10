"""Object boundary for BRNS restaurant and history persistence."""

from BRNS.classes.brns_data_manager_interface import BRNSDataManagerInterface


class BRNSDataManager(BRNSDataManagerInterface):
    """Expose persistence operations required by recommendation searches."""

    def __init__(self, manager_module):
        self._manager = manager_module

    def save_restaurants(self, candidates):
        return self._manager.save_restaurants(candidates)

    def save_search_results(self, request, results, source):
        return self._manager.save_search_results(request, results, source)
