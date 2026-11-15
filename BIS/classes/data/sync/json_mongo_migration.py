"""Explicit, idempotent import of approved JSON records into a chosen database."""
import json
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
from BIS.sources.profile_schema import validate_user


class JsonMongoMigration:
    @staticmethod
    def _read(path):
        if path is None:
            return None
        path = Path(path)
        if any(part.lower() in ('secrets', '.env') for part in path.parts):
            raise ValueError("Secret paths cannot be migration inputs.")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("A selected JSON input is missing or corrupt.") from error

    def prepare(self, users=None, states=None, restaurants=None, history=None):
        records = {"users": [], "profile_state": [], "restaurants": [], "search_history": []}
        value = self._read(users)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError("Users input must be a BIS registry object.")
            emails = set()
            for user_id, raw in value.items():
                user = validate_user(raw, clamp_legacy_limits=True)
                if user_id != user["userID"] or user["email"] in emails:
                    raise ValueError("Users input contains conflicting identities.")
                emails.add(user["email"])
                records["users"].append(dict(user, _id=user_id))
        value = self._read(states)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError("States input must be a BIS state object.")
            for section, users_state in value.items():
                if not isinstance(users_state, dict):
                    raise ValueError("State sections must be objects keyed by userID.")
                for user_id, state in users_state.items():
                    if not isinstance(state, dict):
                        raise ValueError("Workflow states must be objects.")
                    records["profile_state"].append({"_id": str(uuid5(NAMESPACE_URL, json.dumps([section, user_id]))),
                                                    "section": section, "user_id": user_id, "value": state})
        value = self._read(restaurants)
        if value is not None:
            if not isinstance(value, list):
                raise ValueError("Restaurants input must be an array.")
            seen = set()
            for row in value:
                key = row.get("google_place_id") if isinstance(row, dict) else None
                if not isinstance(key, str) or not key.strip() or key in seen or not row.get("name"):
                    raise ValueError("Restaurants need unique Google place IDs and names.")
                seen.add(key)
                records["restaurants"].append(dict(row, _id=key))
        value = self._read(history)
        if value is not None:
            if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
                raise ValueError("History input must be an array of objects.")
            for index, row in enumerate(value):
                key = str(uuid5(NAMESPACE_URL, json.dumps(row, sort_keys=True) + ':' + str(index)))
                # Existing JSON summaries have no user attribution; do not invent one.
                records["search_history"].append(dict(row, _id=key))
        return records

    @staticmethod
    def counts(records):
        return {collection: len(rows) for collection, rows in records.items()}

    def apply(self, connection, records):
        # Refuse conflicting existing records before starting writes. Never replace.
        for collection, rows in records.items():
            for row in rows:
                current = connection.execute(lambda db: db[collection].find_one({"_id": row["_id"]}))
                if collection == "users":
                    by_email = connection.execute(lambda db: db.users.find_one({"email": row["email"]}))
                    if by_email is not None and by_email["_id"] != row["_id"]:
                        raise ValueError("Migration email conflicts with an existing identity.")
                if current is not None and current != row:
                    raise ValueError("Migration conflicts with an existing record; no overwrite is allowed.")
        for collection, rows in records.items():
            for row in rows:
                connection.execute(lambda db: db[collection].update_one(
                    {"_id": row["_id"]}, {"$setOnInsert": row}, upsert=True))
        return self.counts(records)
