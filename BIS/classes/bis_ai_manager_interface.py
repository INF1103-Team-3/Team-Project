"""Focused contract for BIS AI Manager operations."""

from abc import ABC, abstractmethod


class BISAIManagerInterface(ABC):
    """Can interpret profile actions and search requests."""

    @abstractmethod
    def process(self, record, config):
        """Interpret one profile command."""

    @abstractmethod
    def interpret_search_request(self, request, today_request, config):
        """Interpret one confirmed search request."""
