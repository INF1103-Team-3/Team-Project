"""Email verification challenge creation and validation."""

import hashlib
import math
import re
import secrets
import time

from ..contracts.challenge_manager_interface import ChallengeManagerInterface


class VerificationChallengeManager(ChallengeManagerInterface):
    """Own the lifecycle and validation rules for short-lived codes."""

    TTL_SECONDS = 600
    RESEND_SECONDS = 60
    MAX_ATTEMPTS = 5

    _LEGACY_FIELDS = {
        "salt", "code_hash", "sent_at", "expires_at", "attempts",
    }
    _FIELDS = _LEGACY_FIELDS | {"attempt_window_started_at"}

    def hash_code(self, code, salt):
        return hashlib.pbkdf2_hmac(
            "sha256", code.encode(), salt.encode("ascii"), 100_000,
        ).hex()

    def validate(self, challenge):
        """Normalize old saved challenges and reject corrupt state."""
        if not isinstance(challenge, dict) or set(challenge) not in (
                self._FIELDS, self._LEGACY_FIELDS):
            raise ValueError(
                "Invalid verification state. Restore the state file.")
        normalized = dict(challenge)
        if set(normalized) == self._LEGACY_FIELDS:
            normalized["attempt_window_started_at"] = normalized["sent_at"]
        if not isinstance(normalized["salt"], str) or not re.fullmatch(
                r"[0-9a-f]{32}", normalized["salt"]):
            raise ValueError("Invalid verification state.")
        if not isinstance(normalized["code_hash"], str) or not re.fullmatch(
                r"[0-9a-f]{64}", normalized["code_hash"]):
            raise ValueError("Invalid verification state.")
        if (type(normalized["attempts"]) is not int
                or normalized["attempts"] < 0):
            raise ValueError("Invalid verification state.")
        for field in ("sent_at", "expires_at", "attempt_window_started_at"):
            value = normalized[field]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("Invalid verification state.")
        if (normalized["attempt_window_started_at"]
                > normalized["expires_at"]
                or normalized["expires_at"] <= normalized["sent_at"]):
            raise ValueError("Invalid verification state.")
        return normalized

    def _limit_message(self, challenge, now, attempt_reset_seconds):
        remaining = max(1, math.ceil(
            (challenge["attempt_window_started_at"]
             + attempt_reset_seconds - now) / 60))
        unit = "minute" if remaining == 1 else "minutes"
        return (
            "Too many incorrect attempts. "
            f"Wait {remaining} {unit} before requesting another code."
        )

    def create(self, previous=None, now=None, *, attempt_reset_seconds):
        """Create a code while carrying attempts across quick resends."""
        if type(attempt_reset_seconds) is not int \
                or attempt_reset_seconds <= 0:
            raise ValueError("Verification attempt reset must be positive.")
        now = time.time() if now is None else now
        previous = self.validate(previous) if previous else None
        if previous and now < (
                previous["attempt_window_started_at"]
                + attempt_reset_seconds):
            if previous["attempts"] >= self.MAX_ATTEMPTS:
                raise ValueError(self._limit_message(
                    previous, now, attempt_reset_seconds))
            attempts = previous["attempts"]
            window_start = previous["attempt_window_started_at"]
        else:
            attempts = 0
            window_start = now
        if previous and now < previous["sent_at"] + self.RESEND_SECONDS:
            raise ValueError(
                "Wait 60 seconds between verification emails.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(16)
        return code, {
            "salt": salt,
            "code_hash": self.hash_code(code, salt),
            "sent_at": now,
            "expires_at": now + self.TTL_SECONDS,
            "attempts": attempts,
            "attempt_window_started_at": window_start,
        }

    def check(self, challenge, code, now=None, *, attempt_reset_seconds):
        """Return updated state and an error, consuming invalid attempts."""
        if type(attempt_reset_seconds) is not int \
                or attempt_reset_seconds <= 0:
            raise ValueError("Verification attempt reset must be positive.")
        now = time.time() if now is None else now
        if not challenge:
            return None, "Request a verification code first."
        updated = self.validate(challenge)
        if now >= updated["expires_at"]:
            return updated, "Verification code expired. Use /resend."
        if (now >= updated["attempt_window_started_at"]
                + attempt_reset_seconds):
            updated["attempt_window_started_at"] = now
            updated["attempts"] = 0
        if updated["attempts"] >= self.MAX_ATTEMPTS:
            return updated, self._limit_message(
                updated, now, attempt_reset_seconds)
        valid = (
            isinstance(code, str)
            and re.fullmatch(r"[0-9]{6}", code.strip())
        )
        if valid:
            valid = secrets.compare_digest(
                self.hash_code(code.strip(), updated["salt"]),
                updated["code_hash"],
            )
        if valid:
            return updated, None
        updated["attempts"] += 1
        if updated["attempts"] >= self.MAX_ATTEMPTS:
            return updated, self._limit_message(
                updated, now, attempt_reset_seconds)
        return updated, "Incorrect verification code."
