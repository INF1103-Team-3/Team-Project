"""Adapter-independent BIS profile and confirmed-search use cases."""
from copy import deepcopy
from threading import Lock
from BIS.sources.profile_schema import PREFERENCE_FIELDS, normalize_username


class BISApplicationService:
    def __init__(self, data, ai, logic, brns, navigator, history, history_scope,
                 config, model_reader=lambda: None):
        self._data, self._ai, self._logic = data, ai, logic
        self._brns, self._navigator, self._history = brns, navigator, history
        self._history_scope, self._config, self._model = history_scope, config, model_reader
        self._search_lock = Lock()

    def save_profile(self, user, payload):
        if payload.get("user_id") not in (None, user["userID"]):
            raise PermissionError("A profile can only be changed by its owner.")
        if payload.get("email") not in (None, user["email"]):
            raise ValueError("Changing the verified email is not supported by this profile form.")
        if not user["email_verified"]:
            raise PermissionError("Verify your email before changing preferences.")
        updates = {key: payload[key] for key in PREFERENCE_FIELDS if key in payload}
        preferences = self._logic.apply_updates(user["preferences"], updates, "replace")
        # Saving a form is an explicit confirmation; use the same Logic/Data operations as CLI.
        username = normalize_username(payload.get("username") or user["username"])
        return self._data.save(dict(user, username=username, preferences=preferences))

    def _prepare_search(self, payload):
        locations = payload.get("locations") or [payload.get("location", "")]
        cuisines = payload.get("liked_cuisines") or []
        if len(locations) != 1 or len(cuisines) > 1:
            raise ValueError("Choose one origin and one cuisine for the OOP search.")
        origin = self._data.resolve_location(locations[0], self._config.get("google_maps_api_key"))
        cuisine = payload.get("cuisine") or (cuisines[0] if cuisines else "none")
        request = {"origin": origin, "mode": payload["mode"],
                   "max_distance_km": payload.get("max_distance_km"),
                   "max_travel_minutes": payload.get("max_travel_minutes"),
                   "traffic_aware": payload.get("traffic_aware", False),
                   "cuisine": cuisine.lower(), "budget_per_person": payload["budget_per_person"],
                   "other_preferences": payload.get("other_preferences", []),
                   "dietary_requirements": payload.get("dietary_requirements", []),
                   "disliked_cuisines": payload.get("disliked_cuisines", [])}
        request = self._logic.validate_search_request(request)
        config = deepcopy(self._config)
        wishes = ", ".join(request["other_preferences"])
        interpreted = self._ai.interpret_search_request(request, wishes, config)
        return self._logic.preserve_search_wish(
            request, self._logic.validate_search_request(request, interpreted), wishes)

    def search(self, user, payload):
        owner = user["userID"] if user else None
        if not self._search_lock.acquire(timeout=2):
            raise RuntimeError("Another search is in progress. Please retry shortly.")
        try:
            token = payload.get("confirmation_token")
            if not token:
                request = self._prepare_search(payload)
                return {"success": True, "confirmation_required": True, "request": request,
                        "confirmation_token": self._data.create_search_proposal(owner, request)}
            request = self._data.consume_search_proposal(owner, token)
            with self._history_scope.for_user(owner):
                results = self._brns.search(self._data.serialize_search_request(request))
            return {"success": True, "confirmation_required": False,
                    "origin": request["origin"], "origins": [request["origin"]],
                    "selected_cuisines": [request["cuisine"]], "cuisines_breakdown": {},
                    "matches": results["matches"], "alternatives": results["alternatives"],
                    "exclusions_count": results["hidden"],
                    "model_used": self._model() or "AI provider unavailable"}
        finally:
            self._search_lock.release()

    def route(self, payload):
        request = {"origin": {"latitude": payload["origin_lat"], "longitude": payload["origin_lng"]},
                   "mode": payload["mode"], "traffic_aware": payload["traffic_aware"]}
        restaurant = {"name": payload["name"], "lat": payload["dest_lat"], "lng": payload["dest_lng"]}
        return self._navigator.route_to(restaurant, request)

    def history(self, user):
        rows = self._history.load_user_history(user["userID"])
        result = []
        for row in rows:
            req = row.get("request", {})
            result.append(dict(req, id=str(row["_id"]), timestamp=row.get("timestamp"),
                               query=req.get("origin", {}).get("query", ""),
                               locations=[req.get("origin", {}).get("query", "")],
                               matches_count=row.get("matches_count", 0),
                               alternatives_count=row.get("alternatives_count", 0),
                               results_count=row.get("matches_count", 0) + row.get("alternatives_count", 0)))
        return {"history": result}

    def clear_history(self, user):
        self._history.clear_user_history(user["userID"])
        return {"success": True}
