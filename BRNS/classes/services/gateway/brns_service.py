"""Headless BRNS gateway coordinating search, navigation, history, and model metadata."""

from BRNS.classes.services.gateway.brns_gateway_interface import BRNSGatewayInterface


class BRNSService(BRNSGatewayInterface):
    """Own downstream BRNS operations so callers interact through one boundary."""

    def __init__(
        self,
        workflow,
        navigator,
        logic_manager,
        data_manager,
        history_scope,
        io_manager,
        logger,
        active_model_reader=lambda: None,
        last_model_reader=lambda: None,
        photo_service=None,
    ):
        self._workflow = workflow
        self._navigator = navigator
        self._logic = logic_manager
        self._data = data_manager
        self._history_scope = history_scope
        self._io = io_manager
        self._log = logger
        self._active_model_reader = active_model_reader
        self._last_model_reader = last_model_reader
        self._photo_service = photo_service

    def search(
        self,
        bis_json,
        previous_restaurants=(),
        user_id=None,
        max_matches=None,
        max_alternatives=None,
    ):
        kwargs = {}
        if max_matches is not None:
            kwargs["max_matches"] = max_matches
        if max_alternatives is not None:
            kwargs["max_alternatives"] = max_alternatives
        with self._history_scope.for_user(user_id):
            if previous_restaurants:
                return self._workflow.search(
                    bis_json, previous_restaurants=previous_restaurants, **kwargs
                )
            return self._workflow.search(bis_json, **kwargs)

    def route_to(self, restaurant, request):
        return self._navigator.route_to(restaurant, request)

    def place_photo(self, place_id):
        if self._photo_service is None:
            return None
        return self._photo_service.get_or_fetch_photo(place_id)

    def sort_results(self, results, sort_by):
        sorted_results = self._logic.sort_results(results, sort_by)
        self._log.debug_log(
            f"Results sorted by {sort_by}.",
            "INFO",
            "BRNS.logic_manager.sort_results",
        )
        return sorted_results

    def maps_link(self, origin, destination, mode):
        return self._io.build_maps_link(origin, destination, mode)

    def load_history(self, user_id):
        return self._data.load_user_history(user_id)

    def save_history_summary(self, user_id, request, results, source="live-google"):
        with self._history_scope.for_user(user_id):
            return self._data.save_search_results(request, results, source)

    def clear_history(self, user_id):
        self._data.clear_user_history(user_id)

    def active_model(self):
        return self._active_model_reader()

    def last_used_model(self):
        return self._last_model_reader()
