"""One operational log for BiteFinder, with a shared search trace ID.

Callers log stage names, counts and outcomes only. Never pass request bodies,
addresses, provider responses, URLs with keys, or account identifiers.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import uuid4

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "bitefinder.log"
DISPLAY = None
_TRACE_ID = ContextVar("bitefinder_trace_id", default=None)
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class _SharedLogHandler(logging.Handler):
    """Send Python logging records to the BiteFinder log."""

    def emit(self, record):
        level = record.levelname if record.levelname in _LEVELS else "ERROR"
        debug_log(record.getMessage(), level, f"BRC.{record.name}")


def configure_python_logging():
    """Connect BRC's existing Python loggers to the global log once."""
    root = logging.getLogger()
    if not any(isinstance(handler, _SharedLogHandler) for handler in root.handlers):
        root.addHandler(_SharedLogHandler())
    root.setLevel(logging.INFO)


def configure(display=None):
    """Optionally mirror log lines to an IO-owned terminal callback."""
    global DISPLAY
    DISPLAY = display


def start_trace():
    """Start one trace unless a caller (such as BIS) already owns it."""
    if _TRACE_ID.get() is not None:
        return None
    return _TRACE_ID.set(uuid4().hex[:12])


def end_trace(token):
    """Clear only a trace started by the current caller."""
    if token is not None:
        _TRACE_ID.reset(token)


def current_trace_id():
    """Return the current search trace for a user-facing error reference."""
    return _TRACE_ID.get()


def debug_log(message, level="DEBUG", event="application"):
    """Append a concise operational event to the global log."""
    if level not in _LEVELS:
        raise ValueError("Unsupported log level.")
    message = str(message).replace("\n", " ").replace("\r", " ")
    event = str(event).replace("\n", " ").replace("\r", " ")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    trace = _TRACE_ID.get() or "-"
    line = f"{timestamp} | {level:<7} | {trace} | {event} | {message}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        if DISPLAY:
            DISPLAY("Debug log could not be written.")
    if DISPLAY:
        DISPLAY(line)
