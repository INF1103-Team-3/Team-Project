"""Mongo persistence for the same BIS users and state as the JSON store."""
from BIS.classes.data.stores.contracts.base_user_store import BaseUserStore
from BIS.classes.data.stores.contracts.user_store_interface import UserStoreInterface
from BIS.classes.data.stores.contracts.record_store_interface import RecordStoreInterface
from BIS.sources.profile_schema import normalize_email, validate_user


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

    @staticmethod
    def _row_to_user(row):
        """Strip Mongo _id and validate/clamp persisted account records."""
        cleaned = {k: v for k, v in row.items() if k != "_id"}
        return validate_user(cleaned, clamp_legacy_limits=True)

    def registry(self):
        rows = self._connection.execute(lambda db: list(db.users.find({})))
        users = {}
        for row in rows:
            user = self._row_to_user(row)
            users[user["userID"]] = user
        return users

    def email_exists(self, email):
        """Check email membership via targeted query rather than full scan."""
        email = normalize_email(email)
        return bool(self._connection.execute(
            lambda db: db.users.find_one({"email": email}, {"_id": 1})
        ))

    def find_user(self, email):
        """Look up and validate only the requested user by normalized email."""
        email = normalize_email(email)
        row = self._connection.execute(
            lambda db: db.users.find_one({"email": email})
        )
        if row is None:
            raise ValueError(
                "No profile found for this email. Please sign up first.")
        return self._row_to_user(row)

    def get_user(self, user_id):
        """Look up and validate only the requested user by ID."""
        row = self._connection.execute(
            lambda db: db.users.find_one({"_id": user_id})
        )
        if row is None:
            raise ValueError("Unknown userID. Please sign up first.")
        return self._row_to_user(row)

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
