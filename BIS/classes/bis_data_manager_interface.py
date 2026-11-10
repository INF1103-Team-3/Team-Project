"""Focused contract for BIS Data Manager operations."""

from abc import ABC, abstractmethod


class BISDataManagerInterface(ABC):
    """Can persist accounts, preferences and BIS workflow state."""

    @abstractmethod
    def save(self, record):
        """Persist one user record."""

    @abstractmethod
    def save_preferences(self, user_id, preferences, config):
        """Persist one user's preferences."""

    @abstractmethod
    def get_state(self, section, user_id):
        """Load one workflow-state value."""

    @abstractmethod
    def set_state(self, section, user_id, value):
        """Persist one workflow-state value."""

    @abstractmethod
    def serialize_search_request(self, request):
        """Return the existing BRNS-compatible JSON payload."""
