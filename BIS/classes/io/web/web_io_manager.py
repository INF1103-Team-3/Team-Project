"""HTTP input and response formatting for BIS; delegates application decisions."""
from BIS.classes.io.contracts.bis_web_io_interface import BISWebIOInterface
from BIS.sources.profile_schema import CUISINES


class WebIOManager(BISWebIOInterface):
    def __init__(self, auth, application, favorites, health,
                 active_model_reader=None):
        self._auth, self._application = auth, application
        self._favorites, self._health = favorites, health
        self._active_model_reader = active_model_reader or self._default_model_reader

    def _default_model_reader(self):
        reader = getattr(self._application, "active_model", None)
        return reader() if callable(reader) else "Gemini AI"

    @staticmethod
    def token(authorization):
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise PermissionError("Use a valid bearer session.")
        return token

    def user(self, authorization, required=True):
        token = self.token(authorization)
        if not token and not required:
            return None
        return self._auth.authenticate(token)

    @staticmethod
    def format_user(user):
        result = {"user_id": user["userID"], "username": user["username"],
                  "email": user["email"], "email_verified": user["email_verified"]}
        result.update(user["preferences"])
        for field in ("location", "dietary_requirements", "liked_cuisines",
                      "disliked_cuisines", "other_preferences"):
            result[field] = result[field] or []
        return result

    def health(self):
        return {"status": "ok", "mongodb": self._health()}

    def cuisines(self):
        return {"cuisines": list(CUISINES)}

    @staticmethod
    def _format_model_display(raw_model):
        clean = str(raw_model or "").strip()
        if not clean:
            return "Gemini AI"
        if "/" in clean:
            provider, model_name = clean.split("/", 1)
            p_lower = provider.lower()
            if p_lower == "gemini":
                return f"Gemini AI ({model_name})"
            if p_lower == "groq":
                return f"Groq AI ({model_name})"
            if p_lower == "openrouter":
                return f"OpenRouter AI ({model_name})"
        return clean

    def active_model(self):
        return {"active_model": self._format_model_display(self._active_model_reader())}

    def map_config(self):
        reader = getattr(self._application, "map_config", None)
        if callable(reader):
            return reader()
        return {"provider": "leaflet", "google_maps_api_key": ""}

    def register(self, payload):
        return self._auth.register(payload["email"], payload["username"], payload["password"])

    def login(self, payload):
        return self._auth.login(payload["email"], payload["password"])

    def verify(self, payload):
        result = self._auth.verify(payload["email"], payload["code"])
        return dict(result, user=self.format_user(result["user"]))

    def resend(self, payload):
        return self._auth.resend(payload["email"])

    def me(self, authorization):
        return {"authenticated": True, "user": self.format_user(self.user(authorization))}

    def logout(self, authorization):
        return self._auth.logout(self.token(authorization))

    def profile(self, authorization, user_id=None):
        user = self.user(authorization)
        if user_id not in (None, user["userID"]):
            raise PermissionError("A profile can only be read by its owner.")
        return self.format_user(user)

    def save_profile(self, authorization, payload):
        result = self._application.save_profile(self.user(authorization), payload)
        return {"success": True, "user": self.format_user(result)}

    def search(self, authorization, payload):
        return self._application.search(self.user(authorization, required=False), payload)

    def chat(self, authorization, payload):
        return self._application.chat(self.user(authorization, required=False), payload)

    def route(self, payload):
        return dict(self._application.route(payload), success=True)

    def place_photo(self, place_id):
        return self._application.place_photo(place_id)

    def favorites(self, authorization):
        user = self.user(authorization, required=False)
        return self._favorites.list(user) if user else {"favorites": []}

    def toggle_favorite(self, authorization, payload):
        return self._favorites.toggle(self.user(authorization), payload["restaurant"])

    def delete_favorite(self, authorization, key):
        return self._favorites.delete(self.user(authorization), key)

    @staticmethod
    def format_history(rows):
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
                [c.strip() for c in str(cuisine_val).split(",")
                 if c.strip() and c.strip() != "none"]
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

    def history(self, authorization):
        user = self.user(authorization, required=False)
        return (
            self.format_history(self._application.history(user))
            if user else {"history": []}
        )

    def recent(self, authorization):
        rows = self.history(authorization)["history"]
        seen, recent = set(), []
        for row in rows:
            query = row["query"].strip()
            if query and query.casefold() not in seen:
                seen.add(query.casefold())
                recent.append(query)
            if len(recent) == 6:
                break
        return {"recent": recent}

    def clear_history(self, authorization):
        return self._application.clear_history(self.user(authorization))
