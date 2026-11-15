"""The ordered IO to AI to Logic to Data BIS search workflow."""

import time


class BISSearchWorkflow:
    """Collect, interpret, validate and persist one BIS search request."""

    def __init__(
            self, io_manager, ai_manager, logic_manager, data_manager,
            preference_recorder, results_controller, logger,
            other_preferences_field):
        self._io = io_manager
        self._ai = ai_manager
        self._logic = logic_manager
        self._data = data_manager
        self._preferences = preference_recorder
        self._results = results_controller
        self._log = logger
        self._other_preferences = other_preferences_field

    def run(self, session, config, automatic=False):
        if self._logic.next_field(
                session["user"]["preferences"]) is not None:
            self._io.display_message(
                "Complete your profile before using /search.")
            return
        user_id = session["user"]["userID"]
        trace_token = self._log.start_trace()
        started = time.monotonic()
        self._log.debug_log(
            "Search started.", "INFO", "BIS.main.run_search")
        try:
            state = self._data.get_state("search", user_id)
            if automatic and state and state.get("completed"):
                return
            if automatic:
                self._io.display_message(
                    "Profile complete. Starting /search.")
            collected = self._io.collect_search(session["user"], config)
            if collected is None:
                self._log.debug_log(
                    "Collection cancelled.", "INFO",
                    "BIS.io.collect_search")
                self._io.display_message("Search cancelled.")
                return
            self._log.debug_log(
                "Search choices collected.", "INFO",
                "BIS.io.collect_search")
            confirmed = collected["request"]
            today_request = collected["today_request"]
            if collected.get("save_cuisine"):
                self._preferences.remember_cuisine(
                    session, collected["save_cuisine"], config)
            request = self._interpret_and_validate(
                confirmed, today_request, config)
            if request is None:
                return
            payload = self._data.serialize_search_request(request)
            self._log.debug_log(
                "Validated request serialized to JSON.", "INFO",
                "BIS.data.serialize_search_request")
            self._preferences.remember_wishes(
                session, today_request, config)
            if config.get("ai_bypass"):
                self._io.display_search_summary(request)
                session["search"] = request
                self._data.set_state(
                    "search", user_id, {"completed": True})
                self._io.display_message(
                    "Chatbot test mode: restaurant search skipped.",
                    role="bypass")
                self._log.debug_log(
                    "Chatbot test completed without BRNS.", "INFO",
                    "BIS.main.run_search")
                return
            return self._results.run(
                session, request, payload, config)
        except (ValueError, RuntimeError, OSError) as error:
            self._log.debug_log(
                f"Search stopped: {type(error).__name__}.", "ERROR",
                "BIS.main.run_search")
            self._io.display_message(
                f"{error} Details: logs/bitefinder.log "
                f"(trace {self._log.current_trace_id()}).", role="error")
        finally:
            self._log.debug_log(
                f"Search flow finished in "
                f"{time.monotonic() - started:.2f}s.",
                "INFO", "BIS.main.run_search")
            self._log.end_trace(trace_token)

    def _interpret_and_validate(self, confirmed, today_request, config):
        if config.get("ai_bypass"):
            return self._logic.validate_search_request(confirmed)
        while True:
            interpreted = self._ai.interpret_search_request(
                confirmed, today_request, config)
            self._log.debug_log(
                "AI interpretation returned.", "INFO",
                "BIS.ai.interpret_search_request")
            if interpreted is None:
                raise RuntimeError(
                    "BIS AI could not interpret today's request. "
                    "Please retry.")
            try:
                request = self._logic.validate_search_request(
                    confirmed, interpreted)
                request = self._logic.preserve_search_wish(
                    confirmed, request, today_request, self._other_preferences)
                self._log.debug_log(
                    "AI proposal validated.", "INFO",
                    "BIS.logic.validate_search_request")
                break
            except ValueError as error:
                if not self._logic.is_search_clarification(error):
                    raise
                self._log.debug_log(
                    "Clarification required.", "WARNING",
                    "BIS.logic.validate_search_request")
                self._io.display_message(
                    self._logic.clarification_message(error))
                today_request = self._io.ask_search_clarification(config)
                if today_request is None:
                    self._io.display_message("Search cancelled.")
                    return None
        if self._io.confirm_search_request(request, config) is not True:
            self._log.debug_log(
                "Interpretation declined.", "INFO",
                "BIS.io.confirm_search_request")
            self._io.display_message("Search cancelled.")
            return None
        self._log.debug_log(
            "Interpretation confirmed.", "INFO",
            "BIS.io.confirm_search_request")
        return request
