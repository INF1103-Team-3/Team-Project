"""BRNS web IO: reuse input/gateway operations and suppress terminal output."""
from BRNS.classes.candidate_io_interface import CandidateIOInterface
from BRNS.classes.navigation_io_interface import NavigationIOInterface
from BRNS.classes.recommendation_presentation_interface import RecommendationPresentationInterface


class WebIOManager(CandidateIOInterface, NavigationIOInterface, RecommendationPresentationInterface):
    def __init__(self, core):
        self._core = core

    @property
    def display_debug(self):
        return lambda _line: None

    def accept_bis_json(self, payload):
        return self._core.accept_bis_json(payload)

    def find_candidates(self, request):
        return self._core.find_candidates(request)

    def get_route(self, *args, **kwargs):
        return self._core.get_route(*args, **kwargs)

    def build_maps_link(self, *args, **kwargs):
        return self._core.build_maps_link(*args, **kwargs)

    def show_ai_ranking_start(self, count, timeout):
        pass

    def show_halal_verification_start(self, count, database_missing=False):
        pass

    def show_halal_verification_summary(self, summary):
        pass

    def show_results(self, results):
        return results
