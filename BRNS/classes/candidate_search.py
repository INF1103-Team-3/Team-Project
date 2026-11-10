"""Coordinate candidate retrieval using Data, Logic, and an external gateway."""


class CandidateSearch:
    """Assemble candidates without owning storage or preference policies."""

    def __init__(self, data, logic, gateway, logger):
        self._data = data
        self._logic = logic
        self._helpers = gateway
        self._log = logger

    def find(self, request):
        origin = (
            request["origin"]["latitude"],
            request["origin"]["longitude"],
        )
        lookup = self._logic.prepare_candidate_search(request)
        saved_restaurants = self._logic.saved_candidates(
            self._data.load_candidate_records())
        self._log.debug_log(
            f"Loaded {len(saved_restaurants)} saved restaurants.",
            "DEBUG", "BRNS.io_manager.find_candidates")
        candidates = self._helpers.build_candidates(
            origin, lookup, saved_restaurants)
        self._log.debug_log(
            f"Candidate builder returned {len(candidates)} records.",
            "DEBUG", "BRNS.io_manager.find_candidates")
        return candidates
