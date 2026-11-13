"""BRNS standard-input command-line boundary."""

import json
import os
import sys


class BRNSCLIApplication:
    """Read one BIS JSON payload and display its BRNS result."""

    def __init__(
            self, workflow, io_manager, config, logger, terminal_ui):
        self._workflow = workflow
        self._io = io_manager
        self._config = config
        self._log = logger
        self._terminal_ui = terminal_ui

    def run(self, argv=None):
        arguments = list(sys.argv[1:] if argv is None else argv)
        allowed = (
            os.getenv("BITEFINDER_INTERNAL_CLI") == "1"
            or "--internal" in arguments
        )
        if not allowed:
            self._terminal_ui.message(
                "Direct BRNS execution is disabled. Start BiteFinder through "
                "BIS (`python main.py`).",
                "error",
            )
            raise SystemExit(1)
        self._log.configure(
            self._io.display_debug if self._config.DEBUG else None)
        try:
            results = self._workflow.search(json.load(sys.stdin))
        except json.JSONDecodeError:
            self._terminal_ui.message(
                "BRNS requires valid BIS search JSON.", "error")
            return
        except (ValueError, RuntimeError, OSError) as error:
            self._terminal_ui.message(error, "error")
            return
        self._io.show_results(results)
