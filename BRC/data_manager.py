"""Load MUIS snapshots and save checked restaurant JSON atomically."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path


MUIS_SNAPSHOT_PATH = Path(__file__).with_name("data") / "muis_establishments.json"


def load_muis_snapshot(path: Path = MUIS_SNAPSHOT_PATH) -> dict:
    """Read a complete, current MUIS snapshot; never use a partial refresh."""
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"MUIS snapshot unavailable. Run BRC.muis_data_scraper first: {path}"
        ) from exc
    if (not isinstance(snapshot, dict) or snapshot.get("complete") is not True
            or not isinstance(snapshot.get("listings"), list)
            or not isinstance(snapshot.get("covered_names"), list)
            or not snapshot["covered_names"]
            or not isinstance(snapshot.get("fetched_at"), str)
            or snapshot.get("listing_count") != len(snapshot["listings"])
            or snapshot.get("source_url") !=
            "https://halal.muis.gov.sg/halal/establishments"
            or any(not isinstance(name, str) or not name
                   for name in snapshot["covered_names"])
            or any(not isinstance(row, dict)
                   or any(not isinstance(row.get(field), str)
                          or not row[field] for field in (
                              "certificate_number", "name", "address",
                              "postal_code", "scheme"))
                   for row in snapshot["listings"])):
        raise ValueError("MUIS snapshot is invalid or incomplete. Refresh it first.")
    from datetime import timezone, timedelta
    try:
        fetched = datetime.fromisoformat(snapshot["fetched_at"])
    except ValueError as exc:
        raise ValueError("MUIS snapshot has an invalid retrieval time.") from exc
    if (fetched.tzinfo is None or datetime.now(timezone.utc) - fetched
            > timedelta(days=7) or fetched > datetime.now(timezone.utc)
            + timedelta(minutes=5)):
        raise ValueError("MUIS snapshot is stale. Refresh it first.")
    return snapshot


def write_json_atomic(data, path: Path) -> None:
    """Write JSON without exposing a half-written snapshot or result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_muis_snapshot(snapshot: dict, path: Path = MUIS_SNAPSHOT_PATH) -> None:
    if snapshot.get("complete") is not True or not snapshot.get("covered_names"):
        raise ValueError("Refusing to save an incomplete MUIS snapshot.")
    write_json_atomic(snapshot, path)


def save_checked_output(checked, path: Path) -> None:
    write_json_atomic(checked, path)
