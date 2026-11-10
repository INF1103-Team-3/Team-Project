"""Capability contract for validating the BIS-to-BRNS search request."""

from abc import ABC, abstractmethod


class SearchRequestValidatorInterface(ABC):
    """A component that can validate a confirmed search request."""

    @abstractmethod
    def validate(self, request, ai_response=None):
        """Validate a request and optional AI interpretation."""
