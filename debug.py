"""Milestone logging using controlled event names, never raw user/API data."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


EVENTS = {
    "config_loaded", "data_loaded", "data_missing", "data_invalid",
    "data_saved", "write_failed", "input_validated", "ai_started",
    "ai_received", "ai_invalid", "ai_failed", "filtered", "ranked",
    "results_displayed", "validation_failed", "route_failed",
    "route_received", "profile_updated",
}


def debug_log(operation, status="ok", count=None):
    """Accept only enumerated events and numeric counts to exclude secrets."""
    if operation not in EVENTS or status not in {"ok", "error"}:
        return False
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "status": status,
    }
    if type(count) is int:
        record["count"] = count
    try:
        directory = Path(os.environ.get("BITEFINDER_LOG_DIR", "logs"))
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "bitefinder_debug.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps(record) + "\n")
        return True
    except OSError:
        return False
