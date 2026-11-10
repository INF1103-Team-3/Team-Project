"""Validated MUIS halal outlet domain model."""

import re

from BRC.classes.address import Address
from BRC.classes.certificate import Certificate


class HalalOutlet:
    """Own the address and certificate of one currently certified outlet."""

    def __init__(self, name, address, postal_code, certificate_data, cuisines,
                 latitude=None, longitude=None):
        self._name = name
        self._address = Address(address, postal_code)
        self._certificate = Certificate(certificate_data)
        self._cuisines = list(cuisines)
        self._latitude = latitude
        self._longitude = longitude

    @classmethod
    def from_listing(cls, listing, cuisines, snapshot):
        certificate = {
            "certificate_number": listing.certificate_number,
            "listing_id": listing.listing_id,
            "scheme": listing.scheme,
            "category": listing.category,
            "valid_until": listing.valid_until,
            "source_url": snapshot.source_url,
            "raw_fetched_at": snapshot.fetched_at,
        }
        return cls(
            listing.name, listing.address, listing.postal_code,
            certificate, cuisines, listing.latitude, listing.longitude)

    @classmethod
    def from_dict(cls, row):
        muis = row.get("muis") if isinstance(row, dict) else None
        valid = (
            isinstance(muis, dict)
            and all(isinstance(row.get(field), str) and row[field]
                    for field in ("name", "address", "postal_code"))
            and re.fullmatch(r"\d{6}", row["postal_code"])
            and isinstance(row.get("cuisine"), list)
            and isinstance(row.get("dietary"), list)
            and row.get("halal_certification") == "official"
            and isinstance(muis.get("certificate_number"), str))
        if not valid:
            raise ValueError(
                "The cleaned halal restaurant database is invalid.")
        return cls(
            row["name"], row["address"], row["postal_code"], muis,
            row["cuisine"], row.get("latitude"), row.get("longitude"))

    @property
    def name(self):
        return self._name

    @property
    def address(self):
        return self._address

    @property
    def postal_code(self):
        return self._address.postal_code

    @property
    def certificate(self):
        return self._certificate

    @property
    def cuisines(self):
        return list(self._cuisines)

    def to_dict(self):
        return {
            "name": self._name,
            "postal_code": self.postal_code,
            "address": self._address.text,
            "latitude": self._latitude,
            "longitude": self._longitude,
            "cuisine": list(self._cuisines),
            "dietary": ["halal"],
            "halal_certification": "official",
            "muis": self._certificate.to_dict(),
        }
