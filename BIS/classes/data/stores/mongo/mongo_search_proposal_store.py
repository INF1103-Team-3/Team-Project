"""One-use, expiring confirmations of the exact AI-interpreted search request."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone


class MongoSearchProposalStore:
    def __init__(self, connection):
        self._connection = connection

    def ensure_indexes(self):
        self._connection.execute(lambda db: db.search_proposals.create_index("expires_at", expireAfterSeconds=0))

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def create(self, owner, request):
        token = secrets.token_urlsafe(32)
        self._connection.execute(lambda db: db.search_proposals.insert_one({
            "_id": self._key(token), "owner": owner, "request": request,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)}))
        return token

    def consume(self, owner, token):
        row = self._connection.execute(lambda db: db.search_proposals.find_one_and_delete({
            "_id": self._key(token), "owner": owner,
            "expires_at": {"$gt": datetime.now(timezone.utc)}}))
        if not row:
            raise ValueError("Search confirmation expired or was already used. Submit the form again.")
        return row["request"]
