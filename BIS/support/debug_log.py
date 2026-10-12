"""File logging with an optional IO-owned display callback."""

from datetime import datetime
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parents[1] / "logs" / "bitefinder.log"
DISPLAY = None


def configure(display=None):
    global DISPLAY
    DISPLAY = display


def debug_log(message, level="DEBUG", event="application"):
    """Log operational events; never pass secrets or raw payloads."""
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError("Unsupported log level.")
    message = str(message).replace("\n", " ").replace("\r", " ")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    line = f"{timestamp} | {level:<7} | {event} | {message}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        if DISPLAY:
            DISPLAY("Debug log could not be written.")
    if DISPLAY:
        DISPLAY(line)
