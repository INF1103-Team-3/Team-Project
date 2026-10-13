"""Classify BRC input and load data for each workflow."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from BRC import data_manager

NO_INPUT = object()
DEFAULT_RESTAURANTS_PATH = (
    Path(__file__).resolve().parent.parent / "BRNS" / "data" / "restaurants.json")
CLEAN_DATABASE_REQUIRED = "BRC_CLEAN_DATABASE_REQUIRED"


def clean_database_required(error):
    """Return the procedural signal used when BRC must build its database."""
    return RuntimeError(CLEAN_DATABASE_REQUIRED)


def is_clean_database_required(error):
    return isinstance(error, RuntimeError) and str(error) == CLEAN_DATABASE_REQUIRED

def validate_restaurants(value):
    single = isinstance(value, dict)
    if not single and not isinstance(value, list):
        raise ValueError("BRC requires one restaurant object or an array.")
    records = [value] if single else value
    if not records: raise ValueError("The restaurant array cannot be empty.")
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict) or not str(record.get("name") or "").strip():
            raise ValueError(f"Restaurant {index} needs a name.")
        if not str(record.get("address") or "").strip() and not re.fullmatch(
                r"\d{6}", str(record.get("postal_code") or "")):
            raise ValueError(f"Restaurant {index} needs an address or postal code.")
        if "dietary" in record and not isinstance(record["dietary"], list):
            raise ValueError(f"Restaurant {index} has invalid dietary data.")
    return records, single

def read_json_input(path=None):
    try:
        text = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
        return json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Could not read restaurant JSON input.") from exc

def collect_interactive_input():
    """Choose a standalone BRC workflow and return its input value."""
    print("\nBiteFinder Restaurant Checker")
    print("  1. Build or refresh the cleaned MUIS halal database")
    print(f"  2. Check the default restaurant file ({DEFAULT_RESTAURANTS_PATH})")
    print("  3. Check a restaurant JSON file (one object or an array)")
    print("  4. Paste one restaurant JSON object")
    print("  5. Check a file containing one restaurant JSON object")
    while True:
        choice = input("Choose 1–5 [Enter = 1]: ").strip() or "1"
        if choice in {"1", "2", "3", "4", "5"}:
            break
        print("Choose a number from 1 to 5.")
    if choice == "1":
        return NO_INPUT
    if choice == "2":
        path = DEFAULT_RESTAURANTS_PATH
    elif choice in {"3", "5"}:
        entered = input("Restaurant JSON file path: ").strip().strip('"')
        if not entered:
            raise ValueError("Restaurant JSON file path cannot be empty.")
        path = Path(entered).expanduser()
    else:
        try:
            value = json.loads(input("Paste one restaurant JSON object: "))
        except json.JSONDecodeError as exc:
            raise ValueError("The pasted restaurant JSON is invalid.") from exc
        if not isinstance(value, dict):
            raise ValueError("Paste one restaurant JSON object, not an array.")
        return value
    value = read_json_input(path)
    if choice == "5" and not isinstance(value, dict):
        raise ValueError("The selected file must contain one restaurant object.")
    return value


def display_record(record):
    """Display one checked restaurant as JSON."""
    print(json.dumps(record, ensure_ascii=False, indent=2))


def display_list(records):
    """Display a checked restaurant collection as JSON."""
    print(json.dumps(list(records), ensure_ascii=False, indent=2))


def display_result(result):
    """Display a concise result for a completed BRC workflow."""
    if isinstance(result, list):
        print(f"Checked {len(result)} restaurant(s).")
    else:
        print("Checked 1 restaurant.")


def display_status(message, *, error=False):
    """Display one BRC status message from the IO boundary."""
    print(message, file=sys.stderr if error else sys.stdout)

def postal(record):
    value = str(record.get("postal_code") or "")
    if re.fullmatch(r"\d{6}", value): return value
    found = re.findall(r"\b\d{6}\b", str(record.get("address") or ""))
    return found[-1] if found else None

def key(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))

def candidate_sets(records, database):
    result = []
    for record in records:
        code = postal(record)
        candidates = [row for row in database if code and row["postal_code"] == code]
        if not candidates:
            name, address = key(record["name"]), key(record.get("address"))
            candidates = [row for row in database
                          if key(row["name"]) == name or key(row["address"]) == address]
        result.append(candidates[:25])
    return result

def prepare_workflow(value=NO_INPUT, *, raw_path=data_manager.RAW_MUIS_PATH,
                     clean_path=data_manager.CLEAN_DATABASE_PATH,
                     scrape_progress=None):
    if value is NO_INPUT:
        try: raw = data_manager.load_raw_snapshot(raw_path)
        except (ValueError, OSError):
            from BRC import scraper
            raw = scraper.scrape_all(raw_path, progress=scrape_progress)
        return {"scenario": "build_database", "raw_snapshot": raw,
                "clean_path": Path(clean_path)}
    records, single = validate_restaurants(value)
    try: database = data_manager.load_clean_database(clean_path)
    except (ValueError, OSError) as exc:
        raise clean_database_required(exc) from exc
    return {"scenario": "check_restaurants", "records": records, "single": single,
            "database": database, "candidates": candidate_sets(records, database)}
