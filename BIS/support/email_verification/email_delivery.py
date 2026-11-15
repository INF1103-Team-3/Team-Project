"""Compatibility façade for object-oriented SMTP email delivery."""

from .classes.delivery.smtp_email_delivery import SMTPEmailDelivery


_email_delivery = SMTPEmailDelivery()


def validate_email_config(config):
    """Validate SMTP delivery settings without exposing credentials."""
    return _email_delivery.validate_config(config)


def send_verification_email(email, code, config):
    """Deliver a code over TLS; never print or log the code or SMTP errors."""
    return _email_delivery.send_verification_email(email, code, config)


def send_maps_link_email(email, restaurant_name, link, config):
    """Send one selected restaurant's Google Maps directions link."""
    return _email_delivery.send_maps_link_email(
        email, restaurant_name, link, config)


def _send_message(message, config, kind):
    """Deliver an SMTP message without logging its contents or credentials."""
    return _email_delivery._send_message(message, config, kind)
