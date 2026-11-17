"""Own a lazily connected Mongo client and translate backend errors safely."""

import os
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError


class MongoConnection:
    def __init__(self, uri=None, database=None, client=None):
        self.__client = (
            client
            if client is not None
            else MongoClient(
                uri or os.getenv("MONGO_URI", "mongodb://localhost:27017/"),
                serverSelectionTimeoutMS=2000,
                connectTimeoutMS=2000,
                socketTimeoutMS=10000,
                tz_aware=True,
            )
        )
        self.__db = self.__client[
            database or os.getenv("MONGO_DATABASE", "bitefinder")
        ]

    def execute(self, operation):
        try:
            return operation(self.__db)
        except DuplicateKeyError:
            raise ValueError(
                "A record with this identity already exists."
            ) from None
        except PyMongoError:
            raise RuntimeError(
                "MongoDB is unavailable; no alternate storage was used."
            ) from None

    def ready(self):
        return (
            self.execute(lambda _db: self.__client.admin.command("ping"))["ok"]
            == 1
        )

    def close(self):
        self.__client.close()
