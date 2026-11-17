"Coordinate candidate retrieval using Data, Logic, and an external gateway."

from contextvars import ContextVar

from BRNS.classes.logic.evaluation.previous_restaurant_matcher import (
    PreviousRestaurantMatcher,
)

_DISCOVERY_TRACKER = ContextVar("brns_discovery_tracker", default=None)
_LAST_DISCOVERY_ERROR = ContextVar("brns_last_discovery_error", default=False)


class CandidateSearch:
    """Assemble candidates without owning storage or preference policies."""

    def __init__(
        self,
        data,
        logic,
        gateway,
        logger,
        config=None,
        places_gateway=None,
        route_gateway=None,
        policy=None,
    ):
        self._config = config or gateway.config
        self._rules = gateway.logic_manager
        self._policy = policy or gateway.discovery_policy()
        self._places = places_gateway or gateway.places_gateway()
        self._routes = route_gateway or gateway.route_gateway()
        self._data = data
        self._logic = logic or gateway.logic_manager.manager()
        self._helpers = gateway
        self._log = logger

    def last_discovery_failed(self):
        """Return True if the latest build failed only on API errors."""
        return bool(_LAST_DISCOVERY_ERROR.get())

    @staticmethod
    def __active_matcher(previous_restaurants, strict_exclude):
        if not strict_exclude or not previous_restaurants:
            return None
        matcher = PreviousRestaurantMatcher(previous_restaurants)
        return None if matcher.is_empty else matcher

    @staticmethod
    def __record_discovery_status(succeeded):
        tracker = _DISCOVERY_TRACKER.get()
        if tracker is not None:
            tracker["api_success" if succeeded else "api_error"] = True

    @staticmethod
    def __filter_excluded_places(places, matcher):
        if matcher is None:
            return list(places)
        kept = []
        excluded = 0
        for place in places:
            if isinstance(place, dict) and matcher.matches(place):
                excluded += 1
            else:
                kept.append(place)
        tracker = _DISCOVERY_TRACKER.get()
        if tracker is not None and excluded:
            tracker["excluded_count"] += excluded
        return kept

    @staticmethod
    def __confirmed_open_count(places):
        return sum(
            1
            for place in places
            if isinstance(place, dict) and place.get("open_now") is True
        )

    def __run_text_search_tracked(self, origin, *args, matcher=None, **kwargs):
        want_status = bool(kwargs.get("return_status"))
        call_kwargs = dict(kwargs, return_status=True)
        if matcher is not None:
            call_kwargs["max_pages"] = 3
        result = self._places.run_text_search(origin, *args, **call_kwargs)
        if isinstance(result, tuple) and len(result) == 2:
            places, ok = result
            self.__record_discovery_status(ok)
        else:
            places, ok = result, True
        places = self.__filter_excluded_places(places, matcher)
        return (places, ok) if want_status else places

    def __fetch_open_filtered(
        self, origin, req, previous_restaurants, matcher
    ):
        if matcher is not None:
            raw = self.fetch_open(
                origin,
                req,
                previous_restaurants=previous_restaurants,
                strict_exclude=True,
            )
        else:
            raw = self.fetch_open(origin, req)
        return self.__filter_excluded_places(raw, matcher)

    def __fetch_nearby_filtered(self, origin, req, matcher):
        raw = self._places.fetch_nearby_restaurants(origin, req)
        self.__record_discovery_status(not self._places.last_call_failed())
        return self.__filter_excluded_places(raw, matcher)

    def find(self, request, previous_restaurants=(), strict_exclude=False):
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
        if strict_exclude and previous_restaurants:
            candidates = self.build(
                origin,
                lookup,
                saved_restaurants,
                previous_restaurants=previous_restaurants,
                strict_exclude=True,
            )
        else:
            candidates = self.build(origin, lookup, saved_restaurants)
        self._log.debug_log(
            f"Candidate builder returned {len(candidates)} records.",
            "DEBUG",
            "BRNS.io_manager.find_candidates",
        )
        return candidates

    def __collect_live_places(
        self, origin, req, previous_restaurants, matcher, strict_active
    ):
        places = []
        ran_nearby = False
        ran_open_places = False
        if self._policy.use_profile_search(req):
            if strict_active:
                places = self.fetch_profile(
                    origin,
                    req,
                    previous_restaurants=previous_restaurants,
                    strict_exclude=True,
                )
            else:
                places = self.fetch_profile(origin, req)
            places = self.__filter_excluded_places(places, matcher)
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
            places = self.__fetch_nearby_filtered(origin, req, matcher)
            ran_nearby = True
            radius_m = float(min(self._policy.search_radius(req), 50000))
            if self._policy.open_backfill_needed(places, origin, radius_m):
                open_extra = self.__fetch_open_filtered(
                    origin, req, previous_restaurants, matcher
                )
                ran_open_places = True
                places = self._policy.merge_unique_places(places, open_extra)
        if strict_active and self.__confirmed_open_count(places) < 5:
            if not ran_nearby:
                nearby_extra = self.__fetch_nearby_filtered(
                    origin, req, matcher
                )
                ran_nearby = True
                places = self._policy.merge_unique_places(places, nearby_extra)
            if self.__confirmed_open_count(places) < 5 and not ran_open_places:
                open_extra = self.__fetch_open_filtered(
                    origin, req, previous_restaurants, matcher
                )
                ran_open_places = True
                places = self._policy.merge_unique_places(places, open_extra)
        return places

    def __assemble_candidates(self, origin, req, sampled, saved_restaurants):
        candidates = []
        for p in sampled:
            c = self._logic.enrich_place(p, saved_restaurants)
            c["google_search_rank"] = len(candidates) + 1
            candidates.append(c)
        self._routes.travel_times_matrix(
            origin,
            candidates,
            req.get("mode", "walk"),
            req.get("traffic_aware", False),
        )
        self._routes.fill_travel_estimates(origin, candidates)
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

    def build(
        self,
        origin,
        req,
        saved_restaurants,
        previous_restaurants=(),
        strict_exclude=False,
    ):
        "Live Places search with saved enrichment or offline saved records."
        matcher = self.__active_matcher(previous_restaurants, strict_exclude)
        strict_active = matcher is not None
        _LAST_DISCOVERY_ERROR.set(False)
        if not self._config.USE_LIVE_GOOGLE:
            candidates = self._policy.saved_open_candidates(saved_restaurants)
            candidates = self.__filter_excluded_places(candidates, matcher)
            self._log.debug_log(
                f"Saved fallback returned {len(candidates)} open candidates.",
                "INFO",
                "BRNS.io_manager.build_candidates",
            )
            return candidates
        min_rating = self._rules.minimum_rating(
            req.get("other_preferences") or []
        )
        tracker = {
            "api_success": False,
            "api_error": False,
            "excluded_count": 0,
        }
        token = _DISCOVERY_TRACKER.set(tracker)
        try:
            places = self.__collect_live_places(
                origin, req, previous_restaurants, matcher, strict_active
            )
            if not places:
                return []
            radius_m = float(min(self._policy.search_radius(req), 50000))
            sampled = self._policy.select_zone_places(
                places, origin, radius_m, limit=20, min_rating=min_rating
            )
            if not sampled:
                return []
            return self.__assemble_candidates(
                origin, req, sampled, saved_restaurants
            )
        finally:
            _DISCOVERY_TRACKER.reset(token)
            _LAST_DISCOVERY_ERROR.set(
                tracker["api_error"]
                and not tracker["api_success"]
                and tracker["excluded_count"] == 0
            )

    def __run_search_plan(self, origin, plan, matcher):
        response = None
        while True:
            try:
                args, kwargs = plan.send(response)
            except StopIteration as finished:
                return self.__filter_excluded_places(finished.value, matcher)
            response = self.__run_text_search_tracked(
                origin, *args, matcher=matcher, **kwargs
            )

    def fetch_profile(
        self, origin, request, previous_restaurants=(), strict_exclude=False
    ):
        matcher = self.__active_matcher(previous_restaurants, strict_exclude)
        self._log.debug_log(
            "Text Places request started.",
            "INFO",
            "BRNS.io_manager.fetch_by_profile_text",
        )
        plan = self._policy.profile_searches(request)
        places = self.__run_search_plan(origin, plan, matcher)
        self._log.debug_log(
            f"Text Places returned {len(places)} usable records.",
            "INFO",
            "BRNS.io_manager.fetch_by_profile_text",
        )
        return places

    def fetch_open(
        self, origin, request, previous_restaurants=(), strict_exclude=False
    ):
        matcher = self.__active_matcher(previous_restaurants, strict_exclude)
        self._log.debug_log(
            "Open-now Text Places request started.",
            "INFO",
            "BRNS.io_manager.fetch_open_places",
        )
        if hasattr(self._policy, "open_searches"):
            plan = self._policy.open_searches(
                request, self._helpers.OPEN_SEARCH_MAX_PAGES
            )
            places = self.__run_search_plan(origin, plan, matcher)
        else:
            args, kwargs = self._policy.open_search(
                request, self._helpers.OPEN_SEARCH_MAX_PAGES
            )
            places = self.__run_text_search_tracked(
                origin, *args, matcher=matcher, **kwargs
            )
        self._log.debug_log(
            f"Open-now Text Places returned {len(places)} usable records.",
            "INFO",
            "BRNS.io_manager.fetch_open_places",
        )
        return places
