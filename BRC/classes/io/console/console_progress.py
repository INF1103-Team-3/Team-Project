"""Terminal progress presentation for long-running BRC operations."""

import re
import sys


class ConsoleProgress:
    """Render BRC scrape progress to an interactive or redirected stream."""

    WIDTH = 28

    def __init__(self, stream=None):
        self._stream = stream or sys.stderr
        self._interactive = bool(
            getattr(self._stream, "isatty", lambda: False)())
        self._last_stage = None
        self._last_report = None

    def __call__(self, stage, current, total, detail):
        total = max(total, 1)
        current = min(max(current, 0), total)
        line = self._line(stage, current, total, detail)
        if self._interactive:
            self._stream.write("\r\033[2K" + line)
            self._stream.flush()
        report = (stage, current, total)
        changed = stage != self._last_stage or current == total
        if not self._interactive and changed and report != self._last_report:
            self._stream.write(line + "\n")
        self._last_stage, self._last_report = stage, report

    def finish(self):
        if self._interactive:
            self._stream.write("\n")
            self._stream.flush()

    def _line(self, stage, current, total, detail):
        filled = round(self.WIDTH * current / total)
        bar = "#" * filled + "-" * (self.WIDTH - filled)
        label = "MUIS" if stage == "retrieve" else "OneMap"
        detail = re.sub(r"\s+", " ", detail).strip()
        if len(detail) > 58:
            detail = detail[:55] + "..."
        return (
            f"[{bar}] {current / total:6.1%} {label}: "
            f"{current}/{total} | {detail}")
