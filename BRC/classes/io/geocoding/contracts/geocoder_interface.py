"""Capability contract for BRC geocoders."""

from abc import ABC, abstractmethod


class GeocoderInterface(ABC):
    """A collaborator able to add coordinates to MUIS listings."""

    adds_coordinates = True

    @abstractmethod
    def geocode(self, listings):
        """Return listings with coordinates where available."""
