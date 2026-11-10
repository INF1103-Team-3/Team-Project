"""The records BRC works with: MUIS listings, certified outlets and checked restaurants."""

import re
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

SOURCE_URL = "https://halal.muis.gov.sg/halal/establishments"
EATING_ESTABLISHMENT = "Eating Establishment"


class Address:
    """A Singapore address that can find its postal code and unit number."""

    UNIT_PATTERN = re.compile(
        r"(?:#\s*|\b)((?:B\d{1,2}|\d{2})[-/]\d{2,3}(?:/\d{2,3})?[A-Z]?)\b", re.I)

    def __init__(self, text, postal_code=""):
        self._text = text
        self._postal_code = postal_code

    @property
    def text(self):
        return self._text

    @property
    def postal_code(self):
        return self._postal_code

    @staticmethod
    def normalise(text):
        """Lowercase words and digits only, so 'Nasi-Lemak!' equals 'nasi lemak'."""
        return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))

    @property
    def postal(self):
        """The postal-code field if valid, otherwise the last 6-digit number in the text."""
        if re.fullmatch(r"\d{6}", self._postal_code):
            return self._postal_code
        found = re.findall(r"\b\d{6}\b", self._text)
        return found[-1] if found else None

    @property
    def unit(self):
        """The unit number without punctuation, e.g. '#01-23' becomes '0123'."""
        match = self.UNIT_PATTERN.search(self._text)
        if match is None:
            return None
        return re.sub(r"[^A-Z0-9]", "", match.group(1).upper())

    @property
    def key(self):
        return self.normalise(self._text)

    @property
    def street_key(self):
        """The address without its unit, postal code or the word 'Singapore'."""
        street = self.UNIT_PATTERN.sub(" ", self._text)
        street = re.sub(r"\b(?:singapore|\d{6})\b", " ", street, flags=re.I)
        return self.normalise(street)

    def street_similarity(self, other):
        """0.0 (different street) to 1.0 (same street)."""
        return SequenceMatcher(None, self.street_key, other.street_key).ratio()


class Certificate:
    """One MUIS halal certificate."""

    FIELDS = ("certificate_number", "listing_id", "scheme", "category",
              "valid_until", "source_url", "raw_fetched_at")
    DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")

    def __init__(self, data):
        self._data = {field: data.get(field) for field in self.FIELDS}

    @property
    def number(self):
        return self._data["certificate_number"]

    @property
    def listing_id(self):
        return self._data["listing_id"]

    @property
    def valid_until(self):
        return self._data["valid_until"]

    @property
    def source_url(self):
        return self._data["source_url"]

    def is_active(self, today=None):
        """No expiry date counts as active; an unreadable date counts as expired."""
        if not self.valid_until:
            return True
        for date_format in self.DATE_FORMATS:
            try:
                expiry = datetime.strptime(str(self.valid_until)[:10], date_format).date()
            except ValueError:
                continue
            return expiry >= (today or date.today())
        return False

    def to_dict(self):
        return dict(self._data)


class MuisListing:
    """One row of the official MUIS eating-establishment directory."""

    FIELDS = ("listing_id", "certificate_number", "name", "address", "postal_code",
              "scheme", "category", "status", "valid_until", "source_url")
    REQUIRED = ("certificate_number", "name", "address", "postal_code", "scheme")

    def __init__(self, data):
        self._data = {field: data.get(field) for field in self.FIELDS}
        self._latitude = data.get("latitude")
        self._longitude = data.get("longitude")

    @classmethod
    def from_api_row(cls, row, query):
        """A listing from one MUIS search result, or None if it is not a restaurant."""
        if not isinstance(row, dict):
            raise ValueError(f"MUIS returned a malformed listing for {query!r}.")
        if row.get("schemeText") != EATING_ESTABLISHMENT:
            return None
        for key in ("name", "address", "postal", "number"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"MUIS returned an incomplete listing for {query!r}.")
        postal = row["postal"].strip()
        if not re.fullmatch(r"\d{6}", postal):
            raise ValueError(f"MUIS returned an invalid postal code for {query!r}.")
        return cls({
            "listing_id": row.get("id"), "certificate_number": row["number"].strip(),
            "name": row["name"].strip(), "address": row["address"].strip(),
            "postal_code": postal, "scheme": row["schemeText"],
            "category": row.get("subSchemeText"), "status": "listed",
            "valid_until": row.get("expiryDate"), "source_url": SOURCE_URL,
        })

    @classmethod
    def from_dict(cls, row):
        """A listing from saved JSON; rejects rows with missing fields."""
        valid = isinstance(row, dict) and all(
            isinstance(row.get(field), str) and row[field] for field in cls.REQUIRED)
        if not valid or not re.fullmatch(r"\d{6}", row["postal_code"]):
            raise ValueError("MUIS raw data contains an invalid outlet.")
        listing = cls(row)
        listing._data["status"] = row.get("status", "listed")
        listing._data["source_url"] = row.get("source_url", SOURCE_URL)
        return listing

    @property
    def certificate_number(self):
        return self._data["certificate_number"]

    @property
    def name(self):
        return self._data["name"]

    @property
    def address(self):
        return self._data["address"]

    @property
    def postal_code(self):
        return self._data["postal_code"]

    @property
    def scheme(self):
        return self._data["scheme"]

    @property
    def listing_id(self):
        return self._data["listing_id"]

    @property
    def category(self):
        return self._data["category"]

    @property
    def valid_until(self):
        return self._data["valid_until"]

    @property
    def latitude(self):
        return self._latitude

    @property
    def longitude(self):
        return self._longitude

    def with_coordinates(self, latitude, longitude):
        return MuisListing({**self._data, "latitude": latitude, "longitude": longitude})

    def to_dict(self, geocoded=True):
        """Saved form; coordinates are only included once geocoding has run."""
        data = dict(self._data)
        if geocoded:
            data["latitude"] = self._latitude
            data["longitude"] = self._longitude
        return data

    @property
    def crawl_identity(self):
        """Key used to drop duplicates returned by overlapping MUIS searches."""
        address = re.sub(r"\s+", " ", self.address).casefold()
        return "|".join((str(self.listing_id or ""), self.certificate_number,
                         self.postal_code, address))

    @property
    def cuisine_cache_key(self):
        """Changes whenever the text that decides the cuisine changes."""
        identity = self.listing_id or self.certificate_number or "unknown"
        return (f"{identity}|{Address.normalise(self.name or '')}|"
                f"{Address.normalise(self.category or '')}")


class MuisSnapshot:
    """A complete, timestamped download of the MUIS directory."""

    MAX_AGE = timedelta(days=7)

    def __init__(self, listings, fetched_at, postal_prefixes, source_url=SOURCE_URL,
                 geocoded=True):
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
        """A new snapshot timestamped now, with listings sorted by name."""
        ordered = sorted(listings, key=lambda row: (
            row.name.casefold(), row.postal_code, row.certificate_number))
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(ordered, fetched_at, postal_prefixes, geocoded=geocoded)

    @classmethod
    def from_dict(cls, value):
        listings = value.get("listings") if isinstance(value, dict) else None
        complete = (isinstance(listings, list) and len(listings) > 0
                    and value.get("complete") is True
                    and value.get("coverage") == "all_eating_establishments"
                    and value.get("source_url") == SOURCE_URL
                    and cls.covers_all_postal_codes(value.get("postal_prefixes"))
                    and value.get("listing_count") == len(listings)
                    and isinstance(value.get("fetched_at"), str))
        if not complete:
            raise ValueError("MUIS raw data is incomplete or invalid.")
        geocoded = any("latitude" in row for row in listings)
        return cls([MuisListing.from_dict(row) for row in listings], value["fetched_at"],
                   value["postal_prefixes"], value["source_url"], geocoded)

    def to_dict(self):
        return {
            "source_url": self._source_url, "fetched_at": self._fetched_at,
            "complete": True, "coverage": "all_eating_establishments",
            "postal_prefixes": list(self._postal_prefixes),
            "listing_count": len(self._listings),
            "listings": [row.to_dict(self._geocoded) for row in self._listings],
        }

    def validate(self, current=True):
        """Raise ValueError unless complete, correctly timestamped and (optionally) fresh."""
        if (not self.covers_all_postal_codes(self._postal_prefixes) or not self._listings
                or self._source_url != SOURCE_URL or not isinstance(self._fetched_at, str)):
            raise ValueError("MUIS raw data is incomplete or invalid.")
        try:
            fetched = datetime.fromisoformat(self._fetched_at)
        except ValueError as exc:
            raise ValueError("MUIS raw data has an invalid retrieval time.") from exc
        now = datetime.now(timezone.utc)
        if fetched.tzinfo is None or fetched > now + timedelta(minutes=5):
            raise ValueError("MUIS raw data has an invalid retrieval time.")
        if current and now - fetched > self.MAX_AGE:
            raise ValueError("MUIS raw data is older than seven days.")
        return self

    @staticmethod
    def covers_all_postal_codes(prefixes):
        """True when the searched prefixes together cover every 6-digit postal code."""
        if not isinstance(prefixes, list) or not all(
                isinstance(p, str) and p.isdigit() and 1 <= len(p) <= 6 for p in prefixes):
            return False
        searched = set(prefixes)

        def covered(prefix=""):
            if prefix in searched:
                return True
            if len(prefix) == 6:
                return False
            return all(covered(prefix + digit) for digit in "0123456789")

        return covered()


class HalalOutlet:
    """A currently certified restaurant in the cleaned database.

    Composition: the outlet creates and owns its Certificate and Address.
    """

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
            "listing_id": listing.listing_id, "scheme": listing.scheme,
            "category": listing.category, "valid_until": listing.valid_until,
            "source_url": snapshot.source_url, "raw_fetched_at": snapshot.fetched_at,
        }
        return cls(listing.name, listing.address, listing.postal_code, certificate,
                   cuisines, listing.latitude, listing.longitude)

    @classmethod
    def from_dict(cls, row):
        muis = row.get("muis") if isinstance(row, dict) else None
        valid = (isinstance(muis, dict)
                 and all(isinstance(row.get(field), str) and row[field]
                         for field in ("name", "address", "postal_code"))
                 and re.fullmatch(r"\d{6}", row["postal_code"])
                 and isinstance(row.get("cuisine"), list)
                 and isinstance(row.get("dietary"), list)
                 and row.get("halal_certification") == "official"
                 and isinstance(muis.get("certificate_number"), str))
        if not valid:
            raise ValueError("The cleaned halal restaurant database is invalid.")
        return cls(row["name"], row["address"], row["postal_code"], muis, row["cuisine"],
                   row.get("latitude"), row.get("longitude"))

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
            "name": self._name, "postal_code": self.postal_code,
            "address": self._address.text, "latitude": self._latitude,
            "longitude": self._longitude, "cuisine": list(self._cuisines),
            "dietary": ["halal"], "halal_certification": "official",
            "muis": self._certificate.to_dict(),
        }


class HalalDatabase:
    """The cleaned list of certified outlets.

    Aggregation: it groups outlets that are created elsewhere and stay usable
    on their own (for example inside a CheckedRestaurant).
    """

    MAX_CANDIDATES = 25

    def __init__(self, outlets, source_url=SOURCE_URL, source_fetched_at=None):
        self._outlets = list(outlets)
        self._source_url = source_url
        self._source_fetched_at = source_fetched_at
        # If two outlets share a certificate, the later one wins (as in Phase 1).
        self._by_certificate = {outlet.certificate.number: outlet for outlet in self._outlets}

    def __len__(self):
        return len(self._outlets)

    def __iter__(self):
        return iter(self._outlets)

    @property
    def source_url(self):
        return self._source_url

    @property
    def source_fetched_at(self):
        return self._source_fetched_at

    def get(self, certificate_number):
        if not certificate_number:
            return None
        return self._by_certificate.get(certificate_number)

    def filter(self, keep):
        return [outlet for outlet in self._outlets if keep(outlet)]

    def candidates_for(self, record):
        """Outlets at the same postal code; if none, outlets with the same name or address."""
        postal = record.address.postal
        candidates = [o for o in self._outlets if postal and o.postal_code == postal]
        if not candidates:
            name = Address.normalise(record.name)
            candidates = [o for o in self._outlets
                          if Address.normalise(o.name) == name
                          or o.address.key == record.address.key]
        return candidates[:self.MAX_CANDIDATES]

    def to_list(self):
        return [outlet.to_dict() for outlet in self._outlets]


class CuisineCache:
    """Cuisine tags already decided, so the AI is not asked about them again."""

    def __init__(self, tags=None):
        self._tags = {key: list(value) for key, value in (tags or {}).items()}

    def __contains__(self, listing):
        return listing.cuisine_cache_key in self._tags

    def __len__(self):
        return len(self._tags)

    def get(self, listing):
        """The saved tags, or None if this listing has never been tagged."""
        tags = self._tags.get(listing.cuisine_cache_key)
        return None if tags is None else list(tags)

    def put(self, listing, tags):
        self._tags[listing.cuisine_cache_key] = list(tags)

    def to_dict(self):
        return {key: list(value) for key, value in self._tags.items()}


class RestaurantRecord:
    """A restaurant sent in for checking; every original field is kept."""

    def __init__(self, data):
        self._data = dict(data)
        self._address = Address(str(data.get("address")), str(data.get("postal_code") or ""))

    @property
    def name(self):
        return self._data["name"]

    @property
    def address(self):
        return self._address

    def to_dict(self):
        return dict(self._data)


class CheckedRestaurant:
    """The result of checking one restaurant.

    Association: it refers to the matched outlet, which belongs to the database.
    """

    def __init__(self, record, outlet, checked_at):
        self._record = record
        self._outlet = outlet
        self._checked_at = checked_at

    def to_dict(self):
        result = self._record.to_dict()
        if self._outlet is None:
            # A restaurant that claimed official status but failed the check loses it.
            if result.get("halal_certification") == "official":
                result["halal_certification"] = "none"
                result["dietary"] = [x for x in result.get("dietary", []) if x != "halal"]
            result["muis_check"] = {"status": "not_verified", "checked_at": self._checked_at}
            return result

        certificate = self._outlet.certificate
        result["dietary"] = list(dict.fromkeys([*(result.get("dietary") or []), "halal"]))
        result["halal_certification"] = "official"
        result["cuisines"] = self._outlet.cuisines
        if not result.get("cuisine") and self._outlet.cuisines:
            result["cuisine"] = self._outlet.cuisines[0]
        result["muis_check"] = {
            "status": "verified", "checked_at": self._checked_at,
            "certificate_number": certificate.number,
            "listing_id": certificate.listing_id,
            "source_url": certificate.source_url,
            "valid_until": certificate.valid_until,
        }
        return result
