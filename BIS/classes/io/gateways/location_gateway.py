"""External geocoding and location-cache IO for BIS."""

import re
import requests

from common.singapore_locations import (
    is_acceptable_singapore_geocode,
    is_generic_singapore_centroid,
    lookup_seed_singapore_location,
    suggest_seed_locations,
    validate_location_syntax,
)


_PLACES_AUTOCOMPLETE_URL = (
    "https://places.googleapis.com/v1/places:autocomplete"
)


class LocationGateway:
    """Resolve Singapore locations through coordinates, cache, or Google."""

    def __init__(self, logic_manager, geocode_cache, geocode_url):
        self._logic = logic_manager
        self._cache = geocode_cache
        self._geocode_url = geocode_url
        self._autocomplete_url = _PLACES_AUTOCOMPLETE_URL

    def lookup_cached(self, query):
        try:
            clean = validate_location_syntax(query, label="Location")
        except ValueError:
            return None
        pair = self._cache.lookup(clean)
        if (
            pair
            and self._logic.in_singapore(*pair)
            and not is_generic_singapore_centroid(*pair)
        ):
            return {
                "query": clean,
                "label": clean,
                "latitude": pair[0],
                "longitude": pair[1],
            }
        return None

    def resolve(self, query, api_key):
        """Retrieve an origin from coordinates, cache, or geocoding."""
        coordinates = self._logic.parse_coordinates(query)
        if coordinates:
            return {
                "query": query,
                "label": f"{coordinates[0]}, {coordinates[1]}",
                "latitude": coordinates[0],
                "longitude": coordinates[1],
            }
        clean_query = validate_location_syntax(query, label="Location")
        cached = self.lookup_cached(clean_query)
        if cached:
            return cached
        if not api_key:
            seed = lookup_seed_singapore_location(clean_query)
            if seed:
                label, latitude, longitude = seed
                return {
                    "query": clean_query,
                    "label": label,
                    "latitude": latitude,
                    "longitude": longitude,
                }
            raise RuntimeError(
                "This location is not cached. Set GOOGLE_MAPS_API_KEY or "
                "enter Singapore coordinates."
            )
        try:
            response = requests.get(
                self._geocode_url,
                params={
                    "address": clean_query + ", Singapore",
                    "key": api_key,
                },
                timeout=10,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except (
            requests.RequestException,
            ValueError,
            AttributeError,
        ) as error:
            raise RuntimeError(
                "Geocoding is unavailable. Try again."
            ) from error
        for result in results:
            if not is_acceptable_singapore_geocode(result, clean_query):
                continue
            try:
                point = result["geometry"]["location"]
                latitude = float(point["lat"])
                longitude = float(point["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            if self._logic.in_singapore(latitude, longitude):
                self._cache.remember((clean_query,), latitude, longitude)
                return {
                    "query": clean_query,
                    "label": result.get("formatted_address") or clean_query,
                    "latitude": latitude,
                    "longitude": longitude,
                }
        raise ValueError(
            "No Singapore location found. Try another address, landmark, or "
            "6-digit postal code."
        )

    def _fetch_google_autocomplete(self, clean_query, api_key, limit=6):
        if not api_key or len(clean_query) < 2 or len(clean_query) > 120:
            return []
        try:
            response = requests.post(
                self._autocomplete_url,
                json={"input": clean_query, "includedRegionCodes": ["sg"]},
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                },
                timeout=2.5,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError, AttributeError):
            return []

        items = []
        for entry in payload.get("suggestions") or []:
            pred = (entry or {}).get("placePrediction") or {}
            struct = pred.get("structuredFormat") or {}
            main_text = (
                (struct.get("mainText") or {}).get("text")
                or (pred.get("text") or {}).get("text")
                or ""
            )
            main_clean = re.sub(
                r",\s*Singapore$",
                "",
                str(main_text).strip(),
                flags=re.IGNORECASE,
            ).strip()
            if not main_clean or main_clean.lower() == "singapore":
                continue
            secondary = (
                (struct.get("secondaryText") or {}).get("text") or "Singapore"
            ).strip()
            items.append(
                {
                    "label": main_clean,
                    "secondary": secondary,
                    "source": "google",
                }
            )
            if len(items) >= limit:
                break
        return items

    def suggest(self, query, api_key="", limit=6):
        """Return deduplicated Singapore location suggestions."""
        clean = re.sub(r"\s+", " ", str(query or "").strip())
        max_items = max(1, min(int(limit or 6), 12))
        cache_search = getattr(self._cache, "search", None)
        cached_hits = (
            cache_search(clean, limit=max_items)
            if callable(cache_search)
            else []
        )
        seed_hits = suggest_seed_locations(clean, limit=max_items)
        google_hits = self._fetch_google_autocomplete(
            clean, api_key, limit=max_items
        )

        lowered = clean.lower()
        prefix_local = [
            item
            for item in (seed_hits + cached_hits)
            if not lowered or item["label"].lower().startswith(lowered)
        ]
        other_local = [
            item
            for item in (seed_hits + cached_hits)
            if lowered and not item["label"].lower().startswith(lowered)
        ]

        merged = []
        seen = set()
        for item in prefix_local + google_hits + other_local:
            key = item["label"].strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= max_items:
                break
        return merged

    def remember(self, queries, location):
        """Save aliases for a resolved location in the shared cache."""
        self._cache.remember(
            queries, location["latitude"], location["longitude"]
        )
