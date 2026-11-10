"""Capability contract for external restaurant verification."""

from abc import ABC, abstractmethod


class RestaurantVerificationInterface(ABC):
    """An external service that can verify restaurant evidence."""

    @abstractmethod
    def database_missing(self):
        """Return whether the verifier's local evidence is unavailable."""

    @abstractmethod
    def verify(self, restaurant):
        """Return the verifier's checked restaurant record."""
