"""BIS Logic Manager object with composed search validation."""

from BIS.classes.search_request_validator import (
    create_search_request_validator,
)
from BIS.classes.bis_logic_manager_interface import BISLogicManagerInterface


class BISLogicManager(BISLogicManagerInterface):
    """Own BIS validation collaborators while preserving public contracts."""

    def __init__(self, search_validator=None, manager_module=None):
        self.__search_validator = (
            search_validator or create_search_request_validator()
        )
        self._manager = manager_module

    @property
    def search_validator(self):
        """Expose the validator contract for manager-level collaboration."""
        return self.__search_validator

    def validate_search_request(self, request, ai_response=None):
        return self.__search_validator.validate(request, ai_response)

    def next_field(self, preferences):
        return self._manager.next_field(preferences)

    def apply_updates(self, preferences, updates, location_action="add"):
        return self._manager.apply_updates(
            preferences, updates, location_action)

    def is_search_clarification(self, error):
        return self._manager.is_search_clarification(error)

    def clarification_message(self, error):
        return self._manager.clarification_message(error)
