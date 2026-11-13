"""Merge live restaurant facts with saved evidence without inventing facts."""

import re
from BIS.sources.profile_schema import CUISINES


class RestaurantEnricher:
    """Own saved-outlet matching, merge precedence, and price/cuisine policy."""

    CUISINE_MAP = {
        "cafe": "cafe", "fast_food_restaurant": "fast food", "bakery": "bakery",
        "american_restaurant": "western", "pizza_restaurant": "western",
        "hamburger_restaurant": "western", "indian_restaurant": "indian",
        "malaysian_restaurant": "malaysian", "indonesian_restaurant": "indonesian",
    }

    BAND_THRESHOLDS = (8.0, 15.0, 30.0)

    def enrich(self, place, saved_restaurants):
        """Merge saved fields into a Places result. Missing data stays
        None/'unknown' — never invented (business rule)."""
        entry = self._match_saved_restaurant(place, saved_restaurants)
        live_fields = {
            "google_place_id": place.get("google_place_id"),
            "postal_code": place.get("postal_code"),
            "number": place.get("number"),
            "rating_count": place.get("rating_count"),
            "serves_vegetarian_food": place.get("serves_vegetarian_food") is True,
            "halal_hint": place.get("halal_hint") is True,
            "wheelchair_accessible": place.get("wheelchair_accessible"),
            "open_now": place.get("open_now"),
            "today_hours": place.get("today_hours"),
            "opening_hours": place.get("opening_hours"),
        }
        if entry:
            avg_price = entry.get("avg_price")
            saved_cuisines = [cuisine for cuisine in (
                entry.get("cuisines") or
                ([entry["cuisine"]] if entry.get("cuisine") else []))
                if cuisine in CUISINES]
            saved_dietary = (entry.get("dietary_requirements")
                             or entry.get("dietary") or [])
            band = (self.price_to_band(avg_price) if avg_price is not None
                    else (place.get("price_level")
                          or self._band_from_range(place.get("price_start"), place.get("price_end"))))
            return {
                **live_fields,
                "name": entry.get("name", place["name"]),
                "address": place["address"],
                "lat": place["lat"], "lng": place["lng"],
                "cuisines": saved_cuisines or [self._cuisine_from_types(place["types"])],
                "dietary_requirements": sorted(set(
                    saved_dietary
                    + (["vegetarian"] if place.get("serves_vegetarian_food") else []))),
                "avg_price": avg_price,
                "price_band": band,
                "price_start": place.get("price_start"),
                "price_end": place.get("price_end"),
                "price_range": place.get("price_range"),
                "rating": place.get("rating"),
                "open_hours": entry.get("open_hours"),
                "spicy_options": entry.get("spicy_options"),
                "certification": entry.get("certification", "unknown"),
                "walk_minutes": None, "walk_meters": None,
                "drive_minutes": None, "drive_meters": None,
                "transit_minutes": None, "transit_meters": None,
                "source": "saved + google places",
            }
        return {
            **live_fields,
            "name": place["name"],
            "address": place["address"],
            "lat": place["lat"], "lng": place["lng"],
            "cuisines": [self._cuisine_from_types(place["types"])],
            "dietary_requirements": (
                ["vegetarian"] if place.get("serves_vegetarian_food") else []),
            "avg_price": None,
            "price_band": (place.get("price_level")
                           or self._band_from_range(place.get("price_start"), place.get("price_end"))),
            "price_start": place.get("price_start"),
            "price_end": place.get("price_end"),
            "price_range": place.get("price_range"),
            "rating": place.get("rating"),
            "open_hours": None,
            "spicy_options": None,
            "certification": "unknown",
            "walk_minutes": None, "walk_meters": None,
            "drive_minutes": None, "drive_meters": None,
            "transit_minutes": None, "transit_meters": None,
            "source": "google places",
        }

    def _match_saved_restaurant(self, place, saved_restaurants):
        p = self._norm(place["name"])
        for entry in saved_restaurants:
            e = self._norm(entry.get("name", ""))
            if e != p:
                continue
            address = self._norm(entry.get("address", ""))
            if not address or address != self._norm(place.get("address", "")):
                continue
            return entry
        return None

    def _norm(self, name):
        return re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).strip()

    def price_to_band(self, avg_price):
        for band, upper in zip(("inexpensive", "moderate", "expensive"), self.BAND_THRESHOLDS):
            if avg_price <= upper:
                return band
        return "very_expensive"

    def _band_from_range(self, start, end):
        """Derive a budget band from a price range (midpoint). None if no numbers."""
        vals = [v for v in (start, end) if v is not None]
        if not vals:
            return None
        return self.price_to_band(sum(vals) / len(vals))

    def _cuisine_from_types(self, types):
        for t in types or []:
            if t in ("halal_restaurant", "vegetarian_restaurant", "vegan_restaurant"):
                continue
            if t in self.CUISINE_MAP:
                return self.CUISINE_MAP[t]
            if t.endswith("_restaurant"):
                return t[: -len("_restaurant")]
        return "unknown"
