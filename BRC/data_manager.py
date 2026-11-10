"""Compatibility façade for BRC persistence classes."""

from BRC.classes.data_manager import (
    CLEAN_DATABASE_PATH,
    DATA_DIR,
    RAW_MUIS_PATH,
    DataManager,
)
from BRC.classes.data_unavailable_error import DataUnavailableError
from BRC.classes.json_file import JsonFile


__all__ = [
    "CLEAN_DATABASE_PATH",
    "DATA_DIR",
    "RAW_MUIS_PATH",
    "DataManager",
    "DataUnavailableError",
    "JsonFile",
]
