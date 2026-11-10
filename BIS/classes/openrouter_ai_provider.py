"""OpenRouter implementation of the BIS AI provider contract."""

from BIS.classes.ai_provider_interface import AIProviderInterface
from BIS.classes.base_ai_provider import BaseAIProvider


class OpenRouterAIProvider(BaseAIProvider, AIProviderInterface):
    """Request structured model output through OpenRouter."""

    def __init__(
            self, model, request_callable, primary=False,
            include_model=True):
        super().__init__(
            "openrouter", model, request_callable, primary=primary)
        self._include_model = include_model

    def request(self, payload, config):
        request_payload = (
            dict(payload, model=self._model)
            if self._include_model else payload
        )
        return self._send(request_payload, config)
