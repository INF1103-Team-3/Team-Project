"""Logic Manager: BRC's business rules.

  OutletMatcher - is a restaurant the same place as a MUIS outlet?
  LogicManager  - builds the cleaned database and accepts or rejects AI matches.
"""

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from BRC.models import EATING_ESTABLISHMENT, Address, CheckedRestaurant, HalalDatabase, HalalOutlet


class OutletMatcher:
    """A restaurant and a MUIS outlet are the same place when all of these hold:

      1. same postal code, and the certificate is still valid
      2. brand names are at least 72% alike (branch names in brackets ignored)
      3. unit numbers agree (both missing, or both the same)
      4. street addresses are at least 55% alike
    """

    BRAND_SIMILARITY = 0.72
    ADDRESS_SIMILARITY = 0.55

    def same(self, record, outlet):
        if record.address.postal != outlet.postal_code:
            return False
        if not outlet.certificate.is_active():
            return False
        if self._similarity(self.brand(record.name), self.brand(outlet.name)) \
                < self.BRAND_SIMILARITY:
            return False
        if record.address.unit != outlet.address.unit:
            return False
        return record.address.street_similarity(outlet.address) >= self.ADDRESS_SIMILARITY

    @staticmethod
    def brand(name):
        """The name before any '(branch)', '@ place' or '| tagline' part."""
        return Address.normalise(re.split(r"\s*(?:\(|@|\|)\s*", str(name), maxsplit=1)[0])

    @staticmethod
    def _similarity(first, second):
        return SequenceMatcher(None, first, second).ratio()


class LogicManager:
    """Applies BRC's business rules to MUIS data and AI answers.

    Association: it uses an OutletMatcher, which can be replaced with a
    different rule without changing this class.
    """

    def __init__(self, matcher=None):
        self._matcher = matcher or OutletMatcher()

    def build_database(self, snapshot, cuisines):
        """Keep each current eating establishment once, with its cuisine tags."""
        listings = snapshot.listings
        if len(listings) != len(cuisines):
            raise ValueError("BRC AI did not return cuisine data for every listing.")
        outlets, seen = [], set()
        for listing, tags in zip(listings, cuisines):
            outlet = HalalOutlet.from_listing(listing, tags, snapshot)
            if listing.scheme != EATING_ESTABLISHMENT or not outlet.certificate.is_active():
                continue
            # Two listings with this identity are the same physical outlet.
            identity = (str(listing.listing_id or listing.certificate_number),
                        listing.postal_code, outlet.address.street_key, outlet.address.unit)
            if identity not in seen:
                seen.add(identity)
                outlets.append(outlet)
        if not outlets:
            raise ValueError("No current MUIS restaurants remain after validation.")
        return HalalDatabase(outlets, snapshot.source_url, snapshot.fetched_at)

    def exact_matches(self, records, candidate_groups):
        """For each restaurant, the certificate of its only matching candidate, else None.

        These restaurants are certain enough that the AI is not asked about them.
        """
        results = []
        for record, candidates in zip(records, candidate_groups):
            matches = [outlet for outlet in candidates if self._matcher.same(record, outlet)]
            results.append(matches[0].certificate.number if len(matches) == 1 else None)
        return results

    def check_restaurants(self, records, database, chosen_certificates):
        """Accept each AI choice only if the MUIS evidence agrees with it."""
        if len(records) != len(chosen_certificates):
            raise ValueError("BRC AI omitted restaurant matches.")
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        results = []
        for record, certificate in zip(records, chosen_certificates):
            outlet = database.get(certificate)
            if outlet is not None and not self._matcher.same(record, outlet):
                outlet = None
            results.append(CheckedRestaurant(record, outlet, checked_at).to_dict())
        return results

    @staticmethod
    def score(record):
        """1 if the restaurant is officially MUIS-verified, otherwise 0."""
        return int(isinstance(record, dict) and record.get("halal_certification") == "official")

    def route(self, record):
        """'verified' or 'not_verified'."""
        return "verified" if self.score(record) else "not_verified"
