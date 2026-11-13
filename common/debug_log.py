"""One operational log for BiteFinder, with a shared search trace ID.

Callers log stage names, counts and outcomes only. Never pass request bodies,
addresses, provider responses, URLs with keys, or account identifiers.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from uuid import uuid4

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "bitefinder.log"
DISPLAY = None
_TRACE_ID = ContextVar("bitefinder_trace_id", default=None)
_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def safe_error_detail(error, max_length=600):
    """Return one useful exception line with common secret forms redacted."""
    text = str(error).replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()
    substitutions = (
        (r"(?i)(bearer\s+)[^\s,;}]+", r"\1<redacted>"),
        (r"(?i)((?:api[_ -]?key|password|access[_ -]?token)\s*[:=]\s*)"
         r"[^\s,;}]+", r"\1<redacted>"),
        (r"(?i)([?&](?:key|token)=)[^&\s]+", r"\1<redacted>"),
    )
    for pattern, replacement in substitutions:
        text = re.sub(pattern, replacement, text)
    if not text:
        return "No exception message was provided."
    return text if len(text) <= max_length else text[:max_length - 3] + "..."


def _emit_python_log(record):
    """Send one standard-library logging record to the BiteFinder log."""
    level = record.levelname if record.levelname in _LEVELS else "ERROR"
    debug_log(record.getMessage(), level, f"BRC.{record.name}")


def _shared_log_handler():
    """Create a standard handler configured with a procedural callback."""
    handler = logging.Handler()
    handler.emit = _emit_python_log
    handler.bitefinder_shared_handler = True
    return handler


def configure_python_logging():
    """Connect BRC's existing Python loggers to the global log once."""
    root = logging.getLogger()
    if not any(getattr(handler, "bitefinder_shared_handler", False)
               for handler in root.handlers):
        root.addHandler(_shared_log_handler())
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


def adopt_trace(trace_id):
    """Adopt a validated upstream trace when this process has no active one."""
    if _TRACE_ID.get() is not None:
        return None
    if not isinstance(trace_id, str) or not re.fullmatch(
            r"[0-9a-f]{12}", trace_id):
        return start_trace()
    return _TRACE_ID.set(trace_id)


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
