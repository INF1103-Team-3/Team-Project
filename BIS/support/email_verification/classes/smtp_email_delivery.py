"""SMTP implementation of the BIS email delivery contract."""

import smtplib
import ssl
from email.message import EmailMessage

from common.debug_log import debug_log
from sources.profile_schema import normalize_email

from .email_delivery_interface import EmailDeliveryInterface


class SMTPEmailDelivery(EmailDeliveryInterface):
    """Build and deliver verification and Maps-link messages over TLS."""

    def validate_config(self, config):
        """Validate SMTP settings without exposing credentials."""
        if not config.get("smtp_host"):
            raise ValueError(
                "Set SMTP_HOST in .env to send verification emails.")
        if config.get("smtp_security") not in {"starttls", "ssl"}:
            raise ValueError("SMTP_SECURITY must be starttls or ssl.")
        port = config.get("smtp_port", 0)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("SMTP_PORT must be between 1 and 65535.")
        if bool(config.get("smtp_username")) != bool(
                config.get("smtp_password")):
            raise ValueError(
                "Set both SMTP_USERNAME and SMTP_PASSWORD in .env.")
        try:
            normalize_email(config.get("smtp_from_email"))
        except ValueError as error:
            raise ValueError(
                "Set a valid SMTP_FROM_EMAIL in .env.") from error

    def send_verification_email(self, email, code, config):
        """Deliver a code without printing or logging sensitive values."""
        self.validate_config(config)
        message = EmailMessage()
        message["Subject"] = "Your BiteFinder email verification code"
        message["From"] = normalize_email(config["smtp_from_email"])
        message["To"] = normalize_email(email)
        message.set_content(
            f"Your BiteFinder verification code is: {code}\n\n"
            "This code expires in 10 minutes. If you did not request it, "
            "you can ignore this email.\n"
        )
        self._send_message(message, config, "verification email")
        debug_log("Verification email sent.", "INFO", "BIS.email.send")

    def send_maps_link_email(self, email, restaurant_name, link, config):
        """Send one selected restaurant's Google Maps directions link."""
        self.validate_config(config)
        message = EmailMessage()
        message["Subject"] = "Your BiteFinder Google Maps link"
        message["From"] = normalize_email(config["smtp_from_email"])
        message["To"] = normalize_email(email)
        message.set_content(
            f"Google Maps directions to {restaurant_name}:\n{link}\n")
        self._send_message(message, config, "Maps link email")
        debug_log("Maps link email sent.", "INFO", "BIS.email.send")

    def _send_message(self, message, config, kind):
        """Deliver an SMTP message without logging contents or credentials."""
        context = ssl.create_default_context()
        try:
            if config["smtp_security"] == "ssl":
                connection = smtplib.SMTP_SSL(
                    config["smtp_host"], config["smtp_port"],
                    timeout=30, context=context,
                )
            else:
                connection = smtplib.SMTP(
                    config["smtp_host"], config["smtp_port"], timeout=30,
                )
            with connection as server:
                if config["smtp_security"] == "starttls":
                    server.starttls(context=context)
                if config.get("smtp_username"):
                    server.login(
                        config["smtp_username"], config["smtp_password"])
                if server.send_message(message):
                    raise RuntimeError(
                        "The verification email was refused.")
        except (OSError, RuntimeError) as error:
            debug_log("Email delivery failed.", "ERROR", "BIS.email.send")
            raise RuntimeError(
                f"Could not send {kind}. Check SMTP settings and try again."
            ) from error
