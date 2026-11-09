"""MongoDB connection helper for BiteFinder."""

import os
from pymongo import MongoClient
from pymongo.database import Database

_CLIENT: MongoClient | None = None
_DEFAULT_URI = "mongodb://localhost:27017/"
_DB_NAME = "bitefinder"


def get_mongo_client() -> MongoClient:
    """Return a shared MongoClient instance."""
    global _CLIENT
    if _CLIENT is None:
        uri = os.getenv("MONGO_URI", _DEFAULT_URI)
        _CLIENT = MongoClient(uri, serverSelectionTimeoutMS=2000)
    return _CLIENT


def get_db() -> Database:
    """Return the BiteFinder MongoDB database."""
    client = get_mongo_client()
    return client[_DB_NAME]


def is_db_available() -> bool:
    """Check if MongoDB server is responding."""
    try:
        client = get_mongo_client()
        client.admin.command("ping")
        return True
    except Exception:
        return False

