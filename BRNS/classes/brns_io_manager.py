"""Object boundary for BRNS input, provider and display behavior."""

from BRNS.classes.candidate_io_interface import CandidateIOInterface
from BRNS.classes.navigation_io_interface import NavigationIOInterface
from BRNS.classes.recommendation_presentation_interface import (
    RecommendationPresentationInterface,
)


class BRNSIOManager(
        CandidateIOInterface, RecommendationPresentationInterface,
        NavigationIOInterface):
    """Expose IO operations used by recommendation orchestration."""

    def __init__(self, manager_module):
        self._manager = manager_module

    @property
    def display_debug(self):
        return self._manager.display_debug

    def accept_bis_json(self, payload):
        return self._manager.accept_bis_json(payload)

    def find_candidates(self, request):
        return self._manager.find_candidates(request)

    def show_ai_ranking_start(self, count, timeout):
        return self._manager.show_ai_ranking_start(count, timeout)

    def show_halal_verification_start(self, count, database_missing=False):
        return self._manager.show_halal_verification_start(
            count, database_missing)

    def show_halal_verification_summary(self, summary):
        return self._manager.show_halal_verification_summary(summary)

    def get_route(self, *args, **kwargs):
        return self._manager.get_route(*args, **kwargs)

    def build_maps_link(self, *args, **kwargs):
        return self._manager.build_maps_link(*args, **kwargs)

    def show_results(self, results):
        return self._manager.show_results(results)
