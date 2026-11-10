"""Coordinator for complete MUIS directory retrieval."""

from BRC.classes.muis_directory_client import MuisDirectoryClient
from BRC.classes.muis_snapshot import MuisSnapshot
from BRC.classes.no_geocoder import NoGeocoder
from BRC.classes.one_map_geocoder import OneMapGeocoder
from BRC.classes.postal_prefix_crawler import PostalPrefixCrawler
from shared import debug_log


class MuisScraper:
    """Download, geocode, and persist a complete MUIS snapshot."""

    def __init__(self, data, session=None, delay=0.1, geocode=True,
                 progress=None, geocoder=None):
        self._data = data
        self._directory = MuisDirectoryClient(session)
        self._crawler = PostalPrefixCrawler(
            self._directory, data.scrape_progress_file, delay, progress)
        if geocoder is None:
            geocoder = (
                OneMapGeocoder(data.geocode_cache_file, progress=progress)
                if geocode else NoGeocoder())
        self._geocoder = geocoder

    def scrape_all(self):
        debug_log.debug_log(
            "Starting complete MUIS scrape.",
            "INFO", "BRC.scraper.scrape_all")
        self._directory.connect()
        listings, prefixes = self._crawler.crawl()
        if not listings:
            raise ValueError("MUIS returned no eating establishments.")
        listings = self._geocoder.geocode(listings)
        snapshot = MuisSnapshot.create(
            listings, prefixes, self._geocoder.adds_coordinates)
        self._data.save_raw_snapshot(snapshot)
        self._crawler.clear()
        debug_log.debug_log(
            f"Saved {len(listings)} complete MUIS listings.",
            "INFO", "BRC.scraper.scrape_all")
        return snapshot
