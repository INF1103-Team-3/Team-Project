"""Focused contract for BIS search interaction."""

from abc import ABC, abstractmethod


class BISSearchIOInterface(ABC):
    """Can collect, confirm, refine and navigate a BIS search."""

    @abstractmethod
    def collect_search(self, user, config):
        """Collect one structured search request."""

    @abstractmethod
    def confirm_search_request(self, request, config=None):
        """Ask the user to confirm an interpreted request."""

    @abstractmethod
    def choose_results_action(self, *args, **kwargs):
        """Collect one result-list action."""
