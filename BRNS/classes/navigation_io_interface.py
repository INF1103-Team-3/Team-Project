"""Focused BRNS route-IO capability contract."""

from abc import ABC, abstractmethod


class NavigationIOInterface(ABC):
    """Can obtain route details and construct a Maps link."""

    @abstractmethod
    def get_route(self, *args, **kwargs):
        """Return route information for two coordinates."""

    @abstractmethod
    def build_maps_link(self, *args, **kwargs):
        """Return a Google Maps directions link."""
