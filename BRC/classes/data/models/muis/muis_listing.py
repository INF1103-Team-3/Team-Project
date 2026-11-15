"""Domain model for one official MUIS directory row."""

import re

from BRC.classes.data.models.common.address import Address
from BRC.classes.data.models.common.model_constants import EATING_ESTABLISHMENT, SOURCE_URL


class MuisListing:
    """Represent one validated MUIS eating-establishment listing."""

    FIELDS = (
        "listing_id", "certificate_number", "name", "address",
        "postal_code", "scheme", "category", "status", "valid_until",
        "source_url")
    REQUIRED = (
        "certificate_number", "name", "address", "postal_code", "scheme")

    def __init__(self, data):
        self._data = {field: data.get(field) for field in self.FIELDS}
        self._latitude = data.get("latitude")
        self._longitude = data.get("longitude")

    @classmethod
    def from_api_row(cls, row, query):
        if not isinstance(row, dict):
            raise ValueError(
                f"MUIS returned a malformed listing for {query!r}.")
        if row.get("schemeText") != EATING_ESTABLISHMENT:
            return None
        for key in ("name", "address", "postal", "number"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(
                    f"MUIS returned an incomplete listing for {query!r}.")
        postal = row["postal"].strip()
        if not re.fullmatch(r"\d{6}", postal):
            raise ValueError(
                f"MUIS returned an invalid postal code for {query!r}.")
        return cls({
            "listing_id": row.get("id"),
            "certificate_number": row["number"].strip(),
            "name": row["name"].strip(),
            "address": row["address"].strip(),
            "postal_code": postal,
            "scheme": row["schemeText"],
            "category": row.get("subSchemeText"),
            "status": "listed",
            "valid_until": row.get("expiryDate"),
            "source_url": SOURCE_URL,
        })

    @classmethod
    def from_dict(cls, row):
        valid = isinstance(row, dict) and all(
            isinstance(row.get(field), str) and row[field]
            for field in cls.REQUIRED)
        if not valid or not re.fullmatch(r"\d{6}", row["postal_code"]):
            raise ValueError("MUIS raw data contains an invalid outlet.")
        listing = cls(row)
        listing._data["status"] = row.get("status", "listed")
        listing._data["source_url"] = row.get("source_url", SOURCE_URL)
        return listing

    def __getattr__(self, name):
        if name in {
                "certificate_number", "name", "address", "postal_code",
                "scheme", "listing_id", "category", "valid_until"}:
            return self._data[name]
        raise AttributeError(name)

    @property
    def latitude(self):
        return self._latitude

    @property
    def longitude(self):
        return self._longitude

    def with_coordinates(self, latitude, longitude):
        return MuisListing({
            **self._data, "latitude": latitude, "longitude": longitude})

    def to_dict(self, geocoded=True):
        data = dict(self._data)
        if geocoded:
            data["latitude"] = self._latitude
            data["longitude"] = self._longitude
        return data

    @property
    def crawl_identity(self):
        address = re.sub(r"\s+", " ", self.address).casefold()
        return "|".join((
            str(self.listing_id or ""), self.certificate_number,
            self.postal_code, address))

    @property
    def cuisine_cache_key(self):
        identity = self.listing_id or self.certificate_number or "unknown"
        return (
            f"{identity}|{Address.normalise(self.name or '')}|"
            f"{Address.normalise(self.category or '')}")
