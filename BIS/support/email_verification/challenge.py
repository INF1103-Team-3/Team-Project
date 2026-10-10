"""Create and check short-lived email codes without storing plaintext codes."""

import hashlib
import math
import re
import secrets
import time


VERIFICATION_TTL_SECONDS = 600
VERIFICATION_RESEND_SECONDS = 60
VERIFICATION_MAX_ATTEMPTS = 5

_LEGACY_FIELDS = {"salt", "code_hash", "sent_at", "expires_at", "attempts"}
_FIELDS = _LEGACY_FIELDS | {"attempt_window_started_at"}


def hash_verification_code(code, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode(), salt.encode("ascii"), 100_000,
    ).hex()


def validate_challenge(challenge):
    """Normalize old saved challenges and reject corrupt verification state."""
    if not isinstance(challenge, dict) or set(challenge) not in (
            _FIELDS, _LEGACY_FIELDS):
        raise ValueError("Invalid verification state. Restore the state file.")
    normalized = dict(challenge)
    if set(normalized) == _LEGACY_FIELDS:
        normalized["attempt_window_started_at"] = normalized["sent_at"]
    if not isinstance(normalized["salt"], str) or not re.fullmatch(
            r"[0-9a-f]{32}", normalized["salt"]):
        raise ValueError("Invalid verification state.")
    if not isinstance(normalized["code_hash"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", normalized["code_hash"]):
        raise ValueError("Invalid verification state.")
    if type(normalized["attempts"]) is not int or normalized["attempts"] < 0:
        raise ValueError("Invalid verification state.")
    for field in ("sent_at", "expires_at", "attempt_window_started_at"):
        value = normalized[field]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Invalid verification state.")
    if (normalized["attempt_window_started_at"] > normalized["expires_at"]
            or normalized["expires_at"] <= normalized["sent_at"]):
        raise ValueError("Invalid verification state.")
    return normalized


def _limit_message(challenge, now):
    remaining = max(1, math.ceil(
        (challenge["attempt_window_started_at"]
         + VERIFICATION_TTL_SECONDS - now) / 60))
    unit = "minute" if remaining == 1 else "minutes"
    return ("Too many incorrect attempts. "
            f"Wait {remaining} {unit} before requesting another code.")


def new_challenge(previous=None, now=None):
    """Make a new code, carrying the failed-attempt count across resends."""
    now = time.time() if now is None else now
    previous = validate_challenge(previous) if previous else None
    if previous and now < (previous["attempt_window_started_at"]
                           + VERIFICATION_TTL_SECONDS):
        if previous["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
            raise ValueError(_limit_message(previous, now))
        attempts = previous["attempts"]
        window_start = previous["attempt_window_started_at"]
    else:
        attempts = 0
        window_start = now
    if previous and now < previous["sent_at"] + VERIFICATION_RESEND_SECONDS:
        raise ValueError("Wait 60 seconds between verification emails.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    salt = secrets.token_hex(16)
    return code, {
        "salt": salt, "code_hash": hash_verification_code(code, salt),
        "sent_at": now, "expires_at": now + VERIFICATION_TTL_SECONDS,
        "attempts": attempts, "attempt_window_started_at": window_start,
    }


def check_challenge(challenge, code, now=None):
    """Return updated state and an error, consuming one attempt if invalid."""
    now = time.time() if now is None else now
    if not challenge:
        return None, "Request a verification code first."
    updated = validate_challenge(challenge)
    if now >= updated["expires_at"]:
        return updated, "Verification code expired. Use /resend."
    if now >= updated["attempt_window_started_at"] + VERIFICATION_TTL_SECONDS:
        updated["attempt_window_started_at"] = now
        updated["attempts"] = 0
    if updated["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
        return updated, _limit_message(updated, now)
    valid = isinstance(code, str) and re.fullmatch(r"[0-9]{6}", code.strip())
    if valid:
        valid = secrets.compare_digest(
            hash_verification_code(code.strip(), updated["salt"]),
            updated["code_hash"],
        )
    if valid:
        return updated, None
    updated["attempts"] += 1
    if updated["attempts"] >= VERIFICATION_MAX_ATTEMPTS:
        return updated, _limit_message(updated, now)
    return updated, "Incorrect verification code."
