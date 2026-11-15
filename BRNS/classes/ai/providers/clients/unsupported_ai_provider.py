"""Compatibility adapter for an unsupported BRNS provider entry."""

from BRNS.classes.ai.providers.contracts.ai_provider_interface import AIProviderInterface
from BRNS.classes.ai.providers.contracts.base_ai_provider import BaseAIProvider


class UnsupportedAIProvider(BaseAIProvider, AIProviderInterface):
    """Return the legacy failure result for an unknown provider name."""

    def __init__(self, provider_name, model):
        super().__init__(provider_name, model, lambda *_args: None)

    def request(self, system_prompt, user_text):
        del system_prompt, user_text
        return False, f"unknown provider '{self._provider_name}'"
