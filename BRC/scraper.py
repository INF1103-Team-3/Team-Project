"""Download the complete MUIS eating-establishment directory.

MUIS returns at most 200 results per search, so the crawler searches postal
prefixes 0-9 and splits any capped prefix into ten longer ones ('5' -> '50'..'59')
until every search is complete. Progress is saved so a crawl can resume.

Run on its own with:  python -m BRC.scraper [--output PATH] [--no-geocode]
"""

import argparse
import re
import sys
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRC.data_manager import RAW_MUIS_PATH, DataManager, DataUnavailableError
from BRC.models import SOURCE_URL, MuisListing, MuisSnapshot
from shared import debug_log


class MuisDirectoryClient:
    """Talks to the MUIS establishment search API."""

    SEARCH_URL = "https://halal.muis.gov.sg/api/halal/establishments"
    MAX_RESULTS = 200
    TIMEOUT = (5, 20)   # (connect, read) seconds

    def __init__(self, session=None):
        self._session = session or requests.Session()
        self._token = None

    def connect(self):
        """Fetch the anti-forgery token the search API requires."""
        response = self._session.get(SOURCE_URL, timeout=self.TIMEOUT)
        response.raise_for_status()
        field = BeautifulSoup(response.text, "html.parser").find(
            "input", attrs={"name": "__RequestVerificationToken"})
        if field is None or not field.get("value"):
            raise ValueError("MUIS portal did not provide a search token.")
        self._token = field["value"]

    def search(self, text):
        """Return (restaurants, capped). capped=True means MUIS hit its 200-result limit."""
        response = self._session.post(
            self.SEARCH_URL, json={"text": text},
            headers={"Accept": "application/json", "X-CSRF-TOKEN": self._token},
            timeout=self.TIMEOUT)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"MUIS returned invalid JSON for {text!r}.") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"MUIS returned an invalid result for {text!r}.")
        count, rows = payload.get("totalRecords"), payload.get("data")
        if (type(count) is not int or not 0 <= count <= self.MAX_RESULTS
                or not isinstance(rows, list) or len(rows) != count):
            raise ValueError(f"MUIS returned an incomplete result for {text!r}.")
        if count == self.MAX_RESULTS:
            return [], True
        listings = [MuisListing.from_api_row(row, text) for row in rows]
        return [listing for listing in listings if listing is not None], False


class PostalPrefixCrawler:
    """Searches every postal prefix, splitting capped ones, and saves progress.

    Association: it uses the MuisDirectoryClient it is given but does not own it.
    """

    def __init__(self, directory, progress_file, delay=0.1, progress=None):
        self._directory = directory
        self._progress_file = progress_file
        self._delay = delay
        self._progress = progress

    def crawl(self):
        """Return (all restaurants, the prefixes that were fully searched)."""
        state = self._load_state()
        pending, done, found = (state["pending_prefixes"], state["completed_prefixes"],
                                state["listings"])
        since_save = 0
        while pending:
            prefix = pending.pop(0)
            self._report(len(done), len(done) + len(pending) + 1,
                         f"Searching postal prefix {prefix}")
            rows, capped = self._directory.search(prefix)
            if capped:
                if len(prefix) >= 6:
                    raise ValueError(f"MUIS results for postal prefix {prefix!r} remain capped.")
                pending[0:0] = [prefix + digit for digit in "0123456789"]
            else:
                done.append(prefix)
                for number, row in enumerate(rows, 1):
                    if row.postal_code.startswith(prefix):   # search also matches other text
                        found[row.crawl_identity] = row.to_dict(geocoded=False)
                        self._report(len(done), len(done) + len(pending),
                                     f"{row.name} ({number}/{len(rows)} in {prefix})")
            since_save += 1
            if since_save >= 10 or not pending:
                self._progress_file.write(state)
                since_save = 0
            if self._delay and pending:
                time.sleep(self._delay)   # be polite to the MUIS server
        self._report(1, 1, f"Retrieved {len(found)} restaurant outlets")
        return [MuisListing.from_dict(row) for row in found.values()], done

    def clear(self):
        self._progress_file.delete()

    def _report(self, current, total, detail):
        if self._progress:
            self._progress("retrieve", current, total, detail)

    def _load_state(self):
        """Resume saved progress if it is usable, otherwise start from prefixes 0-9."""
        fresh = {"source_url": SOURCE_URL, "pending_prefixes": list("0123456789"),
                 "completed_prefixes": [], "listings": {}}
        if not self._progress_file.exists():
            return fresh
        try:
            saved = self._progress_file.read()
        except DataUnavailableError:
            return fresh
        usable = (isinstance(saved, dict) and saved.get("source_url") == SOURCE_URL
                  and isinstance(saved.get("pending_prefixes"), list)
                  and isinstance(saved.get("completed_prefixes"), list)
                  and isinstance(saved.get("listings"), dict))
        return saved if usable else fresh


class Geocoder(ABC):
    """Interface: adds coordinates to MUIS listings.

    MuisScraper only calls geocode() and reads adds_coordinates, so any
    geocoder works without the scraper checking which one it has.
    """

    adds_coordinates = True

    @abstractmethod
    def geocode(self, listings):
        """Return the listings with coordinates where available."""


class NoGeocoder(Geocoder):
    """Leaves listings without coordinates (used with --no-geocode)."""

    adds_coordinates = False

    def geocode(self, listings):
        return list(listings)


class OneMapGeocoder(Geocoder):
    """Looks up each postal code once on OneMap, in parallel, with a saved cache."""

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
        missing = {postal: listing for postal, listing in first_at_postal.items()
                   if postal not in cache}
        if missing:
            self._look_up(missing, cache)
        return [listing.with_coordinates(**cache.get(listing.postal_code, self.NO_LOCATION))
                for listing in listings]

    def _look_up(self, missing, cache):
        self._report(0, len(missing), f"Preparing {len(missing)} restaurant locations")
        with ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            futures = {pool.submit(self.lookup, postal, listing.address): postal
                       for postal, listing in missing.items()}
            for count, future in enumerate(as_completed(futures), 1):
                postal = futures[future]
                cache[postal] = future.result()
                self._report(count, len(missing), f"{missing[postal].name} ({postal})")
                if count % 25 == 0:
                    self._cache_file.write(cache)
        self._cache_file.write(cache)

    def lookup(self, postal, address):
        """Try the postal code, then the address, then shorter forms of the address."""
        variants = []
        for text in (address,
                     re.sub(r"\s*#.*$", "", address),                              # no unit
                     re.sub(r"\bSingapore\b.*$", "", address, flags=re.IGNORECASE)):  # no country
            text = re.sub(r"\s+", " ", text).strip(" ,")
            if text and text.casefold() not in {v.casefold() for v in variants}:
                variants.append(text)
        for text in (postal, *variants):
            try:
                response = self._http_get(self.URL, params={
                    "searchVal": text, "returnGeom": "Y", "getAddrDetails": "Y",
                    "pageNum": 1}, timeout=20)
                response.raise_for_status()
                payload = response.json()
                if payload.get("found", 0) > 0 and payload.get("results"):
                    best = payload["results"][0]
                    return {"latitude": float(best["LATITUDE"]),
                            "longitude": float(best["LONGITUDE"])}
            except (requests.RequestException, ValueError, KeyError, TypeError):
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


class MuisScraper:
    """Downloads, geocodes and saves the complete MUIS directory.

    Composition: it creates and owns its directory client and crawler.
    Aggregation: a Geocoder can be passed in; otherwise one is chosen from `geocode`.
    """

    def __init__(self, data, session=None, delay=0.1, geocode=True, progress=None,
                 geocoder=None):
        self._data = data
        self._directory = MuisDirectoryClient(session)
        self._crawler = PostalPrefixCrawler(self._directory, data.scrape_progress_file,
                                            delay, progress)
        if geocoder is None:
            geocoder = (OneMapGeocoder(data.geocode_cache_file, progress=progress)
                        if geocode else NoGeocoder())
        self._geocoder = geocoder

    def scrape_all(self):
        debug_log.debug_log("Starting complete MUIS scrape.", "INFO", "BRC.scraper.scrape_all")
        self._directory.connect()
        listings, prefixes = self._crawler.crawl()
        if not listings:
            raise ValueError("MUIS returned no eating establishments.")
        listings = self._geocoder.geocode(listings)
        snapshot = MuisSnapshot.create(listings, prefixes, self._geocoder.adds_coordinates)
        self._data.save_raw_snapshot(snapshot)
        self._crawler.clear()   # finished, so the resume file is no longer needed
        debug_log.debug_log(f"Saved {len(listings)} complete MUIS listings.", "INFO",
                            "BRC.scraper.scrape_all")
        return snapshot


class ScraperCommandLine:
    """python -m BRC.scraper: download the directory without building the database."""

    def run(self, argv=None):
        from BRC.io_manager import ConsoleProgress, IOManager
        parser = argparse.ArgumentParser(
            description="Download all MUIS-certified eating establishments.")
        parser.add_argument("--output", type=Path, default=RAW_MUIS_PATH)
        parser.add_argument("--no-geocode", action="store_true")
        parser.add_argument("--delay", type=float, default=0.1)
        args = parser.parse_args(argv)
        io, display = IOManager(), ConsoleProgress()
        io.display_status("Downloading the complete MUIS eating-establishment directory...",
                          error=True)
        try:
            snapshot = MuisScraper(DataManager(raw_path=args.output), delay=max(0, args.delay),
                                   geocode=not args.no_geocode, progress=display).scrape_all()
        except (ValueError, OSError, requests.RequestException) as exc:
            io.display_status(f"MUIS scrape failed: {exc}", error=True)
            return 1
        finally:
            display.finish()
        io.display_status(f"Saved {len(snapshot.listings)} MUIS-certified restaurants "
                          f"to {args.output}.")
        return 0


if __name__ == "__main__":
    raise SystemExit(ScraperCommandLine().run())
