"""JSON persistence for a single local CLI process; failed reads are preserved."""

import json
import os
import tempfile
from pathlib import Path

from debug import debug_log


def load_json(path, expected_type=list):
    """Return (data, error); distinguish missing files from damaged files."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, expected_type):
            raise ValueError("Invalid root type")
        debug_log("data_loaded")
        return data, None
    except FileNotFoundError:
        debug_log("data_missing")
        return expected_type(), None
    except (OSError, ValueError, UnicodeError):
        debug_log("data_invalid", "error")
        return expected_type(), "Stored data could not be read; original file preserved."


def save_json(path, data):
    """Write atomically so an interrupted save cannot truncate existing data."""
    path = Path(path)
    temporary = None
    try:
        content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(content + "\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        debug_log("data_saved")
        return None
    except (OSError, ValueError, TypeError):
        debug_log("write_failed", "error")
        return "Could not save data. Check directory permissions and free space."
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def append_interaction(directory, interaction):
    path = Path(directory) / "interactions.json"
    records, error = load_json(path)
    if error:
        return error
    records.append(interaction)
    return save_json(path, records)


def load_profile(directory, name):
    profiles, error = load_json(Path(directory) / "users.json", dict)
    profile = profiles.get(name, {})
    if not isinstance(profile, dict):
        return {}, "Stored profile is invalid."
    return profile, error


def save_profile(directory, name, profile):
    path = Path(directory) / "users.json"
    profiles, error = load_json(path, dict)
    if error:
        return error
    profiles[name] = profile
    return save_json(path, profiles)


def query_restaurants(restaurants, name=""):
    """Filter stored records by a case-insensitive name substring."""
    return [r for r in restaurants if name.casefold() in r["name"].casefold()]
