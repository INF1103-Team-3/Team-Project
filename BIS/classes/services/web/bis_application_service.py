"""Adapter-independent BIS profile and search use cases (IO -> AI -> Logic -> Data)."""

from copy import deepcopy

from BIS.classes.services.web.bis_chatbot_service import BISChatbotService
from BIS.support.config import is_smtp_bypass


class BISApplicationService:
    """Coordinate BIS domain workflows across AI, Logic, Data, and the BRNS gateway."""

    def __init__(self, data, ai, logic, brns, config,
                 model_reader=None, chatbot=None):
        self._data = data
        self._ai = ai
        self._logic = logic
        self._brns = brns
        self._config = config
        self._model = model_reader or self._read_last_used_model
        self._chatbot = chatbot or BISChatbotService(
            ai, logic, config, model_reader=self._model, profile_saver=self.save_profile)

    def _read_last_used_model(self):
        reader = getattr(self._brns, "last_used_model", None)
        return reader() if callable(reader) else None

    def active_model(self):
        """Return the active AI model reported by the downstream BRNS gateway."""
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

    def chat(self, user, payload):
        return self._chatbot.respond(user, payload)

    def save_profile(self, user, payload):
        updated = self._logic.prepare_profile_save(
            user, payload, smtp_bypass=is_smtp_bypass(self._config))
        if hasattr(self._data, "resolve_location"):
            api_key = self._config.get("google_maps_api_key")
            for loc in updated["preferences"].get("location") or []:
                try:
                    self._data.resolve_location(loc, api_key)
                except (ValueError, RuntimeError):
                    raise ValueError(
                        f"Default location '{loc}' must be a valid Singapore location."
                    )
        wishes = updated["preferences"].get("other_preferences") or []
        if (wishes and not self._config.get("ai_bypass")
                and hasattr(self._ai, "review_profile_wishes")):
            try:
                self._ai.review_profile_wishes(wishes, deepcopy(self._config))
            except RuntimeError:
                pass
        return self._data.save(updated)

    def _resolve_origins(self, raw_locations):
        api_key = self._config.get("google_maps_api_key")
        resolved = [self._data.resolve_location(loc, api_key) for loc in raw_locations]
        return self._logic.compute_midpoint_origin(resolved), resolved

    def _build_validated_request(self, payload, origin, cuisine_target):
        request = self._logic.build_base_search_request(payload, origin, cuisine_target)
        config = deepcopy(self._config)
        wishes = ", ".join(request["other_preferences"])
        interpreted = self._ai.interpret_search_request(request, wishes, config)
        return self._logic.preserve_search_wish(
            request, self._logic.validate_search_request(request, interpreted), wishes)

    @staticmethod
    def _is_no_open_error(exc):
        msg = str(exc).lower()
        return "no restaurants found" in msg or "no confirmed open" in msg

    def _run_search(self, owner, payload, origin, resolved_origins, selected_cuisines,
                    first_request=None):
        cuisines_breakdown = {}
        try:
            if len(selected_cuisines) <= 1:
                single_c = selected_cuisines[0] if selected_cuisines else None
                request = first_request or self._build_validated_request(
                    payload, origin, single_c)
                results = self._brns.search(
                    self._data.serialize_search_request(request),
                    user_id=owner,
                    max_matches=20,
                    max_alternatives=20,
                )
                matches = results.get("matches", [])
                alternatives = results.get("alternatives", [])
                if single_c:
                    for item in matches + alternatives:
                        if isinstance(item, dict):
                            item["matched_cuisine"] = single_c
                    cuisines_breakdown[single_c] = len(matches) + len(alternatives)
                hidden = results.get("hidden", 0)
            else:
                fetched = []
                last_empty_error = None
                base_request = None
                for c_target in selected_cuisines:
                    sub_request = self._build_validated_request(
                        payload, origin, c_target)
                    if base_request is None:
                        base_request = sub_request
                    try:
                        sub_res = self._brns.search(
                            self._data.serialize_search_request(sub_request),
                            user_id=None,
                            max_matches=20,
                            max_alternatives=20,
                        )
                    except RuntimeError as sub_exc:
                        if self._is_no_open_error(sub_exc):
                            last_empty_error = sub_exc
                            fetched.append((c_target, None))
                            continue
                        raise
                    fetched.append((c_target, sub_res))

                (
                    matches,
                    alternatives,
                    cuisines_breakdown,
                    hidden,
                ) = self._logic.merge_multi_cuisine_results(
                    fetched, len(selected_cuisines), max_total=20)
                if not matches and not alternatives and last_empty_error is not None:
                    raise last_empty_error

                summary_req = dict(base_request or {})
                summary_req["cuisine"] = ", ".join(selected_cuisines)
                self._brns.save_history_summary(
                    owner,
                    summary_req,
                    {"matches": matches, "alternatives": alternatives},
                    "live-google",
                )

            return {
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
        except RuntimeError as exc:
            if self._is_no_open_error(exc):
                return {
                    "success": True,
                    "confirmation_required": False,
                    "origin": origin,
                    "input_origins": resolved_origins,
                    "origins": resolved_origins,
                    "selected_cuisines": selected_cuisines,
                    "cuisines_breakdown": cuisines_breakdown,
                    "matches": [],
                    "alternatives": [],
                    "exclusions_count": 0,
                    "model_used": self._model() or "AI provider unavailable",
                    "message": (
                        "No open restaurants found near this location right now. "
                        "Note: In Singapore, many mall outlets close after 10:00 PM. "
                        "Try searching a 24-hour hotspot (e.g. 'Rivervale Plaza' or 'Jewel Changi') "
                        "or increasing travel limits."
                    ),
                }
            raise

    def search(self, user, payload):
        owner = user["userID"] if user else None
        token = payload.get("confirmation_token")
        if token:
            proposal = self._data.consume_search_proposal(owner, token)
            request = (
                proposal["request"]
                if isinstance(proposal, dict) and "request" in proposal
                else proposal
            )
            resolved_origins = (
                proposal.get("resolved_origins")
                if isinstance(proposal, dict) and "resolved_origins" in proposal
                else [request["origin"]]
            )
            selected_cuisines = (
                proposal.get("selected_cuisines")
                if isinstance(proposal, dict) and "selected_cuisines" in proposal
                else (
                    [request["cuisine"]]
                    if request.get("cuisine") and request.get("cuisine") != "none"
                    else []
                )
            )
            return self._run_search(
                owner,
                payload,
                request["origin"],
                resolved_origins,
                selected_cuisines,
                first_request=request,
            )

        raw_locations = self._logic.collect_search_locations(payload)
        origin, resolved_origins = self._resolve_origins(raw_locations)
        selected_cuisines = self._logic.collect_search_cuisines(payload)

        if payload.get("confirm_only"):
            single_c = selected_cuisines[0] if len(selected_cuisines) == 1 else None
            request = self._build_validated_request(payload, origin, single_c)
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

        return self._run_search(
            owner, payload, origin, resolved_origins, selected_cuisines)

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
