"""HTTP input and response formatting for BIS; delegates application decisions."""
from BIS.sources.profile_schema import CUISINES


class WebIOManager:
    def __init__(self, data, auth, application, favorites, health,
                 active_model_reader=lambda: "Gemini AI"):
        self._data, self._auth, self._application = data, auth, application
        self._favorites, self._health = favorites, health
        self._active_model_reader = active_model_reader

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

    def route(self, payload):
        return dict(self._application.route(payload), success=True)

    def favorites(self, authorization):
        user = self.user(authorization, required=False)
        return self._favorites.list(user) if user else {"favorites": []}

    def toggle_favorite(self, authorization, payload):
        return self._favorites.toggle(self.user(authorization), payload["restaurant"])

    def delete_favorite(self, authorization, key):
        return self._favorites.delete(self.user(authorization), key)

    def history(self, authorization):
        user = self.user(authorization, required=False)
        return self._application.history(user) if user else {"history": []}

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
