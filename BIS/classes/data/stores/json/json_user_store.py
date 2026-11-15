"""JSON-backed account and profile-state persistence for BIS."""

from pathlib import Path
from uuid import uuid4

from BIS.classes.data.stores.contracts.base_json_store import BaseJsonStore
from BIS.classes.data.stores.contracts.base_user_store import BaseUserStore
from BIS.classes.data.stores.contracts.record_store_interface import RecordStoreInterface
from BIS.classes.data.stores.contracts.user_store_interface import UserStoreInterface
from common.debug_log import debug_log
from sources.profile_schema import (
    MINUTES_PER_KM,
    empty_preferences,
    normalize_email,
    normalize_username,
    validate_preferences,
    validate_user,
)


class JsonUserStore(BaseUserStore, BaseJsonStore, UserStoreInterface, RecordStoreInterface):
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
            users[user_id] = validate_user(user, clamp_legacy_limits=True)
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
