"""Capability contract for a BIS AI model provider."""

from abc import ABC, abstractmethod


class AIProviderInterface(ABC):
    """A configured provider that can return model text for one payload."""

    @property
    @abstractmethod
    def label(self):
        """Return a non-secret provider/model identifier."""

    @property
    @abstractmethod
    def primary(self):
        """Whether this provider is the primary attempt in the fallback chain."""

    @abstractmethod
    def request(self, payload, config):
        """Return model response text or raise RuntimeError."""
