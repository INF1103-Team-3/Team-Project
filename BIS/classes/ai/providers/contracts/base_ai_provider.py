"""Shared identity and callable ownership for BIS AI providers."""

from abc import ABC, abstractmethod


class BaseAIProvider(ABC):
    """Base provider carrying common model identity and request state."""

    def __init__(self, provider_name, model, request_callable, primary=False):
        self._provider_name = provider_name
        self._model = model
        self.__request_callable = request_callable
        self._primary = bool(primary)

    @property
    def label(self):
        return f"{self._provider_name}/{self._model}"

    @property
    def primary(self):
        return self._primary

    def _send(self, payload, config):
        return self.__request_callable(payload, config)

    @abstractmethod
    def request(self, payload, config):
        """Send one provider-specific request."""
