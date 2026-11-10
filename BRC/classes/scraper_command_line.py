"""Command-line adapter for standalone MUIS snapshot retrieval."""

import argparse
from pathlib import Path

import requests

from BRC.classes.console_progress import ConsoleProgress
from BRC.classes.data_manager import RAW_MUIS_PATH, DataManager
from BRC.classes.io_manager import IOManager
from BRC.classes.muis_scraper import MuisScraper


class ScraperCommandLine:
    """Parse scraper options and present progress through BRC IO."""

    def run(self, argv=None):
        parser = argparse.ArgumentParser(
            description=(
                "Download all MUIS-certified eating establishments."))
        parser.add_argument("--output", type=Path, default=RAW_MUIS_PATH)
        parser.add_argument("--no-geocode", action="store_true")
        parser.add_argument("--delay", type=float, default=0.1)
        args = parser.parse_args(argv)
        io, display = IOManager(), ConsoleProgress()
        io.display_status(
            "Downloading the complete MUIS eating-establishment directory...",
            error=True)
        try:
            snapshot = MuisScraper(
                DataManager(raw_path=args.output),
                delay=max(0, args.delay),
                geocode=not args.no_geocode,
                progress=display).scrape_all()
        except (ValueError, OSError, requests.RequestException) as error:
            io.display_status(f"MUIS scrape failed: {error}", error=True)
            return 1
        finally:
            display.finish()
        io.display_status(
            f"Saved {len(snapshot.listings)} MUIS-certified restaurants "
            f"to {args.output}.")
        return 0
