"""Compatibility façade for object-oriented verification challenges."""

from .classes.verification_challenge_manager import (
    VerificationChallengeManager,
)


_challenge_manager = VerificationChallengeManager()

VERIFICATION_TTL_SECONDS = _challenge_manager.TTL_SECONDS
VERIFICATION_RESEND_SECONDS = _challenge_manager.RESEND_SECONDS
VERIFICATION_MAX_ATTEMPTS = _challenge_manager.MAX_ATTEMPTS


def hash_verification_code(code, salt):
    return _challenge_manager.hash_code(code, salt)


def validate_challenge(challenge):
    """Normalize old saved challenges and reject corrupt verification state."""
    return _challenge_manager.validate(challenge)


def new_challenge(previous=None, now=None, *, attempt_reset_seconds):
    """Make a new code, carrying the failed-attempt count across resends."""
    return _challenge_manager.create(
        previous, now, attempt_reset_seconds=attempt_reset_seconds)


def check_challenge(challenge, code, now=None, *, attempt_reset_seconds):
    """Return updated state and an error, consuming one attempt if invalid."""
    return _challenge_manager.check(
        challenge, code, now,
        attempt_reset_seconds=attempt_reset_seconds,
    )
