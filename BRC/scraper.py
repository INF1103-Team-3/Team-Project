"""Compatibility façade and launcher for BRC scraping classes."""

from BRC.classes.io.geocoding.contracts.geocoder_interface import GeocoderInterface
from BRC.classes.io.scraping.muis_directory_client import MuisDirectoryClient
from BRC.classes.io.scraping.muis_scraper import MuisScraper
from BRC.classes.io.geocoding.providers.no_geocoder import NoGeocoder
from BRC.classes.io.geocoding.providers.one_map_geocoder import OneMapGeocoder
from BRC.classes.io.scraping.postal_prefix_crawler import PostalPrefixCrawler
from BRC.classes.services.cli.scraper_command_line import ScraperCommandLine


Geocoder = GeocoderInterface


__all__ = [
    "Geocoder",
    "GeocoderInterface",
    "MuisDirectoryClient",
    "MuisScraper",
    "NoGeocoder",
    "OneMapGeocoder",
    "PostalPrefixCrawler",
    "ScraperCommandLine",
]


if __name__ == "__main__":
    raise SystemExit(ScraperCommandLine().run())
