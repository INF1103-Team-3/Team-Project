"""SiliconFlow implementation of the BIS AI provider contract."""

from BIS.classes.ai.providers.contracts.ai_provider_interface import (
    AIProviderInterface,
)
from BIS.classes.ai.providers.contracts.base_ai_provider import BaseAIProvider


class SiliconFlowAIProvider(BaseAIProvider, AIProviderInterface):
    """Request structured model output directly from SiliconFlow."""

    def __init__(self, model, request_callable):
        super().__init__("siliconflow", model, request_callable)

    def request(self, payload, config):
        return self._send(payload, config)
