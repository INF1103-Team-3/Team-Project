"""HTTP transport adapter for the independent BRC service."""

import json
import threading
from http.server import BaseHTTPRequestHandler

from BRC import main as brc_main
from BRC.classes.data.data_manager import CLEAN_DATABASE_PATH
from common import debug_log


MAX_BODY_BYTES = 5 * 1024 * 1024


class BRCRequestHandler(BaseHTTPRequestHandler):
    """Expose BRC health, status, and check operations over HTTP."""

    protocol_version = "HTTP/1.1"
    _run_lock = threading.Lock()
    application_run = staticmethod(brc_main.run)
    database_path = CLEAN_DATABASE_PATH

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
        elif self.path == "/status":
            self._send_json(200, {
                "database_exists": bool(self.database_path.exists()),
            })
        else:
            self._send_json(404, {"error": "Not found."})

    def do_POST(self):
        if self.path != "/check":
            self._send_json(404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("Request body is missing or too large.")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            self._send_json(400, {"error": f"Invalid request: {error}"})
            return
        with self._run_lock:
            token = debug_log.adopt_trace(
                self.headers.get("X-BiteFinder-Trace-ID"))
            try:
                result = self.application_run(value)
            except ValueError as error:
                self._send_json(400, {"error": str(error)})
                return
            except Exception as error:
                detail = debug_log.safe_error_detail(error)
                debug_log.debug_log(
                    f"BRC service check failed: {type(error).__name__}: "
                    f"{detail}", "ERROR", "BRC.service")
                self._send_json(500, {
                    "error": f"{type(error).__name__}: {error}",
                })
                return
            finally:
                debug_log.end_trace(token)
        self._send_json(200, result)

    def _send_json(self, status, payload):
        body = json.dumps(
            payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
