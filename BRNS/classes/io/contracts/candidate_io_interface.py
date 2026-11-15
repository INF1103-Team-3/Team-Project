"""Focused BRNS candidate-input capability contract."""

from abc import ABC, abstractmethod


class CandidateIOInterface(ABC):
    """Can validate BIS input and obtain restaurant candidates."""

    @abstractmethod
    def accept_bis_json(self, payload):
        """Validate and normalize a BIS search payload."""

    @abstractmethod
    def find_candidates(
        self, request, previous_restaurants=(), strict_exclude=False
    ):
        """Return candidate restaurants for a validated request."""
