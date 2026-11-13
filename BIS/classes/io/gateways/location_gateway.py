"""External geocoding and location-cache IO for BIS."""

import requests


class LocationGateway:
    """Resolve Singapore locations through coordinates, cache, or Google."""

    def __init__(self, logic_manager, geocode_cache, geocode_url):
        self._logic = logic_manager
        self._cache = geocode_cache
        self._geocode_url = geocode_url

    def lookup_cached(self, query):
        pair = self._cache.lookup(query)
        if pair and self._logic.in_singapore(*pair):
            return {
                "query": query, "label": query,
                "latitude": pair[0], "longitude": pair[1],
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
        cached = self.lookup_cached(query)
        if cached:
            return cached
        if not api_key:
            raise RuntimeError(
                "This location is not cached. Set GOOGLE_MAPS_API_KEY or "
                "enter Singapore coordinates."
            )
        try:
            response = requests.get(
                self._geocode_url,
                params={"address": query + ", Singapore", "key": api_key},
                timeout=10,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except (
                requests.RequestException, ValueError,
                AttributeError) as error:
            raise RuntimeError(
                "Geocoding is unavailable. Try again.") from error
        for result in results:
            try:
                point = result["geometry"]["location"]
                latitude = float(point["lat"])
                longitude = float(point["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            if self._logic.in_singapore(latitude, longitude):
                self._cache.remember((query,), latitude, longitude)
                return {
                    "query": query,
                    "label": result.get("formatted_address") or query,
                    "latitude": latitude,
                    "longitude": longitude,
                }
        raise ValueError(
            "No Singapore location found. Try another address or postal code.")

    def remember(self, queries, location):
        """Save aliases for a resolved location in the shared cache."""
        self._cache.remember(
            queries, location["latitude"], location["longitude"])
