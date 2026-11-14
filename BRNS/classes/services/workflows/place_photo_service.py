"""Lazy read-through caching service for restaurant pin photos."""

import threading

from BRNS.classes.io.gateways.google.google_place_photo_gateway import (
    GooglePlacePhotoGateway,
)


class PlacePhotoService:
    """Serve cached place photo blobs or fetch-and-persist on first request."""

    def __init__(self, store, gateway, logger):
        self._store = store
        self._gateway = gateway
        self._log = logger
        self._locks = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, place_id):
        with self._locks_guard:
            lock = self._locks.get(place_id)
            if lock is None:
                if len(self._locks) > 512:
                    self._locks.clear()
                lock = threading.Lock()
                self._locks[place_id] = lock
            return lock

    @staticmethod
    def _format_hit(record):
        return {
            "data": record["data"],
            "content_type": record.get("content_type") or "image/jpeg",
            "author_attribution": record.get("author_attribution") or "",
        }

    def get_or_fetch_photo(self, place_id):
        """Return photo bytes from store or fetch from Google and persist on miss."""
        clean_id = GooglePlacePhotoGateway.validate_place_id(place_id)
        cached = self._store.get_photo(clean_id)
        if cached is not None:
            if cached.get("status") == "ok":
                self._log.debug_log(
                    "Place photo cache hit.", "DEBUG", "BRNS.place_photo.cache_hit"
                )
                return self._format_hit(cached)
            return None

        with self._lock_for(clean_id):
            cached = self._store.get_photo(clean_id)
            if cached is not None:
                return self._format_hit(cached) if cached.get("status") == "ok" else None

            fetched = self._gateway.fetch_photo(clean_id)
            if fetched is None:
                return None
            if fetched.get("status") == "not_found":
                self._store.save_photo(clean_id, fetched)
                return None
            if fetched.get("status") == "ok" and fetched.get("data"):
                self._store.save_photo(clean_id, fetched)
                return self._format_hit(fetched)
            return None
