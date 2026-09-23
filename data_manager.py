"""JSON persistence for a single local CLI process; failed reads are preserved."""

import json
import os
import tempfile
from pathlib import Path

from debug import debug_log
from schemas import is_text, valid_profile, validate_bundle, validate_restaurant


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
    except (OSError, ValueError, UnicodeError, RecursionError):
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
    except (OSError, ValueError, TypeError, RecursionError):
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
    if not valid_profile(profile):
        return {}, "Stored profile is invalid."
    return profile, error


def save_profile(directory, name, profile):
    if not is_text(name) or not valid_profile(profile):
        return "Profile name or preferences are invalid."
    path = Path(directory) / "users.json"
    profiles, error = load_json(path, dict)
    if error:
        return error
    profiles[name] = profile
    return save_json(path, profiles)


def query_restaurants(restaurants, name=""):
    """Filter stored records by a case-insensitive name substring."""
    return [r for r in restaurants if name.casefold() in r["name"].casefold()]


def load_restaurants(directory):
    """Load sourced, validated records; report rejected rows to the caller."""
    records, error = load_json(Path(directory) / "restaurants.json")
    if error:
        return [], error
    sources, error = load_json(Path(directory) / "sources.json")
    if error:
        return [], error
    imported, import_error = load_imported_catalog(directory)
    if import_error:
        return [], import_error
    from logic_manager import validate_import_conflicts

    for bundle in imported:
        existing = [record for record in records if isinstance(record, dict)
                    and all(is_text(record.get(field)) for field in
                            ("restaurant_id", "name", "address"))]
        error = validate_import_conflicts(existing, sources, bundle)
        if error:
            return [], "Imported catalog conflicts with existing data; original files preserved."
        records.extend(bundle["restaurants"])
        sources.extend(bundle["sources"])
    references = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        reference = source.get("source_reference")
        if (isinstance(source_id, str) and isinstance(reference, str)
                and reference.startswith("https://") and reference.isprintable()):
            references[source_id] = reference
    source_ids = set(references)
    valid, seen, rejected = [], set(), 0
    for record in records:
        if not validate_restaurant(record, source_ids):
            rejected += 1
        elif record["restaurant_id"] in seen:
            rejected += 1
        else:
            ids = set(record["source_ids"])
            for item in record["menu"]:
                ids.update(item["source_ids"])
            record["source_references"] = [references[sid] for sid in sorted(ids)]
            valid.append(record)
            seen.add(record["restaurant_id"])
    if rejected:
        debug_log("data_invalid", "error", rejected)
    warning = None
    if rejected:
        warning = f"Skipped {rejected} invalid or duplicate restaurant records."
    return valid, warning


def load_history(directory, name, limit=10):
    records, error = load_json(Path(directory) / "interactions.json")
    if error:
        return [], error
    matches = [record for record in records if isinstance(record, dict)
               and record.get("profile") == name]
    return matches[-limit:], None


def load_imported_catalog(directory):
    bundles, error = load_json(Path(directory) / "catalog_imports.json")
    if error:
        return [], error
    if any(validate_bundle(bundle) for bundle in bundles):
        return [], "Imported catalog is invalid; repair it before searching or importing."
    return bundles, None


def read_import_file(directory, filename):
    """Read a bounded JSON file strictly inside data/incoming; never follow escapes."""
    if (not isinstance(filename, str) or Path(filename).name != filename
            or not filename.endswith(".json")):
        return None, "Enter a JSON filename from the data/incoming directory."
    try:
        root = Path(directory).resolve()
        incoming = root / "incoming"
        if incoming.is_symlink():
            return None, "The incoming directory cannot be a symbolic link."
        path = incoming / filename
        if path.is_symlink() or path.resolve().parent != incoming:
            return None, "Import files must stay inside data/incoming."
        with path.open("rb") as source:
            content = source.read(1_000_001)
        if len(content) > 1_000_000:
            return None, "Import files must be no larger than 1 MB."
        bundle = json.loads(content)
    except (OSError, ValueError, RecursionError):
        return None, "Import file is missing, unreadable or not valid JSON."
    error = validate_bundle(bundle)
    if error:
        debug_log("import_invalid", "error")
        return None, error
    return bundle, None


def prepare_import(directory, bundle):
    """Recheck against the current catalog both before preview and before save."""
    from logic_manager import validate_import_conflicts

    records, error = load_restaurants(directory)
    if error:
        return None, error
    sources, error = load_json(Path(directory) / "sources.json")
    if error:
        return None, error
    imported, error = load_imported_catalog(directory)
    if error:
        return None, error
    for previous in imported:
        sources.extend(previous["sources"])
    error = validate_import_conflicts(records, sources, bundle)
    if error:
        debug_log("import_invalid", "error")
        return None, error
    return imported + [bundle], None


def save_import(directory, bundle):
    catalog, error = prepare_import(directory, bundle)
    if error:
        return error
    error = save_json(Path(directory) / "catalog_imports.json", catalog)
    if not error:
        debug_log("import_saved", count=len(bundle["restaurants"]))
    return error
