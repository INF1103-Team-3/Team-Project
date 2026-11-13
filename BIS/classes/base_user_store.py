"""Storage-neutral BIS account operations using validated domain records."""
from abc import ABC, abstractmethod
from uuid import uuid4
from BIS.sources.profile_schema import (
    MINUTES_PER_KM, empty_preferences, normalize_email, normalize_username,
    validate_preferences,
)
from common.debug_log import debug_log


class BaseUserStore(ABC):
    @abstractmethod
    def registry(self):
        """Load validated users keyed by ID."""

    @abstractmethod
    def save(self, record):
        """Persist a validated user."""

    def query(self, filter_fn):
        return [record for record in self.load() if filter_fn(record)]

    def register_user(self, email, username):
        email = normalize_email(email)
        username = normalize_username(username)
        users = self.registry()
        if any(user["email"] == email for user in users.values()):
            raise ValueError(
                "This email is already registered. Choose resume.")
        user_id = str(uuid4())
        while user_id in users:
            user_id = str(uuid4())
        return self.save({
            "userID": user_id,
            "email": email,
            "email_verified": False,
            "username": username,
            "preferences": empty_preferences(),
        })

    def email_exists(self, email):
        email = normalize_email(email)
        return any(
            user["email"] == email for user in self.registry().values())

    def find_user(self, email):
        email = normalize_email(email)
        for user in self.registry().values():
            if user["email"] == email:
                return user
        raise ValueError(
            "No profile found for this email. Please sign up first.")

    def get_user(self, user_id):
        users = self.registry()
        if user_id not in users:
            raise ValueError("Unknown userID. Please sign up first.")
        return users[user_id]

    def save_preferences(self, user_id, preferences, config):
        user = self.get_user(user_id)
        if (not user["email_verified"]
                and config.get("smtp_bypass") is not True):
            raise ValueError(
                "Verify your email before changing preferences.")
        user["preferences"] = validate_preferences(preferences)
        result = self.save(user)
        debug_log(
            f"max_distance_km={preferences['max_distance_km']}, "
            f"max_travel_time_minutes="
            f"{preferences['max_travel_time_minutes']}; "
            f"conversion assumption={MINUTES_PER_KM} min/km.",
            "INFO", "BIS.profile.travel",
        )
        return result
