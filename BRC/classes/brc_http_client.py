"""Client adapter for the separately deployed BRC HTTP service."""

import json
import os
import time
import urllib.error
import urllib.request

from shared import debug_log


class BRCHTTPClient:
    """Verify restaurants through BRC's stable HTTP contract."""

    def __init__(self, base_url=None, timeout=None, opener=None,
                 sleep=time.sleep):
        self._base_url = (
            base_url or os.environ["BRC_SERVICE_URL"]).rstrip("/")
        self._timeout = timeout if timeout is not None else self._env_timeout()
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep

    def database_missing(self):
        try:
            return not bool(
                self._request("/status").get("database_exists"))
        except RuntimeError:
            return True

    def verify(self, restaurant):
        return self._request("/check", restaurant)

    def _request(self, path, payload=None):
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(
                payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        trace_id = debug_log.current_trace_id()
        if trace_id:
            headers["X-BiteFinder-Trace-ID"] = trace_id
        unreachable = None
        for attempt in range(4):
            request = urllib.request.Request(
                self._base_url + path,
                data=data,
                headers=headers,
                method="GET" if data is None else "POST")
            try:
                with self._open(request, timeout=self._timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                text = error.read().decode("utf-8", errors="replace")
                try:
                    text = json.loads(text).get("error", text)
                except (ValueError, AttributeError):
                    pass
                raise RuntimeError(
                    f"BRC service error {error.code}: {text}") from error
            except urllib.error.URLError as error:
                unreachable = error
                if attempt < 3:
                    self._sleep(2 * (attempt + 1))
            except (OSError, ValueError) as error:
                raise RuntimeError(
                    f"BRC service call failed: {error}") from error
        raise RuntimeError(
            f"BRC service is unreachable at {self._base_url}: "
            f"{unreachable}")

    @staticmethod
    def _env_timeout():
        try:
            return float(os.getenv("BRC_SERVICE_TIMEOUT", "1800"))
        except ValueError:
            return 1800.0
