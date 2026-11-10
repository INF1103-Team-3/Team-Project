"""Focused contract for BRNS Data Manager operations."""

from abc import ABC, abstractmethod


class BRNSDataManagerInterface(ABC):
    """Can persist restaurant facts and recommendation history."""

    @abstractmethod
    def save_restaurants(self, candidates):
        """Persist normalized restaurant records."""

    @abstractmethod
    def save_search_results(self, request, results, source):
        """Persist one search summary."""
