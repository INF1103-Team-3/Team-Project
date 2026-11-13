"""Capability contract for BRC AI clients."""

from abc import ABC, abstractmethod


class AIClientInterface(ABC):
    """A client that can send one prompt and return response text."""

    @abstractmethod
    def call_api(self, prompt):
        """Return provider response text or raise a documented AI error."""

    def request_validated(self, prompt, read_answer):
        """Retry a malformed reply once; routers may specialize provider fallback."""
        from BRC.classes.ai.errors.ai_response_error import AIResponseError
        try:
            return read_answer(self.call_api(prompt))
        except AIResponseError:
            return read_answer(self.call_api(prompt))

    def set_reporter(self, report):
        """Optionally receive a callback for non-user-facing status events."""
