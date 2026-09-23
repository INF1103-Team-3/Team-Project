"""Configuration from environment variables; never reads mounted secret files."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_config():
    return {
        "data_dir": Path(os.environ.get("BITEFINDER_DATA_DIR", ROOT / "data")),
        "api_key": os.environ.get("OPENROUTER_API_KEY", "").strip(),
        "model": os.environ.get("OPENROUTER_MODEL", "").strip(),
        "timeout": 20,
        "google_maps_key": os.environ.get("GOOGLE_MAPS_API_KEY", "").strip(),
        "routing_key": os.environ.get("OPENROUTESERVICE_API_KEY", "").strip(),
    }
