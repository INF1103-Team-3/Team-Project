"""Shared list-oriented JSON persistence behavior for BRNS."""

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from shared.debug_log import debug_log


class BaseJsonStore(ABC):
    """Abstract BRNS JSON store with compatible missing/corrupt handling."""

    def __init__(self, records_path):
        self._records_path = Path(records_path)

    def _load_json(self, path):
        path = Path(path)
        if not path.exists():
            debug_log(
                "Saved JSON file is missing; using an empty collection.",
                "WARNING", "BRNS.data.load",
            )
            return None
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError):
            debug_log(
                "Saved JSON file is unreadable; using an empty collection.",
                "ERROR", "BRNS.data.load",
            )
            return None

    def _save_json(self, path, data, *, compact_hours=False):
        path = Path(path)
        try:
            if compact_hours:
                data = self._ordered_hours(data)
            formatted = json.dumps(data, indent=2, ensure_ascii=False)
            if compact_hours:
                formatted = re.sub(
                    r'\[\n[ \t]*"(\d{4})",\n[ \t]*"(\d{4})"\n[ \t]*\]',
                    r'["\1", "\2"]', formatted,
                )
                formatted = re.sub(
                    r'\[\n(?:[ \t]*\["\d{4}", "\d{4}"\],?\n)+[ \t]*\]',
                    lambda match: "[" + ", ".join(re.findall(
                        r'\["\d{4}", "\d{4}"\]', match.group(0))) + "]",
                    formatted,
                )
            with path.open("w", encoding="utf-8") as file:
                file.write(formatted + "\n")
            return True
        except OSError:
            return False

    @staticmethod
    def _ordered_hours(data):
        weekdays = (
            "monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday",
        )
        ordered = []
        for row in data:
            if not isinstance(row, dict):
                ordered.append(row)
                continue
            record = dict(row)
            hours = record.get("opening_hours")
            if isinstance(hours, dict):
                record["opening_hours"] = {
                    day: hours[day] for day in weekdays if day in hours
                }
            ordered.append(record)
        return ordered

    @abstractmethod
    def load(self):
        """Load the concrete store's primary record collection."""
