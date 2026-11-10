"""BRNS AI Manager: provider availability and recommendation requests."""

from BRNS.classes.brns_ai_manager_interface import BRNSAIManagerInterface


class AIManager(BRNSAIManagerInterface):
    """Own BRNS AI requests using an injected recommendation engine."""

    def __init__(self, config, recommendation_runner, deadline_scope):
        self._config = config
        self._recommend = recommendation_runner
        self._deadline_scope = deadline_scope

    def has_configured_provider(self):
        return any(
            (
                entry.get("provider") == "openrouter"
                and self._config.OPENROUTER_API_KEY
                or entry.get("provider") == "gemini"
                and self._config.GEMINI_API_KEY
                or entry.get("provider") == "groq"
                and self._config.GROQ_API_KEY
            )
            and entry.get("model")
            and not any(char in entry["model"] for char in "<> ")
            for entry in self._config.MODEL_CHAIN)

    def recommend_candidates(
            self, request, candidates, previous_restaurants=()):
        with self._deadline_scope(
                self._config.AI_CHAIN_TIMEOUT_SECONDS):
            return self._recommend(
                request, candidates, previous_restaurants)
