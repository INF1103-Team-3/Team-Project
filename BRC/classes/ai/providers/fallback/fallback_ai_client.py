"""Production BRC AI client backed by the configured provider router."""

from BRC.classes.ai.providers.contracts.ai_client_interface import AIClientInterface
from BRC.classes.ai.providers.fallback.ai_provider_router import AIProviderRouter


class FallbackAIClient(AIClientInterface):
    """Route BRC prompts across providers, including schema failures."""

    def __init__(self, settings, gemini_call, chat_completions_call):
        self._settings = settings
        self._router = AIProviderRouter(
            gemini_call, chat_completions_call, cooldown_seconds=120)

    def set_reporter(self, report):
        self._settings["report"] = report

    def call_api(self, prompt):
        return self._router.request(prompt, self._settings)

    def request_validated(self, prompt, read_answer):
        validated = {}

        def validator(raw):
            try:
                validated["result"] = read_answer(raw)
            except (ValueError, TypeError, AttributeError):
                return False
            return True

        self._router.request(prompt, self._settings, validator)
        return validated["result"]
