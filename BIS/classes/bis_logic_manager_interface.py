"""Focused contract for BIS Logic Manager operations."""

from abc import ABC, abstractmethod


class BISLogicManagerInterface(ABC):
    """Can apply deterministic BIS validation and profile rules."""

    @abstractmethod
    def validate_search_request(self, request, ai_response=None):
        """Validate a confirmed or AI-proposed request."""

    @abstractmethod
    def next_field(self, preferences):
        """Return the next incomplete profile field."""

    @abstractmethod
    def apply_updates(self, preferences, updates, location_action="add"):
        """Apply validated profile updates without mutating the input."""
