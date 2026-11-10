"""Compatibility façade and launcher for BRC scraping classes."""

from BRC.classes.geocoder_interface import GeocoderInterface
from BRC.classes.muis_directory_client import MuisDirectoryClient
from BRC.classes.muis_scraper import MuisScraper
from BRC.classes.no_geocoder import NoGeocoder
from BRC.classes.one_map_geocoder import OneMapGeocoder
from BRC.classes.postal_prefix_crawler import PostalPrefixCrawler
from BRC.classes.scraper_command_line import ScraperCommandLine


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
