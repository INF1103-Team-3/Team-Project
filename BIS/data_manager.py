"""Flat-file account storage. No terminal IO or AI interaction."""

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from support.debug_log import debug_log
from sources.profile_schema import (
    MINUTES_PER_KM, empty_preferences, normalize_email, normalize_username,
    validate_user, validate_preferences,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
USERS_FILE = DATA_DIR / "users.json"
STATE_FILE = DATA_DIR / "profile_state.json"
LAST_ERROR = None


def _read_json(path):
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


def _registry(validate=True):
    users = _read_json(USERS_FILE)
    emails = set()
    for user_id, user in users.items():
        if (
            not isinstance(user, dict) or not user_id
            or user.get("userID") != user_id
            or not isinstance(user.get("preferences"), dict)
            or type(user.get("email_verified", False)) is not bool
        ):
            raise ValueError(
                "Invalid user record in data/users.json; saved data was "
                "retained. See the repository README.md for migration or restore a backup."
            )
        email = normalize_email(user.get("email"))
        if email in emails:
            raise ValueError("Duplicate saved emails; restore the user file.")
        emails.add(email)
        if validate:
            users[user_id] = validate_user(user)
    return users


def load():
    """Return records, or [] on read errors; keep the file and block writes."""
    global LAST_ERROR
    try:
        records = list(_registry().values())
    except (ValueError, RuntimeError) as error:
        LAST_ERROR = str(error)
        debug_log("Registry read failed; writes blocked.",
                  "ERROR", "data.load")
        return []
    LAST_ERROR = None
    return records


def query(filter_fn):
    return [record for record in load() if filter_fn(record)]


def _atomic_write(path, value):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".profile-",
            suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(value, file, indent=4,
                      ensure_ascii=False, allow_nan=False)
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


def save(record):
    """Save one validated account, retaining every other account."""
    record = validate_user(record)
    users = _registry()
    if any(user["email"] == record["email"] and key != record["userID"]
           for key, user in users.items()):
        raise ValueError("This email is already registered.")
    users[record["userID"]] = record
    _atomic_write(USERS_FILE, users)
    debug_log("User record saved.", "INFO", "data.save")
    return record


def register_user(email, username):
    email = normalize_email(email)
    username = normalize_username(username)
    users = _registry()
    if any(user["email"] == email for user in users.values()):
        raise ValueError("This email is already registered. Choose resume.")
    user_id = str(uuid4())
    while user_id in users:
        user_id = str(uuid4())
    return save({
        "userID": user_id, "email": email, "email_verified": False,
        "username": username, "preferences": empty_preferences(),
    })


def find_user(email):
    email = normalize_email(email)
    users = _registry()
    for user in users.values():
        if user["email"] == email:
            return user
    raise ValueError("No profile found for this email. Please sign up first.")


def get_user(user_id):
    users = _registry()
    if user_id not in users:
        raise ValueError("Unknown userID. Please sign up first.")
    return users[user_id]


def save_preferences(user_id, preferences, config):
    user = get_user(user_id)
    if not user["email_verified"] and config.get("smtp_bypass") is not True:
        raise ValueError("Verify your email before changing preferences.")
    user["preferences"] = validate_preferences(preferences)
    result = save(user)
    debug_log(
        f"max_distance_km={preferences['max_distance_km']}, "
        f"max_travel_time_minutes={preferences['max_travel_time_minutes']}; "
        f"conversion assumption={MINUTES_PER_KM} min/km.",
        "INFO", "profile.travel",
    )
    return result


def get_state(section, user_id):
    state = _read_json(STATE_FILE)
    values = state.get(section, {})
    if not isinstance(values, dict):
        raise RuntimeError("Invalid internal profile state. Restore the file.")
    value = values.get(user_id)
    if value is not None and not isinstance(value, dict):
        raise RuntimeError("Invalid internal profile state. Restore the file.")
    return value


def set_state(section, user_id, value):
    state = _read_json(STATE_FILE)
    if not isinstance(state.get(section, {}), dict):
        raise RuntimeError("Invalid internal profile state. Restore the file.")
    values = state.setdefault(section, {})
    if value is None:
        values.pop(user_id, None)
    else:
        values[user_id] = value
    _atomic_write(STATE_FILE, state)


def _backup(path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(f"{path.name}.{stamp}.{uuid4().hex[:8]}.bak")
    shutil.copy2(path, target)
    return str(target)


def migrate_users():
    """Explicit, backed-up maintenance; never called during signup/startup."""
    from logic_manager import migrate_record

    users = _registry(validate=False)
    if not users:
        return {"migrated": 0, "backups": [], "reviews": 0}
    state = _read_json(STATE_FILE)
    for section in ("migration", "verification"):
        if not isinstance(state.get(section, {}), dict):
            raise RuntimeError("Invalid internal profile state.")
        state.setdefault(section, {})
    migrated = {}
    count = 0
    reviews = 0
    for user_id, old in users.items():
        try:
            migrated[user_id] = validate_user(old)
            continue
        except ValueError:
            pass
        user, notes = migrate_record(old)
        migrated[user_id] = validate_user(user)
        if notes.get("notices") or notes.get("other_text"):
            state["migration"][user_id] = notes
            reviews += 1
        challenge = old.get("email_verification")
        if isinstance(challenge, dict) and not user["email_verified"]:
            state["verification"][user_id] = challenge
        count += 1
    if not count:
        return {"migrated": 0, "backups": [], "reviews": 0}
    backups = [_backup(USERS_FILE)]
    if STATE_FILE.exists():
        backups.append(_backup(STATE_FILE))
    # Save review information first so a failed registry write loses no notes.
    _atomic_write(STATE_FILE, state)
    _atomic_write(USERS_FILE, migrated)
    debug_log("Registry migration completed with backup.",
              "INFO", "data.migrate")
    return {"migrated": count, "backups": backups, "reviews": reviews}
