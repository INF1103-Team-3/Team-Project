"""Complete MUIS directory snapshot domain model."""

from datetime import datetime, timedelta, timezone

from BRC.classes.data.models.common.model_constants import SOURCE_URL
from BRC.classes.data.models.muis.muis_listing import MuisListing


class MuisSnapshot:
    """Represent a complete, timestamped MUIS directory download."""

    MAX_AGE = timedelta(days=7)

    def __init__(self, listings, fetched_at, postal_prefixes,
                 source_url=SOURCE_URL, geocoded=True):
        self._listings = list(listings)
        self._fetched_at = fetched_at
        self._postal_prefixes = list(postal_prefixes)
        self._source_url = source_url
        self._geocoded = geocoded

    @property
    def listings(self):
        return list(self._listings)

    @property
    def fetched_at(self):
        return self._fetched_at

    @property
    def source_url(self):
        return self._source_url

    @classmethod
    def create(cls, listings, postal_prefixes, geocoded):
        ordered = sorted(listings, key=lambda row: (
            row.name.casefold(), row.postal_code, row.certificate_number))
        fetched_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        return cls(
            ordered, fetched_at, postal_prefixes, geocoded=geocoded)

    @classmethod
    def from_dict(cls, value):
        listings = value.get("listings") if isinstance(value, dict) else None
        complete = (
            isinstance(listings, list) and len(listings) > 0
            and value.get("complete") is True
            and value.get("coverage") == "all_eating_establishments"
            and value.get("source_url") == SOURCE_URL
            and cls.covers_all_postal_codes(value.get("postal_prefixes"))
            and value.get("listing_count") == len(listings)
            and isinstance(value.get("fetched_at"), str))
        if not complete:
            raise ValueError("MUIS raw data is incomplete or invalid.")
        geocoded = any("latitude" in row for row in listings)
        return cls(
            [MuisListing.from_dict(row) for row in listings],
            value["fetched_at"], value["postal_prefixes"],
            value["source_url"], geocoded)

    def to_dict(self):
        return {
            "source_url": self._source_url,
            "fetched_at": self._fetched_at,
            "complete": True,
            "coverage": "all_eating_establishments",
            "postal_prefixes": list(self._postal_prefixes),
            "listing_count": len(self._listings),
            "listings": [
                row.to_dict(self._geocoded) for row in self._listings],
        }

    def validate(self, current=True):
        if (not self.covers_all_postal_codes(self._postal_prefixes)
                or not self._listings or self._source_url != SOURCE_URL
                or not isinstance(self._fetched_at, str)):
            raise ValueError("MUIS raw data is incomplete or invalid.")
        try:
            fetched = datetime.fromisoformat(self._fetched_at)
        except ValueError as error:
            raise ValueError(
                "MUIS raw data has an invalid retrieval time.") from error
        now = datetime.now(timezone.utc)
        if fetched.tzinfo is None or fetched > now + timedelta(minutes=5):
            raise ValueError("MUIS raw data has an invalid retrieval time.")
        if current and now - fetched > self.MAX_AGE:
            raise ValueError("MUIS raw data is older than seven days.")
        return self

    @staticmethod
    def covers_all_postal_codes(prefixes):
        if not isinstance(prefixes, list) or not all(
                isinstance(prefix, str) and prefix.isdigit()
                and 1 <= len(prefix) <= 6 for prefix in prefixes):
            return False
        searched = set(prefixes)

        def covered(prefix=""):
            if prefix in searched:
                return True
            if len(prefix) == 6:
                return False
            return all(covered(prefix + digit) for digit in "0123456789")

        return covered()
