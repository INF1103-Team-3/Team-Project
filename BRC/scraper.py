"""Download the complete MUIS eating-establishment directory."""

from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRC import data_manager
from shared import debug_log


PORTAL_URL = data_manager.SOURCE_URL
SEARCH_URL = "https://halal.muis.gov.sg/api/halal/establishments"
ONEMAP_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
MAX_RESULTS = 200
TIMEOUT = (5, 20)
GEOCODE_WORKERS = 8


class _ConsoleProgress:
    """Render one updating progress line for the standalone scraper."""

    def __init__(self, stream=None, width=28):
        self.stream = stream or sys.stderr
        self.width = width
        self.interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self._last_stage = None
        self._last_report = None

    def __call__(self, stage: str, current: int, total: int, detail: str) -> None:
        total = max(total, 1)
        current = min(max(current, 0), total)
        fraction = current / total
        filled = round(self.width * fraction)
        bar = "#" * filled + "-" * (self.width - filled)
        label = "MUIS" if stage == "retrieve" else "OneMap"
        detail = re.sub(r"\s+", " ", detail).strip()
        if len(detail) > 58:
            detail = detail[:55] + "..."
        line = (f"[{bar}] {fraction:6.1%} {label}: "
                f"{current}/{total} | {detail}")
        if self.interactive:
            self.stream.write("\r\033[2K" + line)
            self.stream.flush()
        report = (stage, current, total)
        if (not self.interactive
                and (stage != self._last_stage or current == total)
                and report != self._last_report):
            print(line, file=self.stream)
        self._last_stage = stage
        self._last_report = report

    def finish(self) -> None:
        if self.interactive:
            self.stream.write("\n")
            self.stream.flush()


def _portal_token(session) -> str:
    response = session.get(PORTAL_URL, timeout=TIMEOUT)
    response.raise_for_status()
    element = BeautifulSoup(response.text, "html.parser").find(
        "input", attrs={"name": "__RequestVerificationToken"})
    if element is None or not element.get("value"):
        raise ValueError("MUIS portal did not provide a search token.")
    return element["value"]


def _normalize_row(row: dict, query: str) -> dict | None:
    if not isinstance(row, dict):
        raise ValueError(f"MUIS returned a malformed listing for {query!r}.")
    if row.get("schemeText") != "Eating Establishment":
        return None
    if any(not isinstance(row.get(key), str) or not row[key].strip()
           for key in ("name", "address", "postal", "number")):
        raise ValueError(f"MUIS returned an incomplete listing for {query!r}.")
    postal = row["postal"].strip()
    if not re.fullmatch(r"\d{6}", postal):
        raise ValueError(f"MUIS returned an invalid postal code for {query!r}.")
    return {
        "listing_id": row.get("id"),
        "certificate_number": row["number"].strip(),
        "name": row["name"].strip(),
        "address": row["address"].strip(),
        "postal_code": postal,
        "scheme": row["schemeText"],
        "category": row.get("subSchemeText"),
        "status": "listed",
        "valid_until": row.get("expiryDate"),
        "source_url": PORTAL_URL,
    }


def _query(session, token: str, text: str) -> tuple[list[dict], bool]:
    response = session.post(
        SEARCH_URL, json={"text": text},
        headers={"Accept": "application/json", "X-CSRF-TOKEN": token},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"MUIS returned invalid JSON for {text!r}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"MUIS returned an invalid result for {text!r}.")
    count, rows = payload.get("totalRecords"), payload.get("data")
    if (type(count) is not int or count < 0 or count > MAX_RESULTS
            or not isinstance(rows, list) or len(rows) != count):
        raise ValueError(f"MUIS returned an incomplete result for {text!r}.")
    if count == MAX_RESULTS:
        return [], True
    normalized = []
    for row in rows:
        item = _normalize_row(row, text)
        if item is not None:
            normalized.append(item)
    return normalized, False


def _new_progress() -> dict:
    return {
        "source_url": PORTAL_URL,
        "pending_prefixes": list("0123456789"),
        "completed_prefixes": [],
        "listings": {},
    }


def _load_progress(path: Path) -> dict:
    if not path.exists():
        return _new_progress()
    try:
        value = data_manager._read_json(path)
    except ValueError:
        return _new_progress()
    if (not isinstance(value, dict) or value.get("source_url") != PORTAL_URL
            or not isinstance(value.get("pending_prefixes"), list)
            or not isinstance(value.get("completed_prefixes"), list)
            or not isinstance(value.get("listings"), dict)):
        return _new_progress()
    return value


def _retrieve_all(session, token: str, *, progress_path: Path,
                  delay: float = 0.1, progress=None) -> tuple[list[dict], list[str]]:
    state = _load_progress(progress_path)
    pending = state["pending_prefixes"]
    completed = state["completed_prefixes"]
    listings = state["listings"]
    since_checkpoint = 0
    while pending:
        prefix = pending.pop(0)
        if progress:
            progress("retrieve", len(completed),
                     len(completed) + len(pending) + 1,
                     f"Searching postal prefix {prefix}")
        rows, capped = _query(session, token, prefix)
        if capped:
            if len(prefix) >= 6:
                raise ValueError(
                    f"MUIS results for postal prefix {prefix!r} remain capped.")
            pending[0:0] = [prefix + digit for digit in "0123456789"]
        else:
            completed.append(prefix)
            for row_index, row in enumerate(rows, 1):
                if row["postal_code"].startswith(prefix):
                    identity = "|".join((
                        str(row.get("listing_id") or ""),
                        row["certificate_number"],
                        row["postal_code"],
                        re.sub(r"\s+", " ", row["address"]).casefold(),
                    ))
                    listings[identity] = row
                    if progress:
                        progress("retrieve", len(completed),
                                 len(completed) + len(pending),
                                 f"{row['name']} ({row_index}/{len(rows)} in {prefix})")
        since_checkpoint += 1
        if since_checkpoint >= 10 or not pending:
            data_manager.write_json_atomic(state, progress_path)
            since_checkpoint = 0
        if delay and pending:
            time.sleep(delay)
    if progress:
        progress("retrieve", 1, 1,
                 f"Retrieved {len(listings)} restaurant outlets")
    return list(listings.values()), completed


def _load_geocode_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = data_manager._read_json(path)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _address_candidates(address: str):
    seen = set()
    for value in (address, re.sub(r"\s*#.*$", "", address),
                  re.sub(r"\bSingapore\b.*$", "", address,
                         flags=re.IGNORECASE)):
        value = re.sub(r"\s+", " ", value).strip(" ,")
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            yield value


def _onemap_lookup(postal: str, address: str, http_get=requests.get):
    for text in (postal, *_address_candidates(address)):
        try:
            response = http_get(ONEMAP_URL, params={
                "searchVal": text, "returnGeom": "Y",
                "getAddrDetails": "Y", "pageNum": 1,
            }, timeout=20)
            response.raise_for_status()
            payload = response.json()
            if payload.get("found", 0) > 0 and payload.get("results"):
                row = payload["results"][0]
                return {"latitude": float(row["LATITUDE"]),
                        "longitude": float(row["LONGITUDE"])}
        except (requests.RequestException, ValueError, KeyError, TypeError):
            continue
    return {"latitude": None, "longitude": None}


def _geocode(listings: list[dict], *, cache_path: Path,
             http_get=requests.get, progress=None) -> list[dict]:
    cache = _load_geocode_cache(cache_path)
    by_postal = {}
    names_by_postal = {}
    for row in listings:
        by_postal.setdefault(row["postal_code"], row["address"])
        names_by_postal.setdefault(row["postal_code"], row["name"])
    missing = [(postal, address) for postal, address in by_postal.items()
               if postal not in cache]
    if missing:
        if progress:
            progress("geocode", 0, len(missing),
                     f"Preparing {len(missing)} restaurant locations")
        with ThreadPoolExecutor(max_workers=GEOCODE_WORKERS) as pool:
            futures = {pool.submit(_onemap_lookup, postal, address, http_get): postal
                       for postal, address in missing}
            for index, future in enumerate(as_completed(futures), 1):
                postal = futures[future]
                cache[postal] = future.result()
                if progress:
                    progress("geocode", index, len(missing),
                             f"{names_by_postal[postal]} ({postal})")
                if index % 25 == 0:
                    data_manager.write_json_atomic(cache, cache_path)
        data_manager.write_json_atomic(cache, cache_path)
    enriched = []
    for row in listings:
        item = dict(row)
        item.update(cache.get(row["postal_code"], {
            "latitude": None, "longitude": None}))
        enriched.append(item)
    return enriched


def scrape_all(output: Path = data_manager.RAW_MUIS_PATH, *, session=None,
               delay: float = 0.1, geocode=True,
               progress_path: Path = data_manager.SCRAPE_PROGRESS_PATH,
               geocode_cache_path: Path = data_manager.ONEMAP_CACHE_PATH,
               progress=None) -> dict:
    """Retrieve, validate, optionally geocode, and atomically save all outlets."""
    debug_log.debug_log("Starting complete MUIS scrape.", "INFO",
                        "BRC.scraper.scrape_all")
    session = session or requests.Session()
    token = _portal_token(session)
    listings, prefixes = _retrieve_all(
        session, token, progress_path=progress_path,
        delay=delay, progress=progress)
    if not listings:
        raise ValueError("MUIS returned no eating establishments.")
    if geocode:
        listings = _geocode(
            listings, cache_path=geocode_cache_path, progress=progress)
    snapshot = {
        "source_url": PORTAL_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": True,
        "coverage": "all_eating_establishments",
        "postal_prefixes": prefixes,
        "listing_count": len(listings),
        "listings": sorted(
            listings, key=lambda row: (row["name"].casefold(),
                                       row["postal_code"],
                                       row["certificate_number"])),
    }
    data_manager.save_raw_snapshot(snapshot, output)
    progress_path.unlink(missing_ok=True)
    debug_log.debug_log(
        f"Saved {len(listings)} complete MUIS listings.", "INFO",
        "BRC.scraper.scrape_all")
    return snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Download all MUIS-certified eating establishments.")
    parser.add_argument("--output", type=Path, default=data_manager.RAW_MUIS_PATH)
    parser.add_argument("--no-geocode", action="store_true")
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args(argv)
    display = _ConsoleProgress()
    print("Downloading the complete MUIS eating-establishment directory...",
          file=sys.stderr)
    try:
        snapshot = scrape_all(args.output, delay=max(0, args.delay),
                              geocode=not args.no_geocode, progress=display)
    except (ValueError, OSError, requests.RequestException) as exc:
        print(f"MUIS scrape failed: {exc}", file=sys.stderr)
        return 1
    finally:
        display.finish()
    print(f"Saved {snapshot['listing_count']} MUIS-certified restaurants "
          f"to {args.output}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
