"""Identity matching policy for MUIS restaurant outlets."""

import re
from difflib import SequenceMatcher

from BRC.models import Address


class OutletMatcher:
    """Decide whether a restaurant and MUIS listing are the same outlet."""

    BRAND_SIMILARITY = 0.72
    ADDRESS_SIMILARITY = 0.55

    def same(self, record, outlet):
        if record.address.postal != outlet.postal_code:
            return False
        if not outlet.certificate.is_active():
            return False
        if (self._similarity(
                self.brand(record.name), self.brand(outlet.name))
                < self.BRAND_SIMILARITY):
            return False
        if record.address.unit != outlet.address.unit:
            return False
        return (
            record.address.street_similarity(outlet.address)
            >= self.ADDRESS_SIMILARITY)

    @staticmethod
    def brand(name):
        return Address.normalise(
            re.split(r"\s*(?:\(|@|\|)\s*", str(name), maxsplit=1)[0])

    @staticmethod
    def _similarity(first, second):
        return SequenceMatcher(None, first, second).ratio()
