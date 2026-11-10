"""Stable BRNS application façade composed from focused services."""

from BRNS.classes.brc_restaurant_checker_adapter import (
    BRCRestaurantCheckerAdapter,
)
from BRNS.classes.brns_cli_application import BRNSCLIApplication
from BRNS.classes.brns_recommendation_workflow import (
    BRNSRecommendationWorkflow,
)
from BRNS.classes.halal_verification_coordinator import (
    HalalVerificationCoordinator,
)
from BRNS.classes.navigation_service import NavigationService


class RecommendationSystem:
    """Preserve the BRNS public API while delegating focused behavior."""

    def __init__(
            self, ai_manager, data_manager, io_manager, logic_manager,
            checker, config, logger, terminal_ui):
        verifier = BRCRestaurantCheckerAdapter(checker)
        self._halal = HalalVerificationCoordinator(
            logic_manager, io_manager, verifier, logger)
        self._workflow = BRNSRecommendationWorkflow(
            io_manager, ai_manager, logic_manager, data_manager,
            self._halal, config, logger,
        )
        self._navigation = NavigationService(io_manager, logger)
        self._logic = logic_manager
        self._log = logger
        self._cli = BRNSCLIApplication(
            self._workflow, io_manager, config, logger, terminal_ui)

    def brc_restaurant(self, candidate):
        return self._halal.brc_restaurant(candidate)

    def verify_halal_candidates(self, candidates, request, recommendations):
        return self._halal.verify(candidates, request, recommendations)

    def search(self, bis_json, previous_restaurants=()):
        return self._workflow.search(bis_json, previous_restaurants)

    def route_to(self, restaurant, request):
        return self._navigation.route_to(restaurant, request)

    def sort_results(self, results, sort_by):
        sorted_results = self._logic.sort_results(results, sort_by)
        self._log.debug_log(
            f"Results sorted by {sort_by}.", "INFO",
            "BRNS.logic_manager.sort_results",
        )
        return sorted_results

    def run_cli(self):
        return self._cli.run()
