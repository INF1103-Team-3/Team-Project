"""BRC Logic Manager: deterministic MUIS verification rules."""

from datetime import datetime, timezone

from BRC.classes.logic.outlet_matcher import OutletMatcher
from BRC.models import (
    EATING_ESTABLISHMENT,
    CheckedRestaurant,
    HalalDatabase,
    HalalOutlet,
)


class LogicManager:
    """Apply BRC rules to AI proposals and authoritative MUIS evidence."""

    KEYWORDS = {
        "malay": "malay", "nasi": "malay", "chicken rice": "chinese",
        "chinese": "chinese", "indian": "indian", "biryani": "indian",
        "japanese": "japanese", "sushi": "japanese", "korean": "korean",
        "thai": "thai", "western": "western", "pizza": "italian",
    }

    def prepare_cuisine_tags(self, listings, cache):
        tags, pending = [[] for _ in listings], []
        for index, listing in enumerate(listings):
            cached = cache.get(listing)
            text = f"{listing.name or ''} {listing.category or ''}".casefold()
            keyword_tags = sorted({
                tag for word, tag in self.KEYWORDS.items() if word in text})
            if cached is not None:
                tags[index] = cached
            elif keyword_tags:
                tags[index] = keyword_tags
                cache.put(listing, keyword_tags)
            else:
                pending.append((index, listing))
        return tags, pending

    def __init__(self, matcher=None):
        self._matcher = matcher or OutletMatcher()

    def build_database(self, snapshot, cuisines):
        listings = snapshot.listings
        if len(listings) != len(cuisines):
            raise ValueError(
                "BRC AI did not return cuisine data for every listing.")
        outlets, seen = [], set()
        for listing, tags in zip(listings, cuisines):
            outlet = HalalOutlet.from_listing(listing, tags, snapshot)
            if (listing.scheme != EATING_ESTABLISHMENT
                    or not outlet.certificate.is_active()):
                continue
            identity = (
                str(listing.listing_id or listing.certificate_number),
                listing.postal_code,
                outlet.address.street_key,
                outlet.address.unit,
            )
            if identity not in seen:
                seen.add(identity)
                outlets.append(outlet)
        if not outlets:
            raise ValueError(
                "No current MUIS restaurants remain after validation.")
        return HalalDatabase(
            outlets, snapshot.source_url, snapshot.fetched_at)

    def exact_matches(self, records, candidate_groups):
        results = []
        for record, candidates in zip(records, candidate_groups):
            matches = [
                outlet for outlet in candidates
                if self._matcher.same(record, outlet)]
            results.append(
                matches[0].certificate.number
                if len(matches) == 1 else None)
        return results

    def check_restaurants(self, records, database, chosen_certificates):
        if len(records) != len(chosen_certificates):
            raise ValueError("BRC AI omitted restaurant matches.")
        checked_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        results = []
        for record, certificate in zip(records, chosen_certificates):
            outlet = database.get(certificate)
            if (outlet is not None
                    and not self._matcher.same(record, outlet)):
                outlet = None
            results.append(
                CheckedRestaurant(record, outlet, checked_at).to_dict())
        return results

    @staticmethod
    def score(record):
        return int(
            isinstance(record, dict)
            and record.get("halal_certification") == "official")

    def route(self, record):
        return "verified" if self.score(record) else "not_verified"
