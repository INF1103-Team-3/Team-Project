"""Web authentication coordinated with the existing BIS verification service."""
import time
from threading import RLock
from BIS.sources.profile_schema import normalize_email, normalize_username


class WebAuthService:
    def __init__(self, data, verification, hasher, config, clock=time.time):
        self._lock = RLock()
        self._data, self._verification, self._hasher = data, verification, hasher
        self._config, self._clock = config, clock

    def authenticate(self, token):
        user_id = self._data.resolve_session(token)
        if not user_id:
            raise PermissionError("Not authenticated or session expired.")
        return self._data.get_user(user_id)

    def _complete_bypass(self, user, pending):
        if pending.get("credential"):
            self._data.save_credentials(user["userID"], pending["credential"])
        updates = {}
        if pending.get("username") and pending["username"] != user["username"]:
            updates["username"] = pending["username"]
        if not user.get("email_verified"):
            updates["email_verified"] = True
        if updates:
            user = self._data.save(dict(user, **updates))
        self._data.set_state("web_auth", user["userID"], None)
        return {
            "success": True,
            "otp_required": False,
            "message": f"Welcome back, {user['username']}!",
            "token": self._data.issue_session(user["userID"]),
            "user": user,
        }

    def _send(self, user, pending):
        if self._config.get("smtp_bypass") is True:
            return self._complete_bypass(user, pending)
        pending = dict(pending, expires_at=self._clock() + 600)
        self._verification.request_code(user, self._config)
        self._data.set_state("web_auth", user["userID"], pending)
        return {"success": True, "otp_required": True, "email": user["email"],
                "message": "A verification code was sent to your email."}

    def register(self, email, username, password):
        with self._lock:
            return self._register(email, username, password)

    def _register(self, email, username, password):
        email, username = normalize_email(email), normalize_username(username)
        credential = self._hasher.create(password)
        if self._data.email_exists(email):
            user = self._data.find_user(email)
            if self._data.get_credentials(user["userID"]):
                raise ValueError("This email is already registered. Please sign in.")
        else:
            user = self._data.register_user(email, username)
        # An existing CLI identity is enrolled only AFTER proof of email ownership.
        return self._send(user, dict(credential=credential, username=username))

    def login(self, email, password):
        with self._lock:
            return self._login(email, password)

    def _login(self, email, password):
        try:
            user = self._data.find_user(normalize_email(email))
        except ValueError as error:
            raise PermissionError("Incorrect email or password.") from error
        credential = self._data.get_credentials(user["userID"])
        if credential:
            if not self._hasher.verify(password, credential):
                raise PermissionError("Incorrect email or password.")
            pending = {}
        else:
            pending = {"credential": self._hasher.create(password)}
        return self._send(user, pending)

    def verify(self, email, code):
        with self._lock:
            return self._verify(email, code)

    def _verify(self, email, code):
        user = self._data.find_user(normalize_email(email))
        pending = self._data.get_state("web_auth", user["userID"])
        if pending is None or pending["expires_at"] <= self._clock():
            raise ValueError("Request a new sign-in verification code.")
        user = self._verification.verify_code(user, code, self._config)
        if pending.get("credential"):
            self._data.save_credentials(user["userID"], pending["credential"])
        if pending.get("username"):
            user = self._data.save(dict(user, username=pending["username"]))
        self._data.set_state("web_auth", user["userID"], None)
        return {"success": True, "otp_required": False,
                "token": self._data.issue_session(user["userID"]), "user": user}

    def resend(self, email):
        with self._lock:
            return self._resend(email)

    def _resend(self, email):
        user = self._data.find_user(normalize_email(email))
        pending = self._data.get_state("web_auth", user["userID"])
        if pending is None:
            raise ValueError("Start registration or sign in first.")
        return self._send(user, pending)

    def logout(self, token):
        self._data.revoke_session(token)
        return {"success": True, "message": "Signed out successfully."}
