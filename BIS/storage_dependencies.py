"""Lazy process-level connection wiring for standalone Mongo-backed CLI mode."""
import atexit
from functools import lru_cache


@lru_cache(maxsize=1)
def mongo_connection():
    from BIS.classes.mongo_connection import MongoConnection
    connection = MongoConnection()
    atexit.register(connection.close)
    return connection
