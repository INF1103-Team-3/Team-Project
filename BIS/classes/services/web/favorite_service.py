"""User-owned bookmarks with stable restaurant identity."""
from threading import Lock


class FavoriteService:
    def __init__(self, data):
        self._data = data
        self._toggle_lock = Lock()

    @staticmethod
    def place_key(restaurant):
        key = restaurant.get("google_place_id") or restaurant.get("place_id")
        if key:
            return str(key)
        name = str(restaurant.get("name") or "").strip().lower()
        address = str(restaurant.get("address") or "").strip().lower()
        if not name or not address:
            raise ValueError("A favorite needs a place ID or restaurant name and address.")
        return name + "|" + address

    def list(self, user):
        return {"favorites": self._data.load_favorites(user["userID"])}

    def toggle(self, user, restaurant):
        with self._toggle_lock:
            return self._toggle(user, restaurant)

    def _toggle(self, user, restaurant):
        key = self.place_key(restaurant)
        current = self._data.load_favorites(user["userID"])
        if any(row["place_key"] == key for row in current):
            self._data.delete_favorite(user["userID"], key)
            return {"success": True, "favorited": False, "place_key": key}
        self._data.save_favorite(user["userID"], key, restaurant)
        return {"success": True, "favorited": True, "place_key": key}

    def delete(self, user, key):
        self._data.delete_favorite(user["userID"], key)
        return {"success": True}
