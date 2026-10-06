from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).with_name("restaurant_history.json")
VALID_OUTCOMES = {"accept", "flag", "reject"}


def _is_valid_record(record) -> bool:
    return (
        isinstance(record, dict)
        and isinstance(record.get("name"), str)
        and record.get("outcome") in VALID_OUTCOMES
    )


def _record_key(record: dict):
    return (record.get("place_id") or record.get("name"), record.get("food_type"))


def _quarantine(path: Path) -> None:
    """Move an unreadable file aside so it is kept but no longer in the way."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        os.replace(path, target)
        log.error("Corrupt history file moved to %s", target)
    except OSError as exc:
        log.error("Could not move corrupt history file %s: %s", path, exc)


def load_records(path: Path = DEFAULT_PATH) -> list[dict]:
    """Load every saved record. Returns [] if the file is missing or corrupt."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return []
        data = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.error("Could not read history file %s: %s", path, exc)
        _quarantine(path)
        return []

    if not isinstance(data, list):
        log.error("History file %s does not contain a list", path)
        _quarantine(path)
        return []

    valid = [r for r in data if _is_valid_record(r)]
    if len(valid) != len(data):
        log.warning("Skipped %d invalid record(s) in %s", len(data) - len(valid), path)
    return valid


def save_records(new_records: list[dict], path: Path = DEFAULT_PATH) -> bool:
    """
    Merge new_records into the saved history and write it back.

    A restaurant is identified by (place_id, food_type); saving it again replaces
    the older entry. Returns True on success, False if the file could not be written.
    """
    path = Path(path)
    try:
        merged = {_record_key(r): r for r in load_records(path)}
        stamp = datetime.now().isoformat(timespec="seconds")
        for record in new_records:
            item = dict(record)
            item["saved_at"] = stamp
            merged[_record_key(item)] = item

        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(list(merged.values()), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)  # atomic: never leaves a half-written history file
        return True
    except (OSError, TypeError, ValueError) as exc:
        log.error("Could not save history to %s: %s", path, exc)
        return False


def filter_records(
    records: list[dict],
    outcome: str | None = None,
    food_type: str | None = None,
    min_rating: float | None = None,
    max_price: float | None = None,
    name_contains: str | None = None,
) -> list[dict]:
    """Return records matching every given filter, newest first."""
    matches = []
    for r in records:
        if outcome and r.get("outcome") != outcome:
            continue
        if food_type and r.get("food_type") != food_type:
            continue
        if min_rating is not None:
            rating = r.get("rating")
            if not isinstance(rating, (int, float)) or rating < min_rating:
                continue
        if max_price is not None:
            price = r.get("avg_price")
            if not isinstance(price, (int, float)) or price > max_price:
                continue
        if name_contains and name_contains.lower() not in r.get("name", "").lower():
            continue
        matches.append(r)
    matches.sort(key=lambda r: str(r.get("saved_at", "")), reverse=True)
    return matches


# ------------------------------------------------- halal-certified directory


HALAL_DIRECTORY_PATH = Path(__file__).with_name("data") / "HalalFreak_restaurants.json"


def load_halal_directory(path: Path = HALAL_DIRECTORY_PATH) -> list[dict]:
    """Load the scraped list of certified establishments. [] if missing or corrupt."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.error("Could not read halal directory %s: %s", path, exc)
        _quarantine(path)
        return []
    if not isinstance(data, list):
        log.error("Halal directory %s does not contain a list", path)
        _quarantine(path)
        return []
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("name"), str)]


def save_halal_directory(rows: list[dict], path: Path = HALAL_DIRECTORY_PATH) -> bool:
    """Write the directory atomically. Returns False if it could not be saved."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        log.error("Could not save halal directory to %s: %s", path, exc)
        return False


def halal_directory_updated(path: Path = HALAL_DIRECTORY_PATH) -> datetime | None:
    """When the directory file was last written, or None if there is none."""
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime)
    except OSError:
        return None
