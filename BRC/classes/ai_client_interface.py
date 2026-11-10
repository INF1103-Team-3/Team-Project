"""Capability contract for BRC AI clients."""

from abc import ABC, abstractmethod


class AIClientInterface(ABC):
    """A client that can send one prompt and return response text."""

    @abstractmethod
    def call_api(self, prompt):
        """Return provider response text or raise a documented AI error."""

    def set_reporter(self, report):
        """Optionally receive a callback for non-user-facing status events."""
