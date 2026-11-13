"""Expiring bearer sessions; only a digest of each bearer is persisted."""
import hashlib
import secrets
import time
from datetime import datetime, timezone


class MongoSessionStore:
    def __init__(self, connection, clock=time.time, ttl=28800):
        self._connection, self._clock, self._ttl = connection, clock, ttl

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def ensure_indexes(self):
        self._connection.execute(lambda db: db.sessions.create_index("expires_at", expireAfterSeconds=0))

    def create(self, user_id):
        token = secrets.token_urlsafe(32)
        self._connection.execute(lambda db: db.sessions.insert_one({
            "_id": self._key(token), "user_id": user_id,
            "expires_at": datetime.fromtimestamp(self._clock() + self._ttl, timezone.utc)}))
        return token

    def resolve(self, token):
        if not token:
            return None
        row = self._connection.execute(lambda db: db.sessions.find_one({"_id": self._key(token)}))
        if not row:
            return None
        expires = row["expires_at"].replace(tzinfo=timezone.utc).timestamp()
        return row["user_id"] if self._clock() < expires else None

    def revoke(self, token):
        if token:
            self._connection.execute(lambda db: db.sessions.delete_one({"_id": self._key(token)}))
