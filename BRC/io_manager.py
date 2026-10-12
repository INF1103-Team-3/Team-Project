"""Validate restaurant JSON and load the existing MUIS snapshot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from BRC import data_manager


def accept_check_input(value) -> tuple[list[dict], bool]:
    """Validate the caller's object/array without dropping extra fields."""
    single = isinstance(value, dict)
    if not single and not isinstance(value, list):
        raise ValueError("BRC requires a restaurant object or array of objects.")
    records = [value] if single else value
    for index, record in enumerate(records):
        if (not isinstance(record, dict)
                or not isinstance(record.get("name"), str)
                or not record["name"].strip()
                or not isinstance(record.get("address"), str)
                or not record["address"].strip()):
            raise ValueError(f"Restaurant {index + 1} needs a name and address.")
        if record.get("postal_code") is not None and not isinstance(
                record["postal_code"], str):
            raise ValueError(f"Restaurant {index + 1} has an invalid postal code.")
        if "dietary" in record and not isinstance(record["dietary"], list):
            raise ValueError(f"Restaurant {index + 1} has invalid dietary data.")
    return records, single


def read_check_input(path: Path | None = None):
    """Read JSON from a file or standard input; never scrape on this path."""
    try:
        text = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
        return json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read restaurant JSON input.") from exc


def load_check_snapshot(path: Path = data_manager.MUIS_SNAPSHOT_PATH) -> dict:
    return data_manager.load_muis_snapshot(path)
