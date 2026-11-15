"""Atomic JSON file persistence used by BRC."""

import json
import os
import re
import tempfile
import time
from pathlib import Path

from BRC.classes.data.storage.data_unavailable_error import DataUnavailableError


class JsonFile:
    """Read and atomically replace one JSON document."""

    def __init__(self, path):
        self._path = Path(path)

    @property
    def path(self):
        return self._path

    def exists(self):
        return self._path.exists()

    def read(self):
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DataUnavailableError(
                f"Cannot read valid JSON from {self._path}.") from error

    def write(self, value, compact_hours=False):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self._path.parent,
                    prefix=f".{self._path.name}.", suffix=".tmp",
                    delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(self.format_json(value, compact_hours))
                stream.flush()
                os.fsync(stream.fileno())
            self._replace(temporary)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def delete(self):
        self._path.unlink(missing_ok=True)

    def _replace(self, temporary):
        for attempt in range(8):
            try:
                os.replace(temporary, self._path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))

    @staticmethod
    def format_json(value, compact_hours=False):
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
