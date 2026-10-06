#!/usr/bin/env python3
"""
Scrape HalalFreak area pages → data/HalalFreak_restaurants.json

Run once before using the app, and refresh weekly:
    python halal_data_scrape.py
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://halalfreak.com"
SITEMAP_URL = "https://halalfreak.com/sitemap-priority.xml"
OUTPUT = Path("data/HalalFreak_restaurants.json")
HEADERS = {"User-Agent": "HalalNav/1.0 (personal project; contact@example.com)"}
DELAY = 1.0
TIMEOUT = 20

EST_RE = re.compile(
    r"^(?P<name>.+?)\s+Certified\s+"
    r"(?P<type>Restaurant|Hawker|Snack Bar\s*/\s*Bakery|Caterer|Central Kitchen|"
    r"Food Kiosk|Staff Canteen|Halal Section|Supermarket|Food Court)",
    re.IGNORECASE,
)


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


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    print("Fetching area list from sitemap...")
    area_urls = get_area_urls()
    print(f"Found {len(area_urls)} area pages.\n")

    all_rows = []
    for i, url in enumerate(area_urls, 1):
        slug = url.rstrip("/").split("/")[-1]
        print(f"[{i}/{len(area_urls)}] {slug}")
        try:
            rows = scrape_area(url, slug)
            all_rows.extend(rows)
            print(f"    -> {len(rows)} establishments")
        except Exception as e:
            print(f"    !! failed: {e}")
        time.sleep(DELAY)

    seen, unique = set(), []
    for row in all_rows:
        if row["profile_url"] not in seen:
            seen.add(row["profile_url"])
            unique.append(row)

    OUTPUT.write_text(json.dumps(unique, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(unique)} establishments to {OUTPUT}")


if __name__ == "__main__":
    main()