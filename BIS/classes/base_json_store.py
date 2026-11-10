"""Shared safe JSON-object persistence for BIS stores."""

import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class BaseJsonStore(ABC):
    """Abstract JSON store with atomic writes and retained-file failures."""

    def __init__(self, records_path):
        self._records_path = Path(records_path)

    def _read_json(self, path):
        path = Path(path)
        try:
            with path.open(encoding="utf-8") as file:
                value = json.load(file)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise RuntimeError(
                "Cannot read saved data. Restore the file before writing; "
                "existing data has been retained."
            ) from error
        if not isinstance(value, dict):
            raise RuntimeError("Saved data must contain a JSON object.")
        return value

    def _atomic_write(self, path, value):
        path = Path(path)
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent,
                prefix=".profile-", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(
                    value, file, indent=4, ensure_ascii=False,
                    allow_nan=False,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError) as error:
            raise RuntimeError(
                "Save failed. Check permissions and disk space; "
                "the previous file was retained."
            ) from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @abstractmethod
    def load(self):
        """Load records in the concrete store's public format."""
