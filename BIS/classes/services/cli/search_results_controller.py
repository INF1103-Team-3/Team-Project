"""Control actions over one set of BIS/BRNS search results."""


class SearchResultsController:
    """Own repeat, refine, sort, route and email result interactions."""

    def __init__(
            self, io_manager, ai_manager, logic_manager, data_manager,
            preference_recorder, brns_application,
            email_delivery, logger, other_preferences_field):
        self._io = io_manager
        self._ai = ai_manager
        self._logic = logic_manager
        self._data = data_manager
        self._preferences = preference_recorder
        self._brns = brns_application
        self._email = email_delivery
        self._log = logger
        self._other_preferences = other_preferences_field

    def run(self, session, request, payload, config):
        previous_restaurants = []
        user_id = session["user"]["userID"]
        while True:
            self._io.display_message("Searching restaurants...")
            if previous_restaurants:
                results = self._brns.search(
                    payload,
                    previous_restaurants=previous_restaurants,
                    user_id=user_id,
                )
            else:
                results = self._brns.search(payload, user_id=user_id)
            matches = results["matches"]
            alternatives = results["alternatives"]
            self._log.debug_log(
                f"BRNS returned {len(matches)} matches and "
                f"{len(alternatives)} alternatives.", "INFO",
                "BIS.main.run_search")
            session["search"] = request
            self._data.set_state(
                "search", user_id, {"completed": True})
            self._io.display_message(
                f"Found {len(matches)} match"
                f"{'es' if len(matches) != 1 else ''} and "
                f"{len(alternatives)} alternative"
                f"{'s' if len(alternatives) != 1 else ''}.")
            if previous_restaurants and results.get("new_count") == 0:
                self._io.display_message(
                    "No new restaurants found for these choices; "
                    "showing available results again.")
            if matches:
                self._io.display_message(
                    f"Top match: {matches[0]['restaurant']['name']}.")
            if not matches:
                self._io.display_no_matches(results)
            visible = bool(matches)
            if visible:
                self._io.display_result_list(results)
            options = matches + alternatives
            previous_restaurants.extend(
                item["restaurant"] for item in options)
            next_request = self._result_actions(
                session, request, results, options, visible, config)
            if next_request is None:
                return
            if next_request is request:
                continue
            request = next_request
            payload = self._data.serialize_search_request(request)
            previous_restaurants = []
            self._log.debug_log(
                "Refined request serialized to JSON.", "INFO",
                "BIS.data.serialize_search_request")

    def _result_actions(
            self, session, request, results, options, visible, config):
        matches = results["matches"]
        alternatives = results["alternatives"]
        while True:
            action = self._io.choose_results_action(
                len(options) if visible else 0,
                alternatives_hidden=bool(alternatives) and not visible)
            if action == "done":
                self._io.display_message(
                    "Search finished. Use /search to try again.")
                return None
            if action == "repeat":
                self._log.debug_log(
                    "Repeating search with the same confirmed request.",
                    "INFO", "BIS.main.run_search")
                return request
            if action == "alternatives" and alternatives and not visible:
                self._io.display_result_list(results)
                visible = True
                continue
            if action == "more" and visible:
                self._io.display_results(
                    results, announce_no_matches=False)
                continue
            if action == "sort" and visible:
                sort_by = self._io.choose_result_sort()
                if sort_by is None:
                    continue
                results = self._brns.sort_results(results, sort_by)
                matches = results["matches"]
                alternatives = results["alternatives"]
                options = matches + alternatives
                self._io.display_message(
                    "Results sorted by "
                    + ("Google rating." if sort_by == "rating"
                       else "travel distance."))
                self._io.display_result_list(results)
                continue
            if action == "again":
                refined = self._refine(session, request, config)
                if refined is not None:
                    return refined
                continue
            if action == "route" and visible:
                self._show_route(options, request)
                continue
            if action == "email" and visible:
                self._email_route(session, options, request, config)
                continue
            self._io.display_message("Choose one of the actions shown.")

    def _refine(self, session, request, config):
        refined = self._io.refine_search_request(
            request, session["user"]["preferences"], config)
        if refined is None:
            return None
        try:
            if config.get("ai_bypass"):
                validated = self._logic.validate_search_request(refined)
            else:
                interpreted = self._ai.interpret_search_request(
                    refined, "", config)
                if interpreted is None:
                    self._io.display_message(
                        "Could not interpret that change. Try again.")
                    return None
                validated = self._logic.validate_search_request(
                    refined, interpreted)
        except (ValueError, RuntimeError) as error:
            self._io.display_message(error)
            return None
        if not config.get("ai_bypass"):
            if self._io.confirm_search_request(validated, config) is not True:
                self._io.display_message(
                    "Search change cancelled; previous results remain.")
                return None
        for wish in validated[self._other_preferences]:
            if (wish not in request[self._other_preferences]
                    and wish not in (
                        session["user"]["preferences"].get(
                            self._other_preferences) or [])):
                self._preferences.remember_wishes(session, wish, config)
        return validated

    def _show_route(self, options, request):
        result_number = self._io.choose_route_result(len(options))
        if result_number is None:
            return
        chosen = options[result_number - 1]["restaurant"]
        if chosen.get("lat") is None or chosen.get("lng") is None:
            self._io.display_message(
                "No route is available for that restaurant.")
            return
        route = self._brns.route_to(chosen, request)
        self._io.display_route(**route)

    def _email_route(self, session, options, request, config):
        user = session["user"]
        if not user.get("email_verified"):
            self._io.display_message(
                "Verify your email before sending a Maps link.")
            return
        result_number = self._io.choose_route_result(len(options))
        if result_number is None:
            return
        chosen = options[result_number - 1]["restaurant"]
        if chosen.get("lat") is None or chosen.get("lng") is None:
            self._io.display_message(
                "No Maps link is available for that restaurant.")
            return
        origin = (
            request["origin"]["latitude"],
            request["origin"]["longitude"],
        )
        destination = (chosen["lat"], chosen["lng"])
        link = self._brns.maps_link(
            origin, destination, request["mode"])
        try:
            self._email.send_maps_link_email(
                user["email"], chosen["name"], link, config)
        except (ValueError, RuntimeError, OSError) as error:
            self._io.display_message(error)
            return
        self._io.display_message(
            f"Google Maps link sent to {user['email']}.")
