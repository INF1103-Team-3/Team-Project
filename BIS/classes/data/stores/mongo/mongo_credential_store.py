"""Web credential persistence, separate from domain users and JSON exports."""


class MongoCredentialStore:
    def __init__(self, connection):
        self._connection = connection

    def get(self, user_id):
        row = self._connection.execute(lambda db: db.web_credentials.find_one({"_id": user_id}))
        return {k: v for k, v in row.items() if k != "_id"} if row else None

    def save(self, user_id, credential):
        self._connection.execute(lambda db: db.web_credentials.replace_one(
            {"_id": user_id}, dict(credential, _id=user_id), upsert=True))
