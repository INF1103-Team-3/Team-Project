"""Shared identity and callable ownership for BRNS AI providers."""

from abc import ABC, abstractmethod


class BaseAIProvider(ABC):
    """Base provider carrying common model identity and request state."""

    def __init__(self, provider_name, model, request_callable):
        self._provider_name = provider_name
        self._model = model
        self.__request_callable = request_callable

    @property
    def label(self):
        return f"{self._provider_name}/{self._model}"

    def _send(self, system_prompt, user_text):
        return self.__request_callable(system_prompt, user_text)

    @abstractmethod
    def request(self, system_prompt, user_text):
        """Send one provider-specific request."""
