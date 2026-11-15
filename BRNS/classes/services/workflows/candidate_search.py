"Coordinate candidate retrieval using Data, Logic, and an external gateway."


class CandidateSearch:
    """Assemble candidates without owning storage or preference policies."""

    def __init__(self, data, logic, gateway, logger, config=None):
        self._config = config or gateway.config
        self._rules = gateway.logic_manager
        self._policy = gateway.discovery_policy()
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
            self._data.load_candidate_records()
        )
        self._log.debug_log(
            f"Loaded {len(saved_restaurants)} saved restaurants.",
            "DEBUG",
            "BRNS.io_manager.find_candidates",
        )
        candidates = self._helpers.build_candidates(
            origin, lookup, saved_restaurants
        )
        self._log.debug_log(
            f"Candidate builder returned {len(candidates)} records.",
            "DEBUG",
            "BRNS.io_manager.find_candidates",
        )
        return candidates

    def build(self, origin, req, saved_restaurants):
        "Live Places search with saved enrichment or offline saved records."
        if not self._config.USE_LIVE_GOOGLE:
            candidates = self._policy.saved_open_candidates(saved_restaurants)
            self._log.debug_log(
                f"Saved fallback returned {len(candidates)} open candidates.",
                "INFO",
                "BRNS.io_manager.build_candidates",
            )
            return candidates
        min_rating = self._rules.minimum_rating(
            req.get("other_preferences") or []
        )
        places = []
        if self._policy.use_profile_search(req):
            places = self._helpers.fetch_by_profile_text(origin, req)
            if places and (
                not any(
                    (
                        isinstance(place, dict)
                        and place.get("open_now") is True
                        for place in places
                    )
                )
            ):
                self._log.debug_log(
                    (
                        "Text search found no confirmed open places; trying "
                        "nearby."
                    ),
                    "INFO",
                    "BRNS.io_manager.build_candidates",
                )
                places = []
        if not places:
            self._log.debug_log(
                "Text search empty; trying nearby Places.",
                "INFO",
                "BRNS.io_manager.build_candidates",
            )
            places = self._helpers.fetch_nearby_restaurants(origin, req)
            radius_m = float(min(self._helpers._search_radius(req), 50000))
            if self._policy.open_backfill_needed(places, origin, radius_m):
                places = self._helpers._merge_unique_places(
                    places, self._helpers.fetch_open_places(origin, req)
                )
        if not places:
            return []
        radius_m = float(min(self._helpers._search_radius(req), 50000))
        sampled = self._helpers._select_zone_places(
            places, origin, radius_m, limit=20, min_rating=min_rating
        )
        candidates = []
        for p in sampled:
            c = self._helpers.enrich_place(p, saved_restaurants)
            c["google_search_rank"] = len(candidates) + 1
            candidates.append(c)
        self._helpers.travel_times_matrix(
            origin,
            candidates,
            req.get("mode", "walk"),
            req.get("traffic_aware", False),
        )
        self._helpers._fill_travel_estimates(origin, candidates)
        estimated = sum(
            (
                c.get(f"{req.get('mode', 'walk')}_source") == "estimate"
                for c in candidates
            )
        )
        self._log.debug_log(
            (
                "Built "
                f"{len(candidates)}"
                " unique candidates; "
                f"{estimated}"
                " travel estimates."
            ),
            "INFO",
            "BRNS.io_manager.build_candidates",
        )
        return candidates

    def fetch_profile(self, origin, request):
        self._log.debug_log(
            "Text Places request started.",
            "INFO",
            "BRNS.io_manager.fetch_by_profile_text",
        )
        plan = self._helpers.discovery_policy().profile_searches(request)
        response = None
        while True:
            try:
                args, kwargs = plan.send(response)
            except StopIteration as finished:
                places = finished.value
                self._log.debug_log(
                    f"Text Places returned {len(places)} usable records.",
                    "INFO",
                    "BRNS.io_manager.fetch_by_profile_text",
                )
                return places
            response = self._helpers._run_text_search(origin, *args, **kwargs)

    def fetch_open(self, origin, request):
        self._log.debug_log(
            "Open-now Text Places request started.",
            "INFO",
            "BRNS.io_manager.fetch_open_places",
        )
        args, kwargs = self._policy.open_search(
            request, self._helpers.OPEN_SEARCH_MAX_PAGES
        )
        places = self._helpers._run_text_search(origin, *args, **kwargs)
        self._log.debug_log(
            f"Open-now Text Places returned {len(places)} usable records.",
            "INFO",
            "BRNS.io_manager.fetch_open_places",
        )
        return places
