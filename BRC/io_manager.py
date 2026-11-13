"""Compatibility façade for BRC terminal interaction classes."""

from BRC.classes.io.console.console_progress import ConsoleProgress
from BRC.classes.io.console.io_manager import (
    DEFAULT_RESTAURANTS_PATH,
    NO_INPUT,
    IOManager,
)


__all__ = [
    "ConsoleProgress",
    "DEFAULT_RESTAURANTS_PATH",
    "IOManager",
    "NO_INPUT",
]
