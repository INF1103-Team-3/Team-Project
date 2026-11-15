"""MongoDB-backed cache for lazily fetched restaurant photo thumbnails."""

from datetime import datetime, timedelta, timezone

from BRNS.classes.data.stores.contracts.place_photo_store_interface import (
    PlacePhotoStoreInterface,
)

TTL_SECONDS = 60 * 60 * 24 * 30
NOT_FOUND_TTL = timedelta(hours=24)


class MongoPlacePhotoStore(PlacePhotoStoreInterface):
    """Persist photo blobs in the dedicated `place_photos` collection."""

    def __init__(self, connection):
        self._connection = connection

    def ensure_indexes(self):
        """Ensure a TTL index so cached place photos expire automatically."""
        self._connection.execute(
            lambda db: db.place_photos.create_index(
                [("cached_at", 1)],
                expireAfterSeconds=TTL_SECONDS,
            )
        )

    @staticmethod
    def _is_stale_missing(doc):
        if doc.get("status") != "not_found":
            return False
        cached_at = doc.get("cached_at")
        if not isinstance(cached_at, datetime):
            return False
        normalized = (
            cached_at
            if cached_at.tzinfo is not None
            else cached_at.replace(tzinfo=timezone.utc)
        )
        return datetime.now(timezone.utc) - normalized > NOT_FOUND_TTL

    def get_photo(self, place_id):
        """Return stored photo payload/status for place_id, or None when uncached."""
        doc = self._connection.execute(
            lambda db, pid=place_id: db.place_photos.find_one({"_id": pid})
        )
        if not isinstance(doc, dict) or self._is_stale_missing(doc):
            return None
        status = doc.get("status") or ("ok" if doc.get("data") else "not_found")
        if status == "not_found":
            return {"place_id": place_id, "status": "not_found"}
        raw = doc.get("data")
        if not raw:
            return None
        return {
            "place_id": place_id,
            "status": "ok",
            "data": bytes(raw),
            "content_type": doc.get("content_type") or "image/jpeg",
            "photo_name": doc.get("photo_name") or "",
            "author_attribution": doc.get("author_attribution") or "",
            "cached_at": doc.get("cached_at"),
        }

    def save_photo(self, place_id, record):
        """Upsert one photo blob or `not_found` marker in `place_photos`."""
        status = record.get("status") or ("ok" if record.get("data") else "not_found")
        raw = bytes(record.get("data") or b"") if status == "ok" else b""
        payload = {
            "_id": place_id,
            "status": status,
            "data": raw,
            "content_type": str(record.get("content_type") or "") if status == "ok" else "",
            "size_bytes": len(raw),
            "photo_name": str(record.get("photo_name") or ""),
            "author_attribution": str(record.get("author_attribution") or ""),
            "cached_at": datetime.now(timezone.utc),
        }
        self._connection.execute(
            lambda db, pid=place_id, item=payload: db.place_photos.replace_one(
                {"_id": pid}, item, upsert=True
            )
        )
        return True
