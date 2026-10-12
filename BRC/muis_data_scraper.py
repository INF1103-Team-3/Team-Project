"""Refresh a local MUIS snapshot independently of the BRC JSON checker."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRC import data_manager, logic_manager
from shared import debug_log

PORTAL_URL = "https://halal.muis.gov.sg/halal/establishments"
SEARCH_URL = "https://halal.muis.gov.sg/api/halal/establishments"
MAX_RESULTS_PER_QUERY = 200


def _query_name(name: str) -> str:
    query = re.split(r"\s*(?:\(|@|\|)\s*", name.strip(), maxsplit=1)[0].strip()
    if len(query) < 3:
        raise ValueError(f"Restaurant name is too short for MUIS search: {name!r}")
    return query


def _names_from_json(path: Path) -> list[str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read restaurant JSON: {path}") from exc
    records = value if isinstance(value, list) else [value]
    if not records or any(not isinstance(row, dict)
                          or not isinstance(row.get("name"), str)
                          or not row["name"].strip() for row in records):
        raise ValueError("Restaurant JSON must contain named restaurant objects.")
    return [row["name"] for row in records]


def _portal_session(session: requests.Session) -> str:
    response = session.get(PORTAL_URL, timeout=(5, 20))
    response.raise_for_status()
    token = BeautifulSoup(response.text, "html.parser").find(
        "input", attrs={"name": "__RequestVerificationToken"})
    if token is None or not token.get("value"):
        raise ValueError("MUIS portal did not provide a search token.")
    return token["value"]


def _search(session: requests.Session, token: str, query: str) -> list[dict]:
    response = session.post(
        SEARCH_URL, json={"text": query},
        headers={"Accept": "application/json", "X-CSRF-TOKEN": token},
        timeout=(5, 20),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError(f"MUIS returned invalid JSON for {query!r}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"MUIS returned an invalid result for {query!r}.")
    count, rows = payload.get("totalRecords"), payload.get("data")
    if (type(count) is not int or count < 0 or not isinstance(rows, list)
            or len(rows) != count or count >= MAX_RESULTS_PER_QUERY):
        raise ValueError(
            f"MUIS results for {query!r} may be truncated; use a narrower query.")
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"MUIS returned a malformed listing for {query!r}.")
        if row.get("schemeText") != "Eating Establishment":
            continue
        if any(not isinstance(row.get(key), str) or not row[key].strip()
               for key in ("name", "address", "postal", "number")):
            raise ValueError(f"MUIS returned an incomplete listing for {query!r}.")
        normalized.append({
            "listing_id": row.get("id"),
            "certificate_number": row["number"].strip(),
            "name": row["name"].strip(),
            "address": row["address"].strip(),
            "postal_code": row["postal"].strip(),
            "scheme": row["schemeText"],
            "sub_scheme": row.get("subSchemeText"),
            "status": "listed",
            "valid_until": row.get("expiryDate"),
            "source_url": PORTAL_URL,
        })
    return normalized


def refresh(names: list[str], output: Path = data_manager.MUIS_SNAPSHOT_PATH,
            *, session: requests.Session | None = None, delay: float = 0.5) -> dict:
    """Query each requested brand; save only after every query is complete."""
    queries = {}
    for name in names:
        query = _query_name(name)
        queries[logic_manager.muis_brand_key(name)] = query
    if not queries:
        raise ValueError("Provide at least one restaurant name or search query.")
    debug_log.debug_log(f"Refreshing {len(queries)} MUIS name queries.", "INFO",
                        "BRC.muis_data_scraper.refresh")
    session = session or requests.Session()
    token = _portal_session(session)
    listings = {}
    for index, (key, query) in enumerate(sorted(queries.items())):
        if index and delay:
            time.sleep(delay)
        for row in _search(session, token, query):
            listings[row["certificate_number"]] = row
    snapshot = {
        "source_url": PORTAL_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": True,
        "covered_names": sorted(queries),
        "queries": queries,
        "listing_count": len(listings),
        "listings": list(listings.values()),
    }
    data_manager.save_muis_snapshot(snapshot, output)
    debug_log.debug_log(
        f"Saved MUIS snapshot with {len(listings)} listings.", "INFO",
        "BRC.data_manager.save_muis_snapshot")
    return snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Refresh a MUIS outlet snapshot.")
    parser.add_argument("--input", type=Path, help="Restaurant JSON to cover")
    parser.add_argument("--query", action="append", default=[],
                        help="Restaurant name to search (repeatable)")
    parser.add_argument("--output", type=Path,
                        default=data_manager.MUIS_SNAPSHOT_PATH)
    args = parser.parse_args(argv)
    try:
        names = list(args.query)
        if args.input:
            names.extend(_names_from_json(args.input))
        snapshot = refresh(names, args.output)
    except (ValueError, OSError, requests.RequestException) as exc:
        print(f"MUIS refresh failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved {snapshot['listing_count']} MUIS eating-establishment "
          f"listings for {len(snapshot['covered_names'])} restaurant names "
          f"to {args.output}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
