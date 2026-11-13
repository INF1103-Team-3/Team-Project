"""Two-way synchronization between MongoDB users and BIS CLI data/users.json."""
import json
from pathlib import Path
from threading import RLock
from BIS.sources.profile_schema import CUISINES, empty_preferences, normalize_email, validate_user


class CliUserFileSync:
    """Keep MongoDB user profiles synchronized with the CLI JSON registry."""

    _SKIP_EMAILS = {"webtest_suite_user@example.com"}

    def __init__(self, connection, users_path, logger=None):
        self._connection = connection
        self._users_path = Path(users_path)
        self._log = logger
        self._lock = RLock()
        self._last_mtime_ns = None

    def _warn(self, message):
        if self._log is not None:
            self._log.debug_log(message, "WARNING", "BIS.cli_user_file_sync")

    @staticmethod
    def _cli_preferences(preferences):
        pref = dict(preferences or {})
        liked = pref.get("liked_cuisines")
        disliked = pref.get("disliked_cuisines")
        return {
            **empty_preferences(),
            **pref,
            "liked_cuisines": (
                [c for c in liked if c in CUISINES] if isinstance(liked, list) else None
            ),
            "disliked_cuisines": (
                [c for c in disliked if c in CUISINES] if isinstance(disliked, list) else None
            ),
        }

    def sync_from_file(self, force=False):
        with self._lock:
            try:
                if not self._users_path.exists():
                    return
                stat = self._users_path.stat()
                if not force and self._last_mtime_ns == stat.st_mtime_ns:
                    return
                raw = json.loads(self._users_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    return
                seen_emails = set()
                for uid, entry in raw.items():
                    if not isinstance(entry, dict):
                        continue
                    candidate = dict(entry, userID=entry.get("userID") or uid)
                    try:
                        user = validate_user(candidate)
                    except ValueError:
                        continue
                    if user["email"] in seen_emails or user["email"] in self._SKIP_EMAILS:
                        continue
                    seen_emails.add(user["email"])
                    existing_by_email = self._connection.execute(
                        lambda db, e=user["email"]: db.users.find_one({"email": e})
                    )
                    if existing_by_email and existing_by_email.get("_id") != user["userID"]:
                        continue
                    existing = self._connection.execute(
                        lambda db, key=user["userID"]: db.users.find_one({"_id": key})
                    )
                    merged = dict(user, _id=user["userID"])
                    if existing and existing.get("email_verified"):
                        merged["email_verified"] = True
                    self._connection.execute(
                        lambda db, doc=merged: db.users.replace_one({"_id": doc["_id"]}, doc, upsert=True)
                    )
                self._last_mtime_ns = self._users_path.stat().st_mtime_ns
            except Exception as exc:
                self._warn(f"CLI->Mongo sync warning: {exc}")

    def sync_to_file(self, user):
        if not isinstance(user, dict):
            return
        try:
            email = normalize_email(user.get("email", ""))
        except ValueError:
            return
        if email in self._SKIP_EMAILS or email.endswith("@test.local"):
            return
        with self._lock:
            try:
                cli_users = {}
                if self._users_path.exists():
                    loaded = json.loads(self._users_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        cli_users = loaded
                uid = str(user.get("userID") or user.get("_id"))
                clean = validate_user({
                    "userID": uid,
                    "email": email,
                    "email_verified": bool(user.get("email_verified", False)),
                    "username": user.get("username"),
                    "preferences": self._cli_preferences(user.get("preferences")),
                })
                cli_users[uid] = clean
                self._users_path.parent.mkdir(parents=True, exist_ok=True)
                self._users_path.write_text(
                    json.dumps(cli_users, indent=4, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                self._last_mtime_ns = self._users_path.stat().st_mtime_ns
            except Exception as exc:
                self._warn(f"Mongo->CLI sync warning: {exc}")

