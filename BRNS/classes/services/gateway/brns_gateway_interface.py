"""Focused gateway contract exposing BRNS search, routing, history, and model status."""

from abc import ABC, abstractmethod


class BRNSGatewayInterface(ABC):
    """Single downstream boundary called by BIS to execute BRNS capabilities."""

    @abstractmethod
    def search(
        self,
        bis_json,
        previous_restaurants=(),
        user_id=None,
        max_matches=None,
        max_alternatives=None,
    ):
        """Run recommendation search for one validated BIS request."""

    @abstractmethod
    def route_to(self, restaurant, request):
        """Return navigation directions and map link for one selected restaurant."""

    @abstractmethod
    def sort_results(self, results, sort_by):
        """Sort a BRNS result set by rating or travel distance."""

    @abstractmethod
    def maps_link(self, origin, destination, mode):
        """Build a Google Maps directions URL for BIS presentation."""

    @abstractmethod
    def load_history(self, user_id):
        """Return persisted search history rows for one BIS user."""

    @abstractmethod
    def save_history_summary(self, user_id, request, results, source="live-google"):
        """Persist one summary search-history record for a BIS user."""

    @abstractmethod
    def clear_history(self, user_id):
        """Delete persisted search history rows for one BIS user."""

    @abstractmethod
    def active_model(self):
        """Return the currently configured or active BRNS AI model."""

    @abstractmethod
    def last_used_model(self):
        """Return the model used for the latest BRNS call, if any."""
