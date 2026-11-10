"""Gemini implementation of the BIS AI provider contract."""

from BIS.classes.ai_provider_interface import AIProviderInterface
from BIS.classes.base_ai_provider import BaseAIProvider


class GeminiAIProvider(BaseAIProvider, AIProviderInterface):
    """Request structured model output directly from Gemini."""

    def __init__(self, model, request_callable):
        super().__init__("gemini", model, request_callable)

    def request(self, payload, config):
        return self._send(payload, config)
