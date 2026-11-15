"""Persistence contract for lazily cached restaurant place photo blobs."""

from abc import ABC, abstractmethod


class PlacePhotoStoreInterface(ABC):
    """Store and retrieve cached thumbnail blobs keyed by place ID."""

    @abstractmethod
    def get_photo(self, place_id):
        """Return a cached photo record dict for place_id, or None."""

    @abstractmethod
    def save_photo(self, place_id, record):
        """Persist a photo record dict (or negative-cache marker) for place_id."""
