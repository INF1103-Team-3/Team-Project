"""Cache of AI-derived cuisine tags."""


class CuisineCache:
    """Retain cuisine tags keyed by stable MUIS listing identity."""

    def __init__(self, tags=None):
        self._tags = {
            key: list(value) for key, value in (tags or {}).items()}

    def __contains__(self, listing):
        return listing.cuisine_cache_key in self._tags

    def __len__(self):
        return len(self._tags)

    def get(self, listing):
        value = self._tags.get(listing.cuisine_cache_key)
        return list(value) if value is not None else None

    def put(self, listing, tags):
        self._tags[listing.cuisine_cache_key] = list(tags)

    def to_dict(self):
        return {key: list(value) for key, value in self._tags.items()}
