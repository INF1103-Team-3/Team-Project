"""Lifecycle owner for BRC's independent HTTP service."""

import os
import signal
import threading
from http.server import ThreadingHTTPServer

from BRC.classes.brc_http_handler import BRCRequestHandler
from shared import debug_log


class BRCHTTPServer:
    """Create, run, and gracefully stop the BRC HTTP server."""

    def __init__(self, host="0.0.0.0", port=None,
                 handler=BRCRequestHandler,
                 server_factory=ThreadingHTTPServer):
        selected_port = int(
            os.getenv("BRC_PORT", "8000") if port is None else port)
        self._server = server_factory((host, selected_port), handler)
        self._server.daemon_threads = True
        self._port = selected_port

    def serve(self):
        debug_log.configure_python_logging()
        self._install_signal_handlers()
        debug_log.debug_log(
            f"BRC service listening on port {self._port}.",
            "INFO", "BRC.service")
        self._start_background_warm()
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()

    def _start_background_warm(self):
        if os.getenv("BRC_AUTO_WARM", "1") == "0":
            return
        if BRCRequestHandler.database_path.exists():
            return

        def warm():
            with BRCRequestHandler._run_lock:
                if BRCRequestHandler.database_path.exists():
                    return
                try:
                    debug_log.debug_log(
                        "BRC background database build started.",
                        "INFO", "BRC.service")
                    BRCRequestHandler.application_run()
                    debug_log.debug_log(
                        "BRC background database build finished.",
                        "INFO", "BRC.service")
                except Exception as error:
                    debug_log.debug_log(
                        f"BRC background database build failed: {error}",
                        "WARNING", "BRC.service")

        threading.Thread(target=warm, daemon=True).start()

    def stop(self, *_):
        threading.Thread(
            target=self._server.shutdown, daemon=True).start()

    def _install_signal_handlers(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)


def serve():
    """Container entry point retained as a minimal bootstrap function."""
    BRCHTTPServer().serve()


if __name__ == "__main__":
    serve()
