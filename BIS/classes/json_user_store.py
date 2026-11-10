"""JSON-backed account and profile-state persistence for BIS."""

from pathlib import Path
from uuid import uuid4

from BIS.classes.base_json_store import BaseJsonStore
from BIS.classes.record_store_interface import RecordStoreInterface
from shared.debug_log import debug_log
from sources.profile_schema import (
    MINUTES_PER_KM,
    empty_preferences,
    normalize_email,
    normalize_username,
    validate_preferences,
    validate_user,
)


class JsonUserStore(BaseJsonStore, RecordStoreInterface):
    """Persist compatible BIS account and profile-state JSON records."""

    def __init__(self, users_path, state_path):
        super().__init__(users_path)
        self.__state_path = Path(state_path)
        self.__last_error = None

    @property
    def last_error(self):
        return self.__last_error

    def registry(self):
        users = self._read_json(self._records_path)
        emails = set()
        for user_id, user in users.items():
            if not isinstance(user_id, str) or not user_id or (
                    not isinstance(user, dict)
                    or user.get("userID") != user_id):
                raise ValueError(
                    "Invalid user record in data/users.json; saved data was "
                    "retained. Restore a valid copy before writing."
                )
            users[user_id] = validate_user(user)
            email = users[user_id]["email"]
            if email in emails:
                raise ValueError(
                    "Duplicate saved emails; restore the user file.")
            emails.add(email)
        return users

    def load(self):
        try:
            records = list(self.registry().values())
        except (ValueError, RuntimeError) as error:
            self.__last_error = str(error)
            debug_log(
                "Registry read failed; writes blocked.",
                "ERROR", "BIS.data.load",
            )
            return []
        self.__last_error = None
        return records

    def query(self, filter_fn):
        return [record for record in self.load() if filter_fn(record)]

    def save(self, record):
        record = validate_user(record)
        users = self.registry()
        if any(
            user["email"] == record["email"] and key != record["userID"]
            for key, user in users.items()
        ):
            raise ValueError("This email is already registered.")
        users[record["userID"]] = record
        self._atomic_write(self._records_path, users)
        debug_log("User record saved.", "INFO", "BIS.data.save")
        return record

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

    def get_state(self, section, user_id):
        state = self._read_json(self.__state_path)
        values = state.get(section, {})
        if not isinstance(values, dict):
            raise RuntimeError(
                "Invalid internal profile state. Restore the file.")
        value = values.get(user_id)
        if value is not None and not isinstance(value, dict):
            raise RuntimeError(
                "Invalid internal profile state. Restore the file.")
        return value

    def set_state(self, section, user_id, value):
        state = self._read_json(self.__state_path)
        if not isinstance(state.get(section, {}), dict):
            raise RuntimeError(
                "Invalid internal profile state. Restore the file.")
        values = state.setdefault(section, {})
        if value is None:
            values.pop(user_id, None)
        else:
            values[user_id] = value
        self._atomic_write(self.__state_path, state)
