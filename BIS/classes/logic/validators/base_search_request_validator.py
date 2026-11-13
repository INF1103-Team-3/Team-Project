"""Shared state and behavior for BIS search-request validators."""

from abc import ABC, abstractmethod

from sources.profile_schema import OTHER_PREFERENCES


class BaseSearchRequestValidator(ABC):
    """Base validator that protects choices already confirmed by the user."""

    def __init__(self, search_fields, supported_cuisines):
        self._search_fields = frozenset(search_fields)
        self.__supported_cuisines = tuple(supported_cuisines)

    @property
    def supported_cuisines(self):
        """Return the immutable cuisine vocabulary used by validation."""
        return self.__supported_cuisines

    def _protect_confirmed_choices(self, confirmed, proposed):
        protected = self._search_fields - {OTHER_PREFERENCES}
        if any(proposed[field] != confirmed[field] for field in protected):
            raise ValueError(
                "SEARCH_CLARIFICATION: The AI interpretation conflicts with "
                "a confirmed choice. Please clarify what you want today."
            )
        if not set(confirmed[OTHER_PREFERENCES]).issubset(
                proposed[OTHER_PREFERENCES]):
            raise ValueError(
                "SEARCH_CLARIFICATION: The AI removed a selected preference. "
                "Please clarify your request."
            )

    @abstractmethod
    def validate(self, request, ai_response=None):
        """Return the normalized ten-field search contract."""
