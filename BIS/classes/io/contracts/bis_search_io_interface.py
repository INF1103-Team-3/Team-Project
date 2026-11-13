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

    @abstractmethod
    def display_results(self, results, announce_no_matches=True):
        """Display ranked recommendation cards without collecting input."""

    @abstractmethod
    def display_result_list(self, results):
        """Show a compact numbered summary of ranked restaurants."""

    @abstractmethod
    def display_no_matches(self, results):
        """Explain why the leading alternative is not a verified match."""

    @abstractmethod
    def display_route(self, name, route, link, mode, traffic_aware=False):
        """Print step-by-step route guidance and Maps link."""
