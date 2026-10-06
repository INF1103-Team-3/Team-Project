"""Procedural profile decisions, conversions, migration, and verification."""

import hashlib
import re
import secrets
import time
from copy import deepcopy
from difflib import SequenceMatcher

from sources.profile_schema import (
    CUISINES, CUISINE_FIELDS, MINUTES_PER_KM, OTHER_PREFERENCES,
    UNSUPPORTED_CUISINES, VERIFICATION_MAX_ATTEMPTS,
    VERIFICATION_RESEND_SECONDS, VERIFICATION_TTL_SECONDS,
    PREFERENCE_FIELDS, empty_preferences, normalize_username,
    validate_preferences, validate_updates, validate_value,
)


def estimate_travel_limits(updates):
    """Complete only this update's missing counterpart, never an old value."""
    updates = dict(updates)
    distance = updates.get("max_distance_km")
    minutes = updates.get("max_travel_time_minutes")
    if distance is not None and minutes is None:
        updates["max_travel_time_minutes"] = round(
            distance * MINUTES_PER_KM, 2)
    elif minutes is not None and distance is None:
        updates["max_distance_km"] = max(
            0.01, round(minutes / MINUTES_PER_KM, 2))
    return updates


def apply_updates(preferences, updates, location_action="add"):
    """Build a new profile; reject conflicts without mutating the old one."""
    if location_action not in {"add", "replace", "remove"}:
        raise ValueError("Choose add, replace, or remove for locations.")
    result = deepcopy(validate_preferences(preferences))
    updates = estimate_travel_limits(validate_updates(updates))
    if "location" in updates:
        old = result["location"] or []
        incoming = updates["location"]
        if location_action == "add":
            updates["location"] = list(dict.fromkeys(old + incoming))
        elif location_action == "remove":
            if any(item not in old for item in incoming):
                raise ValueError("That location is not in your saved list.")
            updates["location"] = [
                item for item in old if item not in incoming]
    result.update(updates)
    return validate_preferences(result)


def cuisine_conflicts(preferences, updates):
    proposed = dict(preferences)
    proposed.update(updates)
    return sorted(set(proposed.get("liked_cuisines") or []) & set(
        proposed.get("disliked_cuisines") or []
    ))


def cuisine_tokens(text, field):
    """Recognize simple cuisine lists without dropping unknown text."""
    text = text.strip().lower().rstrip(".!?")
    if text in {"none", "no preference", "no preferences"}:
        return []
    negative = re.match(
        r"(?:i\s+)?(?:don't like|do not like|dislike|avoid|hate)\b", text)
    positive = re.match(r"(?:i\s+)?(?:like|love|enjoy|prefer)\b", text)
    if negative and field == "liked_cuisines":
        raise ValueError("That describes dislikes. Enter cuisines you like.")
    if positive and field == "disliked_cuisines":
        raise ValueError("That describes likes. Enter cuisines you avoid.")
    text = re.sub(
        r"^(?:i\s+)?(?:don't like|do not like|dislike|avoid|hate|like|love|"
        r"enjoy|prefer)(?:\s+eating)?\s+", "", text,
    )
    parts = re.split(r"\s*(?:,|\band\b|&)\s*", text)
    tokens = []
    for part in parts:
        part = re.sub(r"\s+(?:food|cuisines?|dishes)$", "", part).strip()
        if not part or not re.fullmatch(r"[a-z]+(?:[ -][a-z]+)*", part):
            raise ValueError(
                "Enter cuisine names separated by commas, or none.")
        if part not in tokens:
            tokens.append(part)
    return tokens


def cuisine_suggestions(token):
    """Suggest close matches; never correct automatically."""
    if len(token) < 4:
        return []
    ranked = sorted(
        ((SequenceMatcher(None, token, name).ratio(), name)
         for name in CUISINES),
        reverse=True,
    )
    best = ranked[0][0]
    if best < 0.78:
        return []
    return [name for score, name in ranked if score >= max(0.78, best - 0.08)]


def needs_cuisine_interpretation(text, field):
    """Use AI for complex phrasing; keep typo confirmations local."""
    tokens = cuisine_tokens(text, field)
    unresolved = any(
        token not in CUISINES and token not in UNSUPPORTED_CUISINES
        and not cuisine_suggestions(token) for token in tokens
    )
    known_mention = any(
        re.search(r"\b" + re.escape(name) + r"\b", text.lower())
        for name in CUISINES
    )
    return unresolved and known_mention and len(text.split()) >= 4


def parse_local_answer(text, field):
    """Produce a typed update; cuisine confirmations are handled by IO."""
    from sources.profile_schema import clean_text

    text = clean_text(text, 1000)
    if field in {"max_distance_km", "max_travel_time_minutes"}:
        match = re.fullmatch(
            r"(\d+(?:\.\d{1,2})?)\s*(km|mins?|minutes?)?", text.lower(),
        )
        if not match or (field == "max_distance_km" and match[2] is None):
            raise ValueError(
                "Enter a number with units, e.g. 1 km or 20 mins.")
        target = "max_distance_km" if match[2] == "km" else (
            "max_travel_time_minutes"
        )
        return estimate_travel_limits(
            validate_updates({target: float(match[1])}))
    if field == "budget_per_person":
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
            raise ValueError("Enter SGD as a number, e.g. 5 or 5.50.")
        return validate_updates({field: float(text)})
    if field == "location":
        return validate_updates({field: text.split(",")})
    if field == "dietary_requirements":
        lowered = text.lower()
        if lowered in {"none", "no restrictions", "no dietary requirements"}:
            items = []
        elif lowered == "both":
            items = ["halal", "vegan"]
        else:
            items = re.split(r"\s*(?:,|\band\b|&)\s*", lowered)
        return validate_updates({field: items})
    if field in CUISINE_FIELDS:
        return validate_updates({field: cuisine_tokens(text, field)})
    if field == OTHER_PREFERENCES:
        return {
            field: "" if text.lower() in {
                "none",
                "no preference"} else text}
    raise ValueError("Choose a valid preference field.")


def next_field(preferences):
    for field in PREFERENCE_FIELDS:
        if preferences[field] is None:
            return field
    return None


def hash_verification_code(code, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode(), salt.encode("ascii"), 100_000,
    ).hex()


def new_challenge(previous=None, now=None):
    now = time.time() if now is None else now
    if previous:
        validate_challenge(previous)
    if previous and now < previous["sent_at"] + VERIFICATION_RESEND_SECONDS:
        raise ValueError("Wait 60 seconds between verification emails.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    return code, {
        "salt": salt, "code_hash": hash_verification_code(code, salt),
        "sent_at": now, "expires_at": now + VERIFICATION_TTL_SECONDS,
        "attempts": 0,
    }


def check_challenge(challenge, code, now=None):
    """Return attempt state and any error for the caller to persist."""
    now = time.time() if now is None else now
    if not challenge:
        return None, "Request a verification code first."
    validate_challenge(challenge)
    updated = dict(challenge)
    if now >= updated["expires_at"]:
        return updated, "Verification code expired. Use /resend."
    if updated["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
        return updated, "Too many incorrect attempts. Use /resend."
    updated["attempts"] += 1
    valid = isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code.strip())
    if valid:
        valid = secrets.compare_digest(
            hash_verification_code(code.strip(), updated["salt"]),
            updated["code_hash"],
        )
    return updated, None if valid else "Incorrect verification code."


def migrate_record(old):
    """Return a new record and review notes without modifying the source."""
    legacy = old.get("preferences", {})
    notes = {"notices": []}
    user = {key: old[key] for key in ("userID", "email")}
    user["email_verified"] = old.get("email_verified", False)
    name = old.get("username")
    if not name:
        names = list(dict.fromkeys(v for v in (
            legacy.get("username"), legacy.get("name"),
        ) if isinstance(v, str) and v.strip()))
        name = names[0] if len(names) == 1 else None
    try:
        user["username"] = normalize_username(name)
    except ValueError:
        user["username"] = None
        notes["notices"].append(
            "Please confirm a username of 1–50 characters.")
    preferences = empty_preferences()
    for field in PREFERENCE_FIELDS:
        value = legacy.get(field)
        if field == "location" and isinstance(value, str):
            value = [value]
        try:
            preferences[field] = validate_value(field, value)
        except ValueError:
            notes["notices"].append(f"Please answer {field} again.")
    if cuisine_conflicts(preferences, {}):
        preferences["liked_cuisines"] = None
        preferences["disliked_cuisines"] = None
        notes["notices"].append("Please clarify your cuisine preferences.")
    preferences.update(estimate_travel_limits({
        key: preferences[key] for key in (
            "max_distance_km", "max_travel_time_minutes",
        ) if preferences[key] is not None
    }))
    if preferences[OTHER_PREFERENCES] is None:
        fragments = []
        spice = legacy.get("spice_preference")
        if isinstance(spice, str) and spice.strip():
            fragments.append("Spice preference: " + spice.strip())
        dining = legacy.get("dining_preferences")
        if isinstance(dining, list) and all(isinstance(v, str)
                                            for v in dining):
            if dining:
                fragments.append("Dining preferences: " + ", ".join(dining))
        proposed = "; ".join(fragments)
        if proposed:
            try:
                notes["other_text"] = validate_value(
                    OTHER_PREFERENCES, proposed)
            except ValueError:
                notes["notices"].append("Please re-enter extra preferences.")
    user["preferences"] = validate_preferences(preferences)
    return user, notes


def validate_challenge(challenge):
    """Reject corrupt verification state before using timestamps or hashes."""
    import math

    if not isinstance(challenge, dict) or set(challenge) != {
        "salt", "code_hash", "sent_at", "expires_at", "attempts",
    }:
        raise ValueError("Invalid verification state. Restore the state file.")
    if not isinstance(challenge["salt"], str) or not re.fullmatch(
        r"[0-9a-f]{32}", challenge["salt"],
    ):
        raise ValueError("Invalid verification state.")
    if not isinstance(challenge["code_hash"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", challenge["code_hash"],
    ):
        raise ValueError("Invalid verification state.")
    if type(challenge["attempts"]) is not int or challenge["attempts"] < 0:
        raise ValueError("Invalid verification state.")
    for field in ("sent_at", "expires_at"):
        value = challenge[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Invalid verification state.")
