"""Coordinate local challenge state, SMTP, and account verification."""

import data_manager

from .classes.service.email_verification_service import EmailVerificationService
from .classes.delivery.smtp_email_delivery import SMTPEmailDelivery
from .classes.challenge.verification_challenge_manager import (
    VerificationChallengeManager,
)


_verification_service = EmailVerificationService(
    data_manager, VerificationChallengeManager(), SMTPEmailDelivery())


def get_challenge(user_id):
    return _verification_service.get_challenge(user_id)


def request_code(user, config):
    """Send a code and save its challenge, preserving old state on failure."""
    return _verification_service.request_code(user, config)


def verify_code(user, code, config):
    """Check one code, persist failed attempts, then complete verification."""
    return _verification_service.verify_code(user, code, config)
