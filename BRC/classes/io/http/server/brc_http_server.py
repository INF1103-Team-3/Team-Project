"""Lifecycle owner for BRC's independent HTTP service."""

import os
import signal
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from BRC.classes.data.data_manager import DataManager
from BRC.classes.io.http.server.brc_http_handler import BRCRequestHandler
from common import debug_log


class BRCHTTPServer:
    """Create, run, and gracefully stop the BRC HTTP server."""

    DEFAULT_REFRESH_CHECK_INTERVAL = 3600.0

    def __init__(
        self,
        host="0.0.0.0",
        port=None,
        handler=BRCRequestHandler,
        server_factory=ThreadingHTTPServer,
        refresh_interval=None,
    ):
        selected_port = int(
            os.getenv("BRC_PORT", "8000") if port is None else port
        )
        self._server = server_factory((host, selected_port), handler)
        self._handler = handler
        self._server.daemon_threads = True
        self._port = selected_port
        self._refresh_interval = (
            self._env_refresh_interval()
            if refresh_interval is None
            else float(refresh_interval)
        )
        self._stop_event = threading.Event()
        self._refresh_lock = threading.Lock()

    def serve(self):
        debug_log.configure_python_logging()
        self._install_signal_handlers()
        debug_log.debug_log(
            f"BRC service listening on port {self._port}.",
            "INFO",
            "BRC.service",
        )
        self._start_background_warm()
        self._start_refresh_watcher()
        try:
            self._server.serve_forever()
        finally:
            self._stop_event.set()
            self._server.server_close()

    def _start_background_warm(self):
        if os.getenv("BRC_AUTO_WARM", "1") == "0":
            return
        state = self._database_state()
        if state == "fresh":
            return
        blocking = state == "missing"

        def warm():
            if not self._refresh_lock.acquire(blocking=False):
                return
            try:
                if blocking:
                    with self._handler.serialized_checks():
                        if self._database_state() != "missing":
                            return
                        self._run_database_build("build")
                else:
                    self._run_database_build("refresh")
            finally:
                self._refresh_lock.release()

        threading.Thread(target=warm, daemon=True).start()

    def _start_refresh_watcher(self):
        if os.getenv("BRC_AUTO_WARM", "1") == "0":
            return
        if self._refresh_interval <= 0:
            return

        def watch():
            while not self._stop_event.wait(self._refresh_interval):
                self._start_background_warm()

        threading.Thread(target=watch, daemon=True).start()

    def _database_state(self):
        path = self._handler.database_path
        if not path.exists():
            return "missing"
        if not isinstance(path, (str, Path)):
            return "fresh"
        return DataManager(clean_path=Path(path)).clean_database_state()

    def _run_database_build(self, label):
        try:
            debug_log.debug_log(
                f"BRC background database {label} started.",
                "INFO",
                "BRC.service",
            )
            self._handler.application_run()
            debug_log.debug_log(
                f"BRC background database {label} finished.",
                "INFO",
                "BRC.service",
            )
        except Exception as error:
            debug_log.debug_log(
                f"BRC background database {label} failed: {error}",
                "WARNING",
                "BRC.service",
            )

    def stop(self, *_):
        self._stop_event.set()
        threading.Thread(target=self._server.shutdown, daemon=True).start()

    def _install_signal_handlers(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

    @classmethod
    def _env_refresh_interval(cls):
        try:
            return max(
                0.0,
                float(
                    os.getenv(
                        "BRC_REFRESH_CHECK_INTERVAL_SECONDS",
                        str(cls.DEFAULT_REFRESH_CHECK_INTERVAL),
                    )
                ),
            )
        except ValueError:
            return cls.DEFAULT_REFRESH_CHECK_INTERVAL


def serve():
    """Container entry point retained as a minimal bootstrap function."""
    BRCHTTPServer().serve()


if __name__ == "__main__":
    serve()
