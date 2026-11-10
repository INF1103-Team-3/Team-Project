"""Object boundary for the existing BIS AI Manager behavior."""

from BIS.classes.bis_ai_manager_interface import BISAIManagerInterface


class BISAIManager(BISAIManagerInterface):
    """Associate a BIS session with its AI-processing manager module."""

    def __init__(self, manager_module):
        self._manager = manager_module

    def process(self, record, config):
        return self._manager.process(record, config)

    def interpret_search_request(
            self, request, today_request, config):
        return self._manager.interpret_search_request(
            request, today_request, config)
