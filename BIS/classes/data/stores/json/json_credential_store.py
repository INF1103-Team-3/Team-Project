"""JSON-backed password credential persistence matching MongoCredentialStore."""

from BIS.classes.data.stores.contracts.base_json_store import BaseJsonStore


class JsonCredentialStore(BaseJsonStore):
    """Persist salted PBKDF2 password credentials in a separate JSON object file."""

    def load(self):
        return self._read_json(self._records_path)

    def get(self, user_id):
        if not isinstance(user_id, str) or not user_id:
            return None
        row = self.load().get(user_id)
        if row is None:
            return None
        if not isinstance(row, dict):
            raise RuntimeError("Saved credentials are invalid; restore the file.")
        return dict(row)

    def save(self, user_id, credential):
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("A valid userID is required for credentials.")
        if not isinstance(credential, dict):
            raise ValueError("Credential record must be an object.")
        records = self.load()
        records[user_id] = dict(credential)
        self._atomic_write(self._records_path, records)
