"""Adapter-independent BIS profile and search use cases."""
from copy import deepcopy
import math
from BIS.sources.profile_schema import CUISINES, PREFERENCE_FIELDS, normalize_username
from BIS.classes.bis_chatbot_service import BISChatbotService


class BISApplicationService:
    def __init__(self, data, ai, logic, brns, navigator, history, history_scope,
                 config, model_reader=lambda: None, chatbot=None):
        self._data, self._ai, self._logic = data, ai, logic
        self._brns, self._navigator, self._history = brns, navigator, history
        self._history_scope, self._config, self._model = history_scope, config, model_reader
        self._chatbot = chatbot or BISChatbotService(
            ai, logic, config, model_reader=model_reader, profile_saver=self.save_profile)

    def chat(self, user, payload):
        return self._chatbot.respond(user, payload)

    def save_profile(self, user, payload):
        if payload.get("user_id") not in (None, user["userID"]):
            raise PermissionError("A profile can only be changed by its owner.")
        if payload.get("email") not in (None, user["email"]):
            raise ValueError("Changing the verified email is not supported by this profile form.")
        if not user["email_verified"] and self._config.get("smtp_bypass") is not True:
            raise PermissionError("Verify your email before changing preferences.")
        updates = {key: payload[key] for key in PREFERENCE_FIELDS if key in payload}
        if "location" in updates and isinstance(updates["location"], list):
            updates["location"] = self._normalize_list_items(updates["location"], is_location=True)
        if "other_preferences" in updates and isinstance(updates["other_preferences"], list):
            updates["other_preferences"] = self._normalize_list_items(updates["other_preferences"], is_location=False)
        preferences = self._logic.apply_updates(user["preferences"], updates, "replace")
        # Saving a form is an explicit confirmation; use the same Logic/Data operations as CLI.
        username = normalize_username(payload.get("username") or user["username"])
        return self._data.save(dict(user, username=username, preferences=preferences))

    @staticmethod
    def _normalize_list_items(items, is_location=False):
        normalized = []
        for item in items:
            clean = str(item or "").strip()
            if not clean:
                continue
            if is_location and clean.isdigit():
                clean = f"Singapore {clean}"
            normalized.append(clean)
        return normalized

    @staticmethod
    def _collect_locations(payload):
        raw_locations = []
        for item in (payload.get("locations") or []):
            clean_loc = str(item or "").strip()
            if clean_loc and clean_loc not in raw_locations:
                raw_locations.append(clean_loc)
        primary = str(payload.get("location") or "").strip()
        if primary and primary not in raw_locations:
            raw_locations.insert(0, primary)
        if not raw_locations:
            raise ValueError("Please enter at least one starting location.")
        return raw_locations

    def _resolve_origins(self, raw_locations):
        api_key = self._config.get("google_maps_api_key")
        resolved = [self._data.resolve_location(loc, api_key) for loc in raw_locations]
        if len(resolved) == 1:
            return resolved[0], resolved, raw_locations[0]
        mid_lat = round(sum(o["latitude"] for o in resolved) / len(resolved), 6)
        mid_lng = round(sum(o["longitude"] for o in resolved) / len(resolved), 6)
        short_names = [o["query"] for o in resolved]
        history_query = " + ".join(short_names)[:200]
        midpoint = {
            "query": history_query,
            "label": f"Midpoint between {', '.join(short_names)}"[:500],
            "latitude": mid_lat,
            "longitude": mid_lng,
        }
        return midpoint, resolved, history_query

    @staticmethod
    def _collect_cuisines(payload):
        selected = []
        for raw_c in (payload.get("liked_cuisines") or []):
            for part in str(raw_c or "").split(","):
                clean = part.strip().lower()
                if clean and clean not in ("none", "any", "any cuisine") and clean not in selected:
                    selected.append(clean)
        single = payload.get("cuisine")
        if single:
            for part in str(single).split(","):
                clean = part.strip().lower()
                if clean and clean not in ("none", "any", "any cuisine") and clean not in selected:
                    selected.append(clean)
        return selected

    @staticmethod
    def _place_key(restaurant):
        if not isinstance(restaurant, dict):
            return ""
        pid = str(restaurant.get("google_place_id") or "").strip()
        if pid:
            return pid
        name = str(restaurant.get("name") or "").strip().lower()
        addr = str(restaurant.get("address") or "").strip().lower()
        return f"{name}|{addr}"

    def _build_validated_request(self, payload, origin, cuisine_target):
        minutes = payload.get("max_travel_minutes")
        distance = payload.get("max_distance_km")
        if minutes is not None and distance is not None:
            distance = None
        if minutes is None and distance is None:
            minutes = 20.0

        other_prefs = [
            str(p).strip() for p in (payload.get("other_preferences") or [])
            if str(p or "").strip()
        ]
        if not cuisine_target:
            cuisine_val = "none"
        elif cuisine_target in CUISINES:
            cuisine_val = cuisine_target
        else:
            cuisine_val = "none"
            custom_wish = f"{cuisine_target} cuisine"
            if custom_wish not in other_prefs:
                other_prefs = other_prefs + [custom_wish]

        disliked = [
            str(c).strip().lower() for c in (payload.get("disliked_cuisines") or [])
            if str(c or "").strip().lower() in CUISINES
        ]
        mode = payload.get("mode", "walk")
        traffic = bool(payload.get("traffic_aware", False) and mode == "drive" and minutes is not None)
        request = {
            "origin": origin,
            "mode": mode,
            "max_distance_km": distance,
            "max_travel_minutes": minutes,
            "traffic_aware": traffic,
            "cuisine": cuisine_val,
            "budget_per_person": payload["budget_per_person"],
            "other_preferences": other_prefs,
            "dietary_requirements": payload.get("dietary_requirements", []),
            "disliked_cuisines": disliked,
        }
        request = self._logic.validate_search_request(request)
        config = deepcopy(self._config)
        wishes = ", ".join(request["other_preferences"])
        interpreted = self._ai.interpret_search_request(request, wishes, config)
        return self._logic.preserve_search_wish(
            request, self._logic.validate_search_request(request, interpreted), wishes)

    def _prepare_search(self, payload):
        raw_locations = self._collect_locations(payload)
        origin, resolved_origins, _ = self._resolve_origins(raw_locations)
        selected_cuisines = self._collect_cuisines(payload)
        single_c = selected_cuisines[0] if len(selected_cuisines) == 1 else None
        request = self._build_validated_request(payload, origin, single_c)
        return request, resolved_origins, selected_cuisines

    @staticmethod
    def _is_no_open_error(exc):
        msg = str(exc)
        return "no restaurants found" in msg.lower() or "no confirmed open" in msg.lower()

    def _run_search(self, owner, payload, origin, resolved_origins, selected_cuisines, first_request=None):
        from BRNS import config as brns_config
        brns_config.MAX_MATCHES_SHOWN = 20
        brns_config.MAX_ALTERNATIVES_SHOWN = 20
        cuisines_breakdown = {}
        try:
            if len(selected_cuisines) <= 1:
                single_c = selected_cuisines[0] if selected_cuisines else None
                request = first_request or self._build_validated_request(payload, origin, single_c)
                with self._history_scope.for_user(owner):
                    results = self._brns.search(self._data.serialize_search_request(request))
                matches = results.get("matches", [])
                alternatives = results.get("alternatives", [])
                if single_c:
                    for item in matches + alternatives:
                        if isinstance(item, dict):
                            item["matched_cuisine"] = single_c
                    cuisines_breakdown[single_c] = len(matches) + len(alternatives)
                hidden = results.get("hidden", 0)
            else:
                num_cuisines = len(selected_cuisines)
                combined_matches, combined_alternatives = [], []
                seen_keys = set()
                last_empty_error = None
                total_hidden = 0
                base_request = None

                for c_target in selected_cuisines:
                    sub_request = self._build_validated_request(payload, origin, c_target)
                    if base_request is None:
                        base_request = sub_request
                    try:
                        with self._history_scope.for_user(None):
                            sub_res = self._brns.search(self._data.serialize_search_request(sub_request))
                    except RuntimeError as sub_exc:
                        if self._is_no_open_error(sub_exc):
                            last_empty_error = sub_exc
                            cuisines_breakdown[c_target] = 0
                            continue
                        raise
                    raw_m = [
                        dict(m, matched_cuisine=c_target)
                        for m in sub_res.get("matches", [])
                        if self._place_key(m.get("restaurant")) not in seen_keys
                    ]
                    raw_a = [
                        dict(a, matched_cuisine=c_target)
                        for a in sub_res.get("alternatives", [])
                        if self._place_key(a.get("restaurant")) not in seen_keys
                    ]
                    total_for_c = len(raw_m) + len(raw_a)
                    if total_for_c == 0:
                        cuisines_breakdown[c_target] = 0
                        continue
                    quota = min(
                        max(1, 20 // num_cuisines),
                        max(1, math.ceil(total_for_c / num_cuisines)),
                    )
                    taken_m = raw_m[:quota]
                    rem_slots = max(0, quota - len(taken_m))
                    taken_a = raw_a[:rem_slots]
                    for item in taken_m + taken_a:
                        seen_keys.add(self._place_key(item.get("restaurant")))
                    combined_matches.extend(taken_m)
                    combined_alternatives.extend(taken_a)
                    total_hidden += sub_res.get("hidden", 0)
                    cuisines_breakdown[c_target] = len(taken_m) + len(taken_a)

                if not combined_matches and not combined_alternatives and last_empty_error is not None:
                    raise last_empty_error

                matches, alternatives, hidden = combined_matches, combined_alternatives, total_hidden
                summary_req = dict(base_request or {})
                summary_req["cuisine"] = ", ".join(selected_cuisines)
                with self._history_scope.for_user(owner):
                    self._history.save_search_results(
                        summary_req, {"matches": matches, "alternatives": alternatives}, "live-google")

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
            request = proposal["request"] if isinstance(proposal, dict) and "request" in proposal else proposal
            resolved_origins = (
                proposal.get("resolved_origins") if isinstance(proposal, dict) and "resolved_origins" in proposal
                else [request["origin"]]
            )
            selected_cuisines = (
                proposal.get("selected_cuisines") if isinstance(proposal, dict) and "selected_cuisines" in proposal
                else ([request["cuisine"]] if request.get("cuisine") and request.get("cuisine") != "none" else [])
            )
            return self._run_search(
                owner, payload, request["origin"], resolved_origins, selected_cuisines, first_request=request)

        raw_locations = self._collect_locations(payload)
        origin, resolved_origins, _ = self._resolve_origins(raw_locations)
        selected_cuisines = self._collect_cuisines(payload)

        if payload.get("confirm_only"):
            single_c = selected_cuisines[0] if len(selected_cuisines) == 1 else None
            request = self._build_validated_request(payload, origin, single_c)
            proposal_token = self._data.create_search_proposal(owner, {
                "request": request,
                "resolved_origins": resolved_origins,
                "selected_cuisines": selected_cuisines,
            })
            return {
                "success": True,
                "confirmation_required": True,
                "request": request,
                "confirmation_token": proposal_token,
            }

        return self._run_search(owner, payload, origin, resolved_origins, selected_cuisines)

    def route(self, payload):
        request = {"origin": {"latitude": payload["origin_lat"], "longitude": payload["origin_lng"]},
                   "mode": payload["mode"], "traffic_aware": payload["traffic_aware"]}
        restaurant = {"name": payload["name"], "lat": payload["dest_lat"], "lng": payload["dest_lng"]}
        return self._navigator.route_to(restaurant, request)

    def history(self, user):
        rows = self._history.load_user_history(user["userID"])
        result = []
        for row in rows:
            req = row.get("request") or {}
            query_str = row.get("query") or req.get("origin", {}).get("query", "")
            locs = row.get("locations") or (
                [s.strip() for s in str(query_str).split(" + ") if s.strip()]
                if query_str else []
            )
            cuisine_val = row.get("cuisine") or req.get("cuisine") or ""
            liked = row.get("liked_cuisines") or (
                [c.strip() for c in str(cuisine_val).split(",") if c.strip() and c.strip() != "none"]
                if cuisine_val else []
            )
            matches_cnt = row.get("matches_count", 0)
            alts_cnt = row.get("alternatives_count", 0)
            result.append(dict(
                req,
                id=str(row["_id"]),
                timestamp=row.get("timestamp", ""),
                query=query_str,
                locations=locs,
                cuisine="" if cuisine_val == "none" else cuisine_val,
                liked_cuisines=liked,
                matches_count=matches_cnt,
                alternatives_count=alts_cnt,
                results_count=row.get("results_count", matches_cnt + alts_cnt),
            ))
        return {"history": result}

    def clear_history(self, user):
        self._history.clear_user_history(user["userID"])
        return {"success": True}
