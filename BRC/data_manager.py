"""Persist BRC raw, cleaned, and checked JSON without partial writes."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


BRC_DIR = Path(__file__).resolve().parent
DATA_DIR = BRC_DIR / "data"
RAW_MUIS_PATH = DATA_DIR / "muis_establishments.json"
CLEAN_DATABASE_PATH = DATA_DIR / "halal_restaurants.json"
CHECK_CACHE_PATH = DATA_DIR / "checked_restaurants_cache.json"
SINGLE_RESULT_PATH = DATA_DIR / "checked_restaurant.json"
BATCH_RESULT_PATH = DATA_DIR / "checked_restaurants.json"
SCRAPE_PROGRESS_PATH = DATA_DIR / "scrape_progress.json"
ONEMAP_CACHE_PATH = DATA_DIR / "onemap_cache.json"
SOURCE_URL = "https://halal.muis.gov.sg/halal/establishments"
MAX_SOURCE_AGE = timedelta(days=7)


def format_json(value, *, compact_hours=False) -> str:
    """Return readable JSON with compact opening-hour ranges when requested."""
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if compact_hours:
        text = re.sub(
            r'\[\n[ \t]*"(\d{4})",\n[ \t]*"(\d{4})"\n[ \t]*\]',
            r'["\1", "\2"]', text)
        text = re.sub(
            r'\[\n(?:[ \t]*\["\d{4}", "\d{4}"\],?\n)+[ \t]*\]',
            lambda match: "[" + ", ".join(re.findall(
                r'\["\d{4}", "\d{4}"\]', match.group(0))) + "]",
            text)
    return text + "\n"


def write_json_atomic(value, path: Path, *, compact_hours=False) -> None:
    """Write JSON atomically, retrying transient Windows file locks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(format_json(value, compact_hours=compact_hours))
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                temporary = None
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read valid JSON from {path}.") from exc


def _covers_all_postals(prefixes) -> bool:
    if (not isinstance(prefixes, list)
            or any(not isinstance(item, str) or not item.isdigit()
                   or not 1 <= len(item) <= 6 for item in prefixes)):
        return False
    terminals = set(prefixes)

    def covered(prefix=""):
        if prefix in terminals:
            return True
        if len(prefix) == 6:
            return False
        return all(covered(prefix + digit) for digit in "0123456789")

    return covered()


def validate_raw_snapshot(snapshot: dict, *, current=True) -> dict:
    """Require a complete official snapshot and its postal-prefix proof."""
    if (not isinstance(snapshot, dict)
            or snapshot.get("complete") is not True
            or snapshot.get("coverage") != "all_eating_establishments"
            or snapshot.get("source_url") != SOURCE_URL
            or not _covers_all_postals(snapshot.get("postal_prefixes"))
            or not isinstance(snapshot.get("listings"), list)
            or not snapshot["listings"]
            or snapshot.get("listing_count") != len(snapshot["listings"])
            or not isinstance(snapshot.get("fetched_at"), str)):
        raise ValueError("MUIS raw data is incomplete or invalid.")
    for row in snapshot["listings"]:
        if (not isinstance(row, dict)
                or any(not isinstance(row.get(field), str) or not row[field]
                       for field in ("certificate_number", "name", "address",
                                     "postal_code", "scheme"))
                or not re.fullmatch(r"\d{6}", row["postal_code"])):
            raise ValueError("MUIS raw data contains an invalid outlet.")
    try:
        fetched = datetime.fromisoformat(snapshot["fetched_at"])
    except ValueError as exc:
        raise ValueError("MUIS raw data has an invalid retrieval time.") from exc
    now = datetime.now(timezone.utc)
    if fetched.tzinfo is None or fetched > now + timedelta(minutes=5):
        raise ValueError("MUIS raw data has an invalid retrieval time.")
    if current and now - fetched > MAX_SOURCE_AGE:
        raise ValueError("MUIS raw data is older than seven days.")
    return snapshot


def load_raw_snapshot(path: Path = RAW_MUIS_PATH, *, current=True) -> dict:
    return validate_raw_snapshot(_read_json(path), current=current)


def save_raw_snapshot(snapshot: dict, path: Path = RAW_MUIS_PATH) -> None:
    validate_raw_snapshot(snapshot, current=False)
    write_json_atomic(snapshot, path)


def _valid_clean_row(row) -> bool:
    return (isinstance(row, dict)
            and isinstance(row.get("name"), str) and bool(row["name"])
            and isinstance(row.get("address"), str) and bool(row["address"])
            and isinstance(row.get("postal_code"), str)
            and bool(re.fullmatch(r"\d{6}", row["postal_code"]))
            and isinstance(row.get("cuisine"), list)
            and isinstance(row.get("dietary"), list)
            and row.get("halal_certification") == "official"
            and isinstance(row.get("muis"), dict)
            and isinstance(row["muis"].get("certificate_number"), str))


def load_clean_database(path: Path = CLEAN_DATABASE_PATH) -> list[dict]:
    value = _read_json(path)
    if (not isinstance(value, dict)
            or not isinstance(value.get("restaurants"), list)
            or not value["restaurants"]
            or value.get("restaurant_count") != len(value["restaurants"])
            or not isinstance(value.get("source_fetched_at"), str)
            or any(not _valid_clean_row(row) for row in value["restaurants"])):
        raise ValueError("The cleaned halal restaurant database is invalid.")
    return value["restaurants"]


def save_clean_database(restaurants: list[dict], source: dict,
                        path: Path = CLEAN_DATABASE_PATH) -> dict:
    if not restaurants or any(not _valid_clean_row(row) for row in restaurants):
        raise ValueError("Refusing to save an incomplete cleaned database.")
    value = {
        "source_url": source["source_url"],
        "source_fetched_at": source["fetched_at"],
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "restaurant_count": len(restaurants),
        "restaurants": restaurants,
    }
    write_json_atomic(value, path)
    return value


def _cache_key(row: dict) -> str:
    place_id = row.get("google_place_id") or row.get("place_id")
    if isinstance(place_id, str) and place_id:
        return "google:" + place_id
    check = row.get("muis_check")
    if isinstance(check, dict) and check.get("certificate_number"):
        return "muis:" + str(check["certificate_number"])
    postal = str(row.get("postal_code") or "")
    address = " ".join(re.findall(r"[a-z0-9]+", str(
        row.get("address") or "").casefold()))
    name = " ".join(re.findall(r"[a-z0-9]+", str(
        row.get("name") or "").casefold()))
    return f"outlet:{postal}:{address}:{name}"


def update_checked_cache(records: list[dict], path: Path = CHECK_CACHE_PATH) -> None:
    cached = []
    if path.exists():
        try:
            value = _read_json(path)
            cached = value.get("restaurants", []) if isinstance(value, dict) else []
        except ValueError:
            cached = []
    merged = {_cache_key(row): row for row in cached if isinstance(row, dict)}
    for row in records:
        merged[_cache_key(row)] = row
    write_json_atomic({
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "restaurant_count": len(merged),
        "restaurants": list(merged.values()),
    }, path, compact_hours=True)


def save_checked_result(result, *, single: bool,
                        output: Path | None = None):
    records = [result] if single else result
    update_checked_cache(records)
    destination = output or (SINGLE_RESULT_PATH if single else BATCH_RESULT_PATH)
    write_json_atomic(result, destination, compact_hours=True)
    return result
