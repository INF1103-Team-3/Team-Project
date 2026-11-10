"""Mongo persistence for the same BIS users and state as the JSON store."""
from BIS.classes.base_user_store import BaseUserStore
from BIS.classes.user_store_interface import UserStoreInterface
from BIS.classes.record_store_interface import RecordStoreInterface
from BIS.sources.profile_schema import validate_user


class MongoUserStore(BaseUserStore, UserStoreInterface, RecordStoreInterface):
    def __init__(self, connection):
        self._connection = connection
        self._last_error = None

    @property
    def last_error(self):
        return self._last_error

    def ensure_indexes(self):
        self._connection.execute(lambda db: db.users.create_index("email", unique=True))
        self._connection.execute(lambda db: db.profile_state.create_index(
            [("section", 1), ("user_id", 1)], unique=True))

    def registry(self):
        rows = self._connection.execute(lambda db: list(db.users.find({})))
        users = {}
        for row in rows:
            row = {k: v for k, v in row.items() if k != "_id"}
            user = validate_user(row)
            users[user["userID"]] = user
        return users

    def load(self):
        try:
            users = list(self.registry().values())
            self._last_error = None
            return users
        except (ValueError, RuntimeError) as error:
            self._last_error = str(error)
            raise

    def save(self, record):
        user = validate_user(record)
        self._connection.execute(lambda db: db.users.replace_one(
            {"_id": user["userID"]}, dict(user, _id=user["userID"]), upsert=True))
        return user

    def get_state(self, section, user_id):
        row = self._connection.execute(lambda db: db.profile_state.find_one(
            {"section": section, "user_id": user_id}))
        value = row.get("value") if row else None
        if value is not None and not isinstance(value, dict):
            raise RuntimeError("Invalid internal profile state. Restore the record.")
        return value

    def set_state(self, section, user_id, value):
        key = {"section": section, "user_id": user_id}
        if value is None:
            self._connection.execute(lambda db: db.profile_state.delete_one(key))
        elif isinstance(value, dict):
            self._connection.execute(lambda db: db.profile_state.update_one(
                key, {"$set": {"value": value}}, upsert=True))
        else:
            raise ValueError("Workflow state must be a dictionary or None.")
