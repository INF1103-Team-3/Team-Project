from __future__ import annotations

import logging
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from bs4 import BeautifulSoup
from shared import debug_log

import data_manager
import io_manager

log = logging.getLogger(__name__)

BASE = "https://halalfreak.com"
SITEMAP_URL = "https://halalfreak.com/sitemap-priority.xml"
HEADERS = {"User-Agent": "HalalNav/1.0 (personal project; contact@example.com)"}
DELAY = 1.0
TIMEOUT = 20

EST_RE = re.compile(
    r"^(?P<name>.+?)\s+Certified\s+"
    r"(?P<type>Restaurant|Hawker|Snack Bar\s*/\s*Bakery|Caterer|Central Kitchen|"
    r"Food Kiosk|Staff Canteen|Halal Section|Supermarket|Food Court)",
    re.IGNORECASE,
)

Progress = Callable[[str], None]


class ScrapeError(Exception):
    """Raised when the certified directory could not be downloaded or saved."""


def get_area_urls():
    r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    areas = []
    for loc in root.findall(".//sm:loc", ns):
        url = (loc.text or "").strip()
        if "/areas/" in url and url.rstrip("/") != f"{BASE}/areas":
            areas.append(url)
    return sorted(set(areas))


def scrape_area(area_url, area_slug):
    r = requests.get(area_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/establishments/"):
            continue
        text = a.get_text(" ", strip=True)
        m = EST_RE.match(text)
        if not m:
            continue
        postal_match = re.search(r"\b(\d{6})\b", text)
        results.append({
            "name": m.group("name").strip(),
            "halal_status": "Certified",
            "type": m.group("type").strip(),
            "postal_code": postal_match.group(1) if postal_match else None,
            "area": area_slug,
            "profile_url": urljoin(BASE, href),
        })

    seen, unique = set(), []
    for row in results:
        if row["profile_url"] not in seen:
            seen.add(row["profile_url"])
            unique.append(row)
    return unique


def scrape_all(progress: Progress | None = None) -> list[dict]:
    """Scrape every area page. A failing area is logged and skipped."""
    say = progress or (lambda _message: None)

    say("Fetching area list from sitemap...")
    try:
        area_urls = get_area_urls()
    except (requests.RequestException, ET.ParseError) as exc:
        log.error("Could not read the HalalFreak sitemap: %s", exc)
        raise ScrapeError(f"Could not read the HalalFreak sitemap: {exc}") from exc
    say(f"Found {len(area_urls)} area pages.\n")

    all_rows = []
    for i, url in enumerate(area_urls, 1):
        slug = url.rstrip("/").split("/")[-1]
        say(f"[{i}/{len(area_urls)}] {slug}")
        try:
            rows = scrape_area(url, slug)
            all_rows.extend(rows)
            say(f"    -> {len(rows)} establishments")
        except Exception as exc:
            log.warning("Area %s failed: %s", slug, exc)
            say(f"    !! failed: {exc}")
        time.sleep(DELAY)

    seen, unique = set(), []
    for row in all_rows:
        if row["profile_url"] not in seen:
            seen.add(row["profile_url"])
            unique.append(row)
    return unique


def refresh(progress: Progress | None = None) -> int:
    """Scrape and save the directory. Returns how many establishments were saved."""
    rows = scrape_all(progress)
    if not rows:
        # Never replace good data with an empty scrape (the site layout may have changed).
        raise ScrapeError("No establishments were found, so your existing data was kept.")
    if not data_manager.save_halal_directory(rows):
        raise ScrapeError("Could not save the directory file (see logs/bitefinder.log).")
    return len(rows)


def main() -> int:
    debug_log.configure_python_logging()
    try:
        count = refresh(progress=io_manager.show_message)
    except ScrapeError as exc:
        io_manager.show_error(str(exc))
        return 1
    io_manager.show_message(
        f"\nSaved {count} establishments to {data_manager.HALAL_DIRECTORY_PATH}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
