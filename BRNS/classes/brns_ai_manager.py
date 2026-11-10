"""Object boundary for BRNS AI recommendation behavior."""

from BRNS.classes.brns_ai_manager_interface import BRNSAIManagerInterface


class BRNSAIManager(BRNSAIManagerInterface):
    """Expose the AI operations required by recommendation orchestration."""

    def __init__(self, manager_module):
        self._manager = manager_module

    def has_configured_provider(self):
        return self._manager.has_configured_provider()

    def recommend_candidates(self, *args, **kwargs):
        return self._manager.recommend_candidates(*args, **kwargs)
