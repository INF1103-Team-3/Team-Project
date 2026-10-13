FROM python:3.11-slim-bookworm AS source
ARG SEED_ACCOUNTS=yes
WORKDIR /src
COPY . .
RUN set -eux; \
    mkdir -p BIS/data BRC/data BRNS/data data logs /seed; \
    find data logs -mindepth 1 -delete; \
    find BIS/data BRC/data BRNS/data \
        \( -name '.gitkeep' -o -name '*.lock' -o -name '*.tmp' -o -name '*.bak' \) -delete; \
    if [ "$SEED_ACCOUNTS" != "yes" ]; then \
        rm -f BIS/data/users.json BIS/data/profile_state.json; \
    fi; \
    cp -a BIS/data /seed/bis; \
    cp -a BRNS/data /seed/brns; \
    cp -a BRC/data /seed/brc; \
    find BIS/data BRNS/data BRC/data -mindepth 1 -delete


FROM python:3.11-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY <<'EOF' /usr/local/bin/docker-entrypoint.sh
#!/bin/sh
set -e
mkdir -p /data/logs
for src in /opt/seed/*/; do
    [ -d "$src" ] || continue
    name=${src%/}
    name=${name##*/}
    mkdir -p "/data/$name"
done
if [ ! -e /data/.seeded ]; then
    for src in /opt/seed/*/; do
        [ -d "$src" ] || continue
        name=${src%/}
        name=${name##*/}
        (cd "$src" && find . -type f) | while IFS= read -r file; do
            target="/data/$name/${file#./}"
            if [ ! -e "$target" ]; then
                mkdir -p "${target%/*}"
                cp -p "$src${file#./}" "$target"
            fi
        done
    done
    touch /data/.seeded
fi
exec "$@"
EOF
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh


FROM base AS brc

COPY --from=source --chown=10001:10001 /src/BRC /app/BRC
COPY --from=source --chown=10001:10001 /src/shared /app/shared

RUN mkdir -p /opt/seed/brc
COPY --from=source --chown=10001:10001 /seed/brc/ /opt/seed/brc/

RUN set -eux; \
    mkdir -p /data/brc /data/logs; \
    cp -a /opt/seed/brc/. /data/brc/; \
    rm -rf /app/BRC/data /app/logs; \
    ln -s /data/brc  /app/BRC/data; \
    ln -s /data/logs /app/logs; \
    chown -R 10001:10001 /data


COPY --chown=10001:10001 <<'PYEOF' /app/brc_service.py
"""Serve BRC restaurant checks to the BIS/BRNS container."""
import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from BRC import main as brc_main
from shared import debug_log

MAX_BODY_BYTES = 5 * 1024 * 1024
RUN_LOCK = threading.Lock()  # BRC paces its AI requests, so run one check at a time


def send_json(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/health":
            send_json(self, 200, {"status": "ok"})
        elif self.path == "/status":
            exists = brc_main.data_manager.CLEAN_DATABASE_PATH.exists()
            send_json(self, 200, {"database_exists": bool(exists)})
        else:
            send_json(self, 404, {"error": "Not found."})

    def do_POST(self):
        if self.path != "/check":
            send_json(self, 404, {"error": "Not found."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("Request body is missing or too large.")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            send_json(self, 400, {"error": f"Invalid request: {error}"})
            return
        with RUN_LOCK:
            token = debug_log.start_trace()
            try:
                result = brc_main.run(value)
            except ValueError as error:
                send_json(self, 400, {"error": str(error)})
                return
            except Exception as error:  # report every other failure to the caller
                debug_log.debug_log(
                    f"BRC service check failed: {type(error).__name__}.",
                    "ERROR", "BRC.service")
                send_json(self, 500, {"error": f"{type(error).__name__}: {error}"})
                return
            finally:
                debug_log.end_trace(token)
        send_json(self, 200, result)


def serve():
    debug_log.configure_python_logging()
    port = int(os.getenv("BRC_PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"BRC service listening on port {port}", file=sys.stderr, flush=True)
    server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    serve()
PYEOF


VOLUME ["/data"]
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "/app/brc_service.py"]


FROM base AS bis-brns

COPY --from=source --chown=10001:10001 /src/ /app/


RUN mkdir -p /opt/seed/bis /opt/seed/brns
COPY --from=source --chown=10001:10001 /seed/bis/ /opt/seed/bis/
COPY --from=source --chown=10001:10001 /seed/brns/ /opt/seed/brns/
RUN set -eux; \
    mkdir -p /data/bis /data/brns /data/logs; \
    cp -a /opt/seed/bis/. /data/bis/; \
    cp -a /opt/seed/brns/. /data/brns/; \
    rm -rf /app/BIS/data /app/BRNS/data /app/data /app/logs; \
    mkdir -p /app/BRC/data; \
    ln -s /data/bis  /app/BIS/data; \
    ln -s /data/brns /app/BRNS/data; \
    ln -s /data/brns /app/data; \
    ln -s /data/logs /app/logs; \
    chown -R 10001:10001 /data /app/BRC/data


COPY <<'PYEOF' /opt/bitefinder/brc_remote.py
"""Stand-in for BRC.main that talks to the BRC container over HTTP."""
import json
import os
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

NO_INPUT = object()


def _base_url():
    return os.environ["BRC_SERVICE_URL"].rstrip("/")


def _timeout():
    try:
        return float(os.getenv("BRC_SERVICE_TIMEOUT", "1800"))
    except ValueError:
        return 1800.0


def _request(path, payload=None):
    """Call the BRC service; retry only while it cannot be reached at all."""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    unreachable = None
    for attempt in range(4):
        request = urllib.request.Request(
            _base_url() + path, data=data, headers=headers,
            method="GET" if data is None else "POST")
        try:
            with urllib.request.urlopen(request, timeout=_timeout()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            try:
                text = json.loads(text).get("error", text)
            except (ValueError, AttributeError):
                pass
            raise RuntimeError(f"BRC service error {error.code}: {text}") from error
        except urllib.error.URLError as error:
            unreachable = error
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"BRC service call failed: {error}") from error
    raise RuntimeError(
        f"BRC service is unreachable at {_base_url()}: {unreachable}")


def run(value=NO_INPUT, **_ignored):
    """Check one restaurant object or an array in the BRC container."""
    if value is NO_INPUT:
        raise RuntimeError(
            "Build the BRC database in the BRC container: "
            "docker exec -it <brc container> python -m BRC.main")
    return _request("/check", value)


def _database_exists():
    try:
        return bool(_request("/status").get("database_exists"))
    except RuntimeError:
        return False


data_manager = SimpleNamespace(
    CLEAN_DATABASE_PATH=SimpleNamespace(exists=_database_exists))
PYEOF


COPY <<'PYEOF' /opt/bitefinder/sitecustomize.py
import importlib.util
import os
import sys

if os.environ.get("BRC_SERVICE_URL"):
    _spec = importlib.util.spec_from_file_location(
        "BRC.main", "/opt/bitefinder/brc_remote.py")
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    sys.modules["BRC.main"] = _module
PYEOF

ENV PYTHONPATH=/opt/bitefinder${PYTHONPATH:+:${PYTHONPATH}}


VOLUME ["/data"]
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "main.py"]
