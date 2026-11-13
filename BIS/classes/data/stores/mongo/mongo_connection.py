"""Own a lazily connected Mongo client and translate backend errors safely."""
import os
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError


class MongoConnection:
    def __init__(self, uri=None, database=None, client=None):
        self._client = client if client is not None else MongoClient(
            uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
            serverSelectionTimeoutMS=2000, connectTimeoutMS=2000,
            socketTimeoutMS=10000, tz_aware=True)
        self.db = self._client[database or os.getenv("MONGO_DATABASE", "bitefinder")]

    def execute(self, operation):
        try:
            return operation(self.db)
        except DuplicateKeyError as error:
            raise ValueError("A record with this identity already exists.") from None
        except PyMongoError as error:
            raise RuntimeError("MongoDB is unavailable; no alternate storage was used.") from None

    def ready(self):
        return self.execute(lambda _db: self._client.admin.command("ping"))["ok"] == 1

    def close(self):
        self._client.close()
