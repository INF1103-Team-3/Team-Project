"""NVIDIA NIM implementation of the BIS AI provider contract."""

from BIS.classes.ai.providers.contracts.ai_provider_interface import (
    AIProviderInterface,
)
from BIS.classes.ai.providers.contracts.base_ai_provider import BaseAIProvider


class NvidiaAIProvider(BaseAIProvider, AIProviderInterface):
    """Request structured model output directly from NVIDIA NIM."""

    def __init__(self, model, request_callable):
        super().__init__("nvidia", model, request_callable)

    def request(self, payload, config):
        return self._send(payload, config)
