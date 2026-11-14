"""Environment configuration; no user interaction."""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

import ai_manager
from common.debug_log import debug_log

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


def load_config():
    """Load application configuration from environment variables."""
    load_dotenv(ENV_FILE)
    ai_bypass = os.getenv("AI_BYPASS", "false").strip().lower() == "true"
    smtp_bypass = os.getenv("SMTP_BYPASS", "false").strip().lower() == "true"
    env_values = dotenv_values(ENV_FILE) if ENV_FILE.is_file() else {}

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
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "").strip(),
        "groq_api_key": os.getenv("GROQ_API_KEY", "").strip(),
        "google_maps_api_key": os.getenv("GOOGLE_MAPS_API_KEY", "").strip(),
        "google_maps_js_api_key": os.getenv("GOOGLE_MAPS_JS_API_KEY", "").strip(),
        "use_live_google": (
            os.getenv("USE_LIVE_GOOGLE", "true").strip().lower() != "false"
        ),
        "smtp_host": os.getenv("SMTP_HOST", "").strip(),
        "smtp_bypass": smtp_bypass,
        "_smtp_bypass_initial": smtp_bypass,
        "_had_env_smtp_bypass": "SMTP_BYPASS" in env_values,
        "_env_file": str(ENV_FILE),
        "smtp_security": (
            os.getenv("SMTP_SECURITY", "starttls").strip().lower()
        ),
        "smtp_port": _read_positive_int(
            os.getenv("SMTP_PORT", "587"), default=587,
        ),
        "smtp_username": os.getenv("SMTP_USERNAME", "").strip(),
        "smtp_password": os.getenv("SMTP_PASSWORD", ""),
        "smtp_from_email": os.getenv("SMTP_FROM_EMAIL", "").strip(),
        "verification_attempt_reset_seconds": 60 * _read_positive_int(
            os.getenv("VERIFICATION_ATTEMPT_RESET_MINUTES", "10"),
            default=10,
        ),
    }

    debug_log("Configuration loaded.", "DEBUG", "BIS.config.load")
    return config


def is_smtp_bypass(config):
    """Read SMTP_BYPASS live from .env unless explicitly overridden in memory."""
    if not isinstance(config, dict):
        return False
    env_path_str = config.get("_env_file")
    if not env_path_str:
        return config.get("smtp_bypass") is True
    if "_smtp_bypass_initial" in config and (
        bool(config.get("smtp_bypass")) != bool(config.get("_smtp_bypass_initial"))
    ):
        return config.get("smtp_bypass") is True
    env_path = Path(env_path_str)
    if env_path.is_file():
        values = dotenv_values(env_path)
        if "SMTP_BYPASS" in values and values["SMTP_BYPASS"] is not None:
            return str(values["SMTP_BYPASS"]).strip().lower() == "true"
        if config.get("_had_env_smtp_bypass"):
            return False
    return config.get("smtp_bypass") is True


def validate_config(config):
    """Return a list of configuration errors."""
    errors = []
    if config.get("ai_bypass") is True:
        return errors
    if (not config.get("openrouter_api_keys")
            and not ai_manager.has_fallback_provider(config)):
        errors.append(
            "Set OPENROUTER_API_KEYS, OPENROUTER_API_KEY, or "
            "GEMINI_API_KEY for BIS in .env."
        )

    if (config.get("openrouter_api_keys")
            and not config.get("openrouter_model")
            and not ai_manager.has_fallback_provider(config)):
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
