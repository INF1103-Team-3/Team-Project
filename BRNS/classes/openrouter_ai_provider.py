"""OpenRouter implementation of the BRNS AI provider contract."""

from BRNS.classes.ai_provider_interface import AIProviderInterface
from BRNS.classes.base_ai_provider import BaseAIProvider


class OpenRouterAIProvider(BaseAIProvider, AIProviderInterface):
    """Request BRNS model output through OpenRouter."""

    def __init__(self, model, request_callable):
        super().__init__("openrouter", model, request_callable)

    def request(self, system_prompt, user_text):
        return self._send(system_prompt, user_text)
