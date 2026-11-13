"""User-isolated bookmark persistence."""


class MongoFavoriteStore:
    def __init__(self, connection):
        self._connection = connection

    def ensure_indexes(self):
        self._connection.execute(lambda db: db.favorites.create_index(
            [("user_id", 1), ("place_key", 1)], unique=True))

    def load(self, user_id):
        return self._connection.execute(lambda db: list(db.favorites.find(
            {"user_id": user_id}, {"_id": 0})))

    def set(self, user_id, key, restaurant):
        self._connection.execute(lambda db: db.favorites.update_one(
            {"user_id": user_id, "place_key": key},
            {"$set": {"restaurant": restaurant}}, upsert=True))

    def delete(self, user_id, key):
        return self._connection.execute(lambda db: db.favorites.delete_one(
            {"user_id": user_id, "place_key": key})).deleted_count
