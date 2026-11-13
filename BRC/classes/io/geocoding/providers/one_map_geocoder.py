"""OneMap geocoding adapter for MUIS listings."""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from BRC.classes.data.storage.data_unavailable_error import DataUnavailableError
from BRC.classes.io.geocoding.contracts.geocoder_interface import GeocoderInterface


class OneMapGeocoder(GeocoderInterface):
    """Geocode unique postal codes in parallel with a persistent cache."""

    URL = "https://www.onemap.gov.sg/api/common/elastic/search"
    WORKERS = 8
    NO_LOCATION = {"latitude": None, "longitude": None}

    def __init__(self, cache_file, http_get=requests.get, progress=None):
        self._cache_file = cache_file
        self._http_get = http_get
        self._progress = progress

    def geocode(self, listings):
        cache = self._load_cache()
        first_at_postal = {}
        for listing in listings:
            first_at_postal.setdefault(listing.postal_code, listing)
        missing = {
            postal: listing for postal, listing in first_at_postal.items()
            if postal not in cache}
        if missing:
            self._look_up(missing, cache)
        return [
            listing.with_coordinates(**cache.get(
                listing.postal_code, self.NO_LOCATION))
            for listing in listings]

    def _look_up(self, missing, cache):
        self._report(0, len(missing),
                     f"Preparing {len(missing)} restaurant locations")
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            futures = {
                pool.submit(self.lookup, postal, listing.address): postal
                for postal, listing in missing.items()}
            for count, future in enumerate(as_completed(futures), 1):
                postal = futures[future]
                cache[postal] = future.result()
                self._report(
                    count, len(missing),
                    f"{missing[postal].name} ({postal})")
                if count % 25 == 0:
                    self._cache_file.write(cache)
        self._cache_file.write(cache)

    def lookup(self, postal, address):
        variants = []
        for text in (
                address, re.sub(r"\s*#.*$", "", address),
                re.sub(r"\bSingapore\b.*$", "", address,
                       flags=re.IGNORECASE)):
            text = re.sub(r"\s+", " ", text).strip(" ,")
            if (text and text.casefold()
                    not in {item.casefold() for item in variants}):
                variants.append(text)
        for text in (postal, *variants):
            try:
                response = self._http_get(
                    self.URL,
                    params={
                        "searchVal": text, "returnGeom": "Y",
                        "getAddrDetails": "Y", "pageNum": 1},
                    timeout=20)
                response.raise_for_status()
                payload = response.json()
                if payload.get("found", 0) > 0 and payload.get("results"):
                    best = payload["results"][0]
                    return {
                        "latitude": float(best["LATITUDE"]),
                        "longitude": float(best["LONGITUDE"]),
                    }
            except (
                    requests.RequestException, ValueError,
                    KeyError, TypeError):
                continue
        return dict(self.NO_LOCATION)

    def _report(self, current, total, detail):
        if self._progress:
            self._progress("geocode", current, total, detail)

    def _load_cache(self):
        if not self._cache_file.exists():
            return {}
        try:
            saved = self._cache_file.read()
        except DataUnavailableError:
            return {}
        return saved if isinstance(saved, dict) else {}
