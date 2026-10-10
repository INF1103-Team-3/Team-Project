"""Coordinate local challenge state, SMTP, and account verification."""

import data_manager

from . import challenge, email_delivery


def get_challenge(user_id):
    saved = data_manager.get_state("verification", user_id)
    return challenge.validate_challenge(saved) if saved else None


def request_code(user, config):
    """Send a code and save its challenge, preserving old state on failure."""
    code, pending = challenge.new_challenge(
        get_challenge(user["userID"]),
        attempt_reset_seconds=config["verification_attempt_reset_seconds"],
    )
    email_delivery.send_verification_email(user["email"], code, config)
    data_manager.set_state("verification", user["userID"], pending)


def verify_code(user, code, config):
    """Check one code, persist failed attempts, then complete verification."""
    user_id = user["userID"]
    updated, error = challenge.check_challenge(
        get_challenge(user_id), code,
        attempt_reset_seconds=config["verification_attempt_reset_seconds"],
    )
    if updated and error:
        data_manager.set_state("verification", user_id, updated)
    if error:
        raise ValueError(error)
    if not user["email_verified"]:
        user = data_manager.save(dict(user, email_verified=True))
    data_manager.set_state("verification", user_id, None)
    return user
