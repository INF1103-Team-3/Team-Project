"""No-op place photo store for CLI/JSON mode when MongoDB is unavailable."""

from BRNS.classes.data.stores.contracts.place_photo_store_interface import (
    PlacePhotoStoreInterface,
)


class NullPlacePhotoStore(PlacePhotoStoreInterface):
    """Act as an uncached stand-in so non-Mongo runtimes share one contract."""

    def get_photo(self, place_id):
        """Always report a cache miss when binary Mongo storage is disabled."""
        return None

    def save_photo(self, place_id, record):
        """Accept writes without persisting binary image payloads to JSON files."""
        return False
