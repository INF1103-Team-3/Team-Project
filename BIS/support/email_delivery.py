"""SMTP delivery helper; no terminal IO, verification rules, or storage."""

import smtplib
import ssl
from email.message import EmailMessage

from shared.debug_log import debug_log
from sources.profile_schema import normalize_email


def validate_email_config(config):
    """Validate SMTP delivery settings without exposing credentials."""
    if not config.get("smtp_host"):
        raise ValueError("Set SMTP_HOST in .env to send verification emails.")
    if config.get("smtp_security") not in {"starttls", "ssl"}:
        raise ValueError("SMTP_SECURITY must be starttls or ssl.")
    port = config.get("smtp_port", 0)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT must be between 1 and 65535.")
    if bool(config.get("smtp_username")) != bool(config.get("smtp_password")):
        raise ValueError("Set both SMTP_USERNAME and SMTP_PASSWORD in .env.")
    try:
        normalize_email(config.get("smtp_from_email"))
    except ValueError as error:
        raise ValueError("Set a valid SMTP_FROM_EMAIL in .env.") from error


def send_verification_email(email, code, config):
    """Deliver a code over TLS; never print or log the code or SMTP errors."""
    validate_email_config(config)
    message = EmailMessage()
    message["Subject"] = "Your BiteFinder email verification code"
    message["From"] = normalize_email(config["smtp_from_email"])
    message["To"] = normalize_email(email)
    message.set_content(
        f"Your BiteFinder verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you did not request it, "
        "you can ignore this email.\n"
    )
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
                server.login(config["smtp_username"], config["smtp_password"])
            if server.send_message(message):
                raise RuntimeError("The verification email was refused.")
    except (OSError, RuntimeError) as error:
        debug_log("Email delivery failed.", "ERROR", "BIS.email.send")
        raise RuntimeError(
            "Could not send verification email. Check SMTP settings "
            "and try again."
        ) from error
    debug_log("Verification email sent.", "INFO", "BIS.email.send")
