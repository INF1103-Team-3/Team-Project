"""BRNS AI Manager: provider availability and recommendation requests."""

from BRNS.classes.ai.contracts.brns_ai_manager_interface import BRNSAIManagerInterface


class AIManager(BRNSAIManagerInterface):
    """Own BRNS AI requests using an injected recommendation engine."""

    def __init__(self, config, recommendation_runner, deadline_scope, prepared_runner,
                 provider_registry):
        self._providers = provider_registry
        self._prepared = prepared_runner
        self._config = config
        self._recommend = recommendation_runner
        self._deadline_scope = deadline_scope

    def has_configured_provider(self):
        return any(
            self._providers.is_configured(entry.get("provider"), self._config)
            and entry.get("model")
            and not any(char in entry["model"] for char in "<> ")
            for entry in self._config.MODEL_CHAIN)

    def recommend_candidates(
            self, request, candidates, previous_restaurants=()):
        with self._deadline_scope(
                self._config.AI_CHAIN_TIMEOUT_SECONDS):
            return self._recommend(
                request, candidates, previous_restaurants)

    def recommend_prepared(self, context, candidate_count):
        with self._deadline_scope(self._config.AI_CHAIN_TIMEOUT_SECONDS):
            return self._prepared(context, candidate_count)
