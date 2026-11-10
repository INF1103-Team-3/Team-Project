"""Capability contract for a BRNS AI model provider."""

from abc import ABC, abstractmethod


class AIProviderInterface(ABC):
    """A configured provider that can return one BRNS model response."""

    @property
    @abstractmethod
    def label(self):
        """Return a non-secret provider/model identifier."""

    @abstractmethod
    def request(self, system_prompt, user_text):
        """Return ``(ok, content_or_error)`` for one request."""
