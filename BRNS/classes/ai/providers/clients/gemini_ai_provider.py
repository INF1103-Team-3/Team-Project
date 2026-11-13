"""Gemini implementation of the BRNS AI provider contract."""

from BRNS.classes.ai.providers.contracts.ai_provider_interface import AIProviderInterface
from BRNS.classes.ai.providers.contracts.base_ai_provider import BaseAIProvider


class GeminiAIProvider(BaseAIProvider, AIProviderInterface):
    """Request BRNS model output directly from Gemini."""

    def __init__(self, model, request_callable):
        super().__init__("gemini", model, request_callable)

    def request(self, system_prompt, user_text):
        return self._send(system_prompt, user_text)
