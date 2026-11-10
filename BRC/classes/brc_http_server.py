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
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()

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
