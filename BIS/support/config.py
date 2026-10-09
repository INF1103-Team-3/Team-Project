"""Environment configuration; no user interaction."""

import os
from pathlib import Path

from dotenv import load_dotenv

import ai_manager
from shared.debug_log import debug_log

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


def load_config():
    """Load application configuration from environment variables."""
    load_dotenv(ENV_FILE)
    ai_bypass = os.getenv("AI_BYPASS", "false").strip().lower() == "true"

    config = {
        "app_name": (
            os.getenv("APP_NAME", "BiteFinder").strip() or "BiteFinder"
        ),
        "ai_bypass": ai_bypass,
        "debug": os.getenv("DEBUG", "false").strip().lower() == "true",
        "openrouter_api_keys": [] if ai_bypass else ai_manager.load_api_keys(),
        "openrouter_key_index": 0,
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "").strip(),
        "openrouter_base_url": os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).rstrip("/"),
        "openrouter_timeout_seconds": _read_positive_int(
            os.getenv("OPENROUTER_TIMEOUT_SECONDS", "30"),
            default=30,
        ),
        "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY", "").strip(),
        "smtp_host": os.getenv("SMTP_HOST", "").strip(),
        "smtp_bypass": (
            os.getenv("SMTP_BYPASS", "false").strip().lower() == "true"
        ),
        "smtp_security": (
            os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        ),
        "smtp_port": _read_positive_int(
            os.getenv("SMTP_PORT", "587"), default=587,
        ),
        "smtp_username": os.getenv("SMTP_USERNAME", "").strip(),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_from_email": os.getenv("SMTP_FROM_EMAIL", "").strip(),
    }

    debug_log("Configuration loaded.", "DEBUG", "BIS.config.load")
    return config


def validate_config(config):
    """Return a list of configuration errors."""
    errors = []
    if config.get("ai_bypass") is True:
        return errors
    if not config.get("openrouter_api_keys"):
        errors.append(
            "Set OPENROUTER_API_KEYS, OPENROUTER_API_KEYS_FILE, or "
            "OPENROUTER_API_KEY in .env."
        )

    if not config.get("openrouter_model"):
        errors.append("Set OPENROUTER_MODEL in .env.")

    debug_log(f"Configuration validated with {len(errors)} error(s).",
              "DEBUG", "BIS.config.validate")
    return errors


def _read_positive_int(value, default):
    """Convert a value to a positive integer, otherwise return the default."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return default

    if parsed_value <= 0:
        return default

    return parsed_value
