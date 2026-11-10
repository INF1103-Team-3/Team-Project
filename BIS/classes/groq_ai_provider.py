"""Groq implementation of the BIS AI provider contract."""

from BIS.classes.ai_provider_interface import AIProviderInterface
from BIS.classes.base_ai_provider import BaseAIProvider


class GroqAIProvider(BaseAIProvider, AIProviderInterface):
    """Request structured model output directly from Groq."""

    def __init__(self, model, request_callable):
        super().__init__("groq", model, request_callable)

    def request(self, payload, config):
        return self._send(payload, config)
