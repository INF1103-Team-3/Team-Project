"""Adapter-independent BIS profile and search use cases (IO -> AI -> Logic
-> Data).
"""

from copy import deepcopy

from common.singapore_locations import (
    suggest_seed_locations,
    validate_location_syntax,
)
from BIS.classes.services.web.bis_chatbot_service import (
    BISChatbotService,
)
from BIS.support.config import is_smtp_bypass
from BIS.classes.services.web.preference_review_service import (
    PreferenceReviewService,
)

_NO_OPEN_RESTAURANTS_MESSAGE = (
    "No open restaurants found near this location right now. "
    "Note: In Singapore, many mall outlets close after 10:00 PM. "
    "Try searching a 24-hour hotspot (e.g. 'Rivervale Plaza' or "
    "'Jewel Changi') or increasing travel limits."
)
_EXHAUSTED_REFRESH_MESSAGE = (
    "No more new restaurants found matching your current filters. "
    "Reset seen results or adjust your filters to discover more."
)


class BISApplicationService:
    """Coordinate BIS domain workflows across AI, Logic, Data, and the BRNS
    gateway.
    """

    def __init__(
        self,
        data,
        ai,
        logic,
        brns,
        config,
        model_reader=None,
        chatbot=None,
        location_gateway=None,
        preference_review=None,
    ):
        self._locations = location_gateway
        self._data = data
        self._ai = ai
        self._logic = logic
        self._brns = brns
        self._config = config
        self._model = model_reader or self.__read_last_used_model
        self._reviews = preference_review or PreferenceReviewService(
            ai, logic, config
        )
        self._chatbot = chatbot or BISChatbotService(
            ai,
            logic,
            config,
            model_reader=self._model,
            profile_saver=self.save_profile,
            location_gateway=self._locations,
            preference_review=self._reviews,
        )

    def __read_last_used_model(self):
        reader = getattr(self._brns, "last_used_model", None)
        return reader() if callable(reader) else None

    def active_model(self):
        "Return the active AI model reported by the downstream BRNS gateway."
        reader = getattr(self._brns, "active_model", None)
        if callable(reader):
            model = reader()
            if model:
                return model
        return self._model()

    def map_config(self):
        """Return interactive map provider configuration for the web UI."""
        use_live = self._config.get("use_live_google", True) is not False
        js_key = (
            self._config.get("google_maps_js_api_key")
            or self._config.get("google_maps_api_key")
            or ""
        ).strip()
        active_key = js_key if (js_key and use_live) else ""
        return {
            "provider": "google" if active_key else "leaflet",
            "google_maps_api_key": active_key,
        }

    def suggest_locations(self, query="", limit=6):
        """Return validated Singapore location suggestions."""
        bounded = max(1, min(int(limit or 6), 12))
        suggest_fn = getattr(self._locations, "suggest", None)
        if callable(suggest_fn):
            use_live = self._config.get("use_live_google", True) is not False
            api_key = (
                self._config.get("google_maps_api_key") or ""
                if use_live
                else ""
            )
            items = suggest_fn(query, api_key=api_key, limit=bounded)
        else:
            items = suggest_seed_locations(query, limit=bounded)
        return {"suggestions": list(items or [])}

    def chat(self, user, payload):
        return self._chatbot.respond(user, payload)

    def save_profile(self, user, payload):
        updated = self._logic.prepare_profile_save(
            user, payload, smtp_bypass=is_smtp_bypass(self._config)
        )
        if self._locations is not None:
            api_key = self._config.get("google_maps_api_key")
            for loc in updated["preferences"].get("location") or []:
                try:
                    self._locations.resolve(loc, api_key)
                except (ValueError, RuntimeError):
                    raise ValueError(
                        (
                            "Default location '"
                            f"{loc}"
                            "' must be a valid Singapore location."
                        )
                    )
        wishes = updated["preferences"].get("other_preferences")
        if wishes:
            updated["preferences"]["other_preferences"] = (
                self._reviews.validate_wishes(
                    wishes,
                    field_label="Default special wishes",
                )
            )
        liked_cuisines = updated["preferences"].get("liked_cuisines")
        if liked_cuisines:
            updated["preferences"]["liked_cuisines"] = (
                self._reviews.validate_cuisines(
                    liked_cuisines,
                    field_label="Default preferred cuisines",
                )
            )
        disliked_cuisines = updated["preferences"].get("disliked_cuisines")
        if disliked_cuisines:
            updated["preferences"]["disliked_cuisines"] = (
                self._reviews.validate_cuisines(
                    disliked_cuisines,
                    field_label="Default disliked cuisines",
                )
            )
        return self._data.save(updated)

    def validate_cuisines(self, payload):
        raw = payload.get("cuisines") or []
        parsed = []
        for entry in raw:
            for part in str(entry or "").split(","):
                clean = part.strip()
                if clean:
                    parsed.append(clean)
        if not parsed:
            raise ValueError("Enter a cuisine name before adding.")
        label = (
            str(payload.get("field_label") or "Cuisine").strip() or "Cuisine"
        )
        cleaned = self._reviews.validate_cuisines(
            parsed,
            field_label=label,
        )
        return {"success": True, "valid": True, "cuisines": cleaned}

    def __resolve_origins(self, raw_locations):
        api_key = self._config.get("google_maps_api_key")
        if self._locations is None:
            raise RuntimeError("Location lookup is not configured.")
        resolved = []
        for raw in raw_locations:
            clean = validate_location_syntax(raw, label="Starting location")
            resolved.append(self._locations.resolve(clean, api_key))
        return self._logic.compute_midpoint_origin(resolved), resolved

    def __build_validated_request(self, payload, origin, cuisine_target):
        request = self._logic.build_base_search_request(
            payload, origin, cuisine_target
        )
        config = deepcopy(self._config)
        wishes = ", ".join(request["other_preferences"])
        interpreted = self._ai.interpret_search_request(
            request, wishes, config
        )
        return self._logic.preserve_search_wish(
            request,
            self._logic.validate_search_request(request, interpreted),
            wishes,
        )

    @staticmethod
    def __is_no_open_error(exc):
        msg = str(exc).lower()
        if "unavailable" in msg:
            return False
        return "no restaurants found" in msg or "no confirmed open" in msg

    @staticmethod
    def __normalize_previous_restaurants(raw_previous):
        """Convert Pydantic models or dicts into seen-restaurant dicts."""
        normalized = []
        for item in raw_previous or ():
            if hasattr(item, "model_dump"):
                item = item.model_dump()
            if not isinstance(item, dict):
                continue
            pid = item.get("google_place_id")
            pid_str = str(pid).strip() if pid is not None else ""
            name = str(item.get("name") or "").strip()
            address = str(item.get("address") or "").strip()
            if not pid_str and not name and not address:
                continue
            normalized.append(
                {
                    "google_place_id": pid_str or None,
                    "name": name,
                    "address": address,
                }
            )
        return normalized

    @staticmethod
    def __build_previous_matcher(previous_restaurants):
        """Build a seen predicate keyed by place ID or (name, address)."""
        seen_pids = set()
        seen_name_addrs = set()
        for item in previous_restaurants or ():
            if not isinstance(item, dict):
                continue
            pid = str(item.get("google_place_id") or "").strip()
            if pid:
                seen_pids.add(pid)
            name = str(item.get("name") or "").casefold().strip()
            addr = str(item.get("address") or "").casefold().strip()
            if name:
                seen_name_addrs.add((name, addr))

        def is_seen(entry):
            restaurant = (
                entry.get("restaurant")
                if isinstance(entry, dict) and "restaurant" in entry
                else entry
            )
            if not isinstance(restaurant, dict):
                return False
            pid = str(restaurant.get("google_place_id") or "").strip()
            if pid and pid in seen_pids:
                return True
            name = str(restaurant.get("name") or "").casefold().strip()
            addr = str(restaurant.get("address") or "").casefold().strip()
            return bool(name and (name, addr) in seen_name_addrs)

        return is_seen

    def __search_brns(
        self, request, user_id, previous_restaurants, strict_exclude
    ):
        """Call the BRNS gateway, forwarding seen venues only on refresh."""
        serialized = self._data.serialize_search_request(request)
        if strict_exclude:
            return self._brns.search(
                serialized,
                previous_restaurants=previous_restaurants,
                user_id=user_id,
                max_matches=20,
                max_alternatives=20,
                strict_exclude=True,
            )
        return self._brns.search(
            serialized,
            user_id=user_id,
            max_matches=20,
            max_alternatives=20,
        )

    def __build_search_response(
        self,
        origin,
        resolved_origins,
        selected_cuisines,
        cuisines_breakdown,
        matches,
        alternatives,
        hidden,
        *,
        strict_exclude=False,
        exhausted_previous=False,
        message=None,
    ):
        """Format `/api/search` response preserving normal-search keys."""
        response = {
            "success": True,
            "confirmation_required": False,
            "origin": origin,
            "input_origins": resolved_origins,
            "origins": resolved_origins,
            "selected_cuisines": selected_cuisines,
            "cuisines_breakdown": cuisines_breakdown,
            "matches": matches,
            "alternatives": alternatives,
            "exclusions_count": hidden,
            "model_used": self._model() or "AI provider unavailable",
        }
        if strict_exclude:
            response["exhausted_previous"] = bool(exhausted_previous)
            response["new_count"] = len(matches) + len(alternatives)
        if message:
            response["message"] = message
        return response

    def __run_search(
        self,
        owner,
        payload,
        origin,
        resolved_origins,
        selected_cuisines,
        first_request=None,
        previous_restaurants=(),
        strict_exclude=False,
    ):
        cuisines_breakdown = {}
        normalized_previous = (
            self.__normalize_previous_restaurants(previous_restaurants)
            if strict_exclude and previous_restaurants
            else []
        )
        is_seen = (
            self.__build_previous_matcher(normalized_previous)
            if normalized_previous
            else None
        )
        try:
            exhausted_previous = False
            if len(selected_cuisines) <= 1:
                single_c = selected_cuisines[0] if selected_cuisines else None
                request = first_request or self.__build_validated_request(
                    payload, origin, single_c
                )
                results = self.__search_brns(
                    request, owner, normalized_previous, strict_exclude
                )
                matches = list(results.get("matches", []) or [])
                alternatives = list(results.get("alternatives", []) or [])
                if is_seen is not None:
                    matches = [m for m in matches if not is_seen(m)]
                    alternatives = [a for a in alternatives if not is_seen(a)]
                if single_c:
                    matches = [
                        (
                            dict(item, matched_cuisine=single_c)
                            if isinstance(item, dict)
                            else item
                        )
                        for item in matches
                    ]
                    alternatives = [
                        (
                            dict(item, matched_cuisine=single_c)
                            if isinstance(item, dict)
                            else item
                        )
                        for item in alternatives
                    ]
                    cuisines_breakdown[single_c] = len(matches) + len(
                        alternatives
                    )
                hidden = results.get("hidden", 0)
                if strict_exclude:
                    exhausted_previous = bool(
                        not matches
                        and not alternatives
                        and (
                            normalized_previous
                            or results.get("exhausted_previous")
                        )
                    )
            else:
                fetched = []
                last_empty_error = None
                base_request = None
                any_sub_exhausted = False
                for c_target in selected_cuisines:
                    sub_request = self.__build_validated_request(
                        payload, origin, c_target
                    )
                    if base_request is None:
                        base_request = sub_request
                    try:
                        sub_res = self.__search_brns(
                            sub_request,
                            None,
                            normalized_previous,
                            strict_exclude,
                        )
                    except RuntimeError as sub_exc:
                        if self.__is_no_open_error(sub_exc):
                            last_empty_error = sub_exc
                            fetched.append((c_target, None))
                            continue
                        raise
                    if strict_exclude and isinstance(sub_res, dict):
                        if sub_res.get("exhausted_previous"):
                            any_sub_exhausted = True
                        if is_seen is not None:
                            sub_res = dict(
                                sub_res,
                                matches=[
                                    m
                                    for m in (sub_res.get("matches") or [])
                                    if not is_seen(m)
                                ],
                                alternatives=[
                                    a
                                    for a in (
                                        sub_res.get("alternatives") or []
                                    )
                                    if not is_seen(a)
                                ],
                            )
                    fetched.append((c_target, sub_res))

                (
                    matches,
                    alternatives,
                    cuisines_breakdown,
                    hidden,
                ) = self._logic.merge_multi_cuisine_results(
                    fetched, len(selected_cuisines), max_total=20
                )
                if strict_exclude:
                    exhausted_previous = bool(
                        not matches
                        and not alternatives
                        and (normalized_previous or any_sub_exhausted)
                    )
                if (
                    not matches
                    and not alternatives
                    and last_empty_error is not None
                ):
                    if not exhausted_previous:
                        raise last_empty_error

                if not (strict_exclude and not matches and not alternatives):
                    summary_req = dict(base_request or {})
                    summary_req["cuisine"] = ", ".join(selected_cuisines)
                    self._brns.save_history_summary(
                        owner,
                        summary_req,
                        {"matches": matches, "alternatives": alternatives},
                        "live-google",
                    )

            message = (
                _EXHAUSTED_REFRESH_MESSAGE if exhausted_previous else None
            )
            return self.__build_search_response(
                origin,
                resolved_origins,
                selected_cuisines,
                cuisines_breakdown,
                matches,
                alternatives,
                hidden,
                strict_exclude=strict_exclude,
                exhausted_previous=exhausted_previous,
                message=message,
            )
        except RuntimeError as exc:
            if self.__is_no_open_error(exc):
                if strict_exclude and normalized_previous:
                    return self.__build_search_response(
                        origin,
                        resolved_origins,
                        selected_cuisines,
                        cuisines_breakdown,
                        [],
                        [],
                        0,
                        strict_exclude=True,
                        exhausted_previous=True,
                        message=_EXHAUSTED_REFRESH_MESSAGE,
                    )
                return self.__build_search_response(
                    origin,
                    resolved_origins,
                    selected_cuisines,
                    cuisines_breakdown,
                    [],
                    [],
                    0,
                    strict_exclude=strict_exclude,
                    exhausted_previous=False,
                    message=_NO_OPEN_RESTAURANTS_MESSAGE,
                )
            raise

    def search(self, user, payload):
        owner = user["userID"] if user else None
        strict_exclude = bool(payload.get("strict_exclude"))
        previous_restaurants = self.__normalize_previous_restaurants(
            payload.get("previous_restaurants")
        )
        token = payload.get("confirmation_token")
        if token and not strict_exclude:
            proposal = self._data.consume_search_proposal(owner, token)
            request = (
                proposal["request"]
                if isinstance(proposal, dict) and "request" in proposal
                else proposal
            )
            resolved_origins = (
                proposal.get("resolved_origins")
                if isinstance(proposal, dict)
                and "resolved_origins" in proposal
                else [request["origin"]]
            )
            selected_cuisines = (
                proposal.get("selected_cuisines")
                if isinstance(proposal, dict)
                and "selected_cuisines" in proposal
                else (
                    [request["cuisine"]]
                    if request.get("cuisine")
                    and request.get("cuisine") != "none"
                    else []
                )
            )
            return self.__run_search(
                owner,
                payload,
                request["origin"],
                resolved_origins,
                selected_cuisines,
                first_request=request,
            )

        raw_locations = self._logic.collect_search_locations(payload)
        origin, resolved_origins = self.__resolve_origins(raw_locations)
        selected_cuisines = self._reviews.validate_cuisines(
            self._logic.collect_search_cuisines(payload),
            field_label="Preferred cuisines",
        )
        collect_disliked = getattr(
            self._logic, "collect_search_disliked_cuisines", None
        )
        raw_disliked = (
            collect_disliked(payload)
            if callable(collect_disliked)
            else (payload.get("disliked_cuisines") or [])
        )
        normalized_disliked = self._reviews.validate_cuisines(
            raw_disliked,
            field_label="Disliked cuisines",
        )
        cuisine_overlap = set(selected_cuisines) & set(normalized_disliked)
        if cuisine_overlap:
            joined = ", ".join(sorted(cuisine_overlap))
            raise ValueError(
                "Resolve cuisines listed as both preferred and disliked: "
                f"{joined}."
            )
        normalized_wishes = self._reviews.validate_wishes(
            payload.get("other_preferences"),
            field_label="Special requests",
        )
        if (
            "other_preferences" in payload
            or normalized_wishes
            or "disliked_cuisines" in payload
            or normalized_disliked
        ):
            payload = dict(
                payload,
                other_preferences=normalized_wishes,
                disliked_cuisines=normalized_disliked,
            )

        if payload.get("confirm_only") and not strict_exclude:
            single_c = (
                selected_cuisines[0] if len(selected_cuisines) == 1 else None
            )
            request = self.__build_validated_request(payload, origin, single_c)
            proposal_token = self._data.create_search_proposal(
                owner,
                {
                    "request": request,
                    "resolved_origins": resolved_origins,
                    "selected_cuisines": selected_cuisines,
                },
            )
            return {
                "success": True,
                "confirmation_required": True,
                "request": request,
                "confirmation_token": proposal_token,
            }

        return self.__run_search(
            owner,
            payload,
            origin,
            resolved_origins,
            selected_cuisines,
            previous_restaurants=previous_restaurants,
            strict_exclude=strict_exclude,
        )

    def route(self, payload):
        request = {
            "origin": {
                "latitude": payload["origin_lat"],
                "longitude": payload["origin_lng"],
            },
            "mode": payload["mode"],
            "traffic_aware": payload["traffic_aware"],
        }
        restaurant = {
            "name": payload["name"],
            "lat": payload["dest_lat"],
            "lng": payload["dest_lng"],
        }
        return self._brns.route_to(restaurant, request)

    def place_photo(self, place_id):
        fetcher = getattr(self._brns, "place_photo", None)
        if callable(fetcher):
            return fetcher(place_id)
        return None

    def history(self, user):
        return self._brns.load_history(user["userID"])

    def clear_history(self, user):
        self._brns.clear_history(user["userID"])
        return {"success": True}
