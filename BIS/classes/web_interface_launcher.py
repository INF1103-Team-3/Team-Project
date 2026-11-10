"""Own bounded web-stack startup and host browser integration."""

import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import webbrowser


class WebInterfaceLauncher:
    def __init__(self, root=None, runner=subprocess.run, opener=urllib.request.urlopen,
                 browser=webbrowser.open, clock=time.monotonic, sleep=time.sleep,
                 in_container=None, url=None, ready_url=None, timeout=120):
        self._root = Path(root or Path(__file__).resolve().parents[2])
        self._runner, self._open, self._browser = runner, opener, browser
        self._clock, self._sleep = clock, sleep
        self._container = Path("/.dockerenv").exists() if in_container is None else in_container
        self._url = url or os.getenv("BITEFINDER_WEB_URL", "http://localhost:8080")
        self._ready_url = ready_url or os.getenv(
            "BITEFINDER_WEB_READY_URL",
            "http://web/api/health" if self._container else self._url + "/api/health")
        self._timeout = timeout

    def _ready(self):
        try:
            with self._open(self._ready_url, timeout=3) as response:
                return response.status == 200 and json.loads(response.read()).get("mongodb") is True
        except (OSError, ValueError):
            return False

    def start(self):
        if self._container:
            if not self._ready():
                raise RuntimeError("Web stack is unavailable. On the host run: "
                                   "docker compose -f docker-compose.web.yml up -d --build")
        else:
            if not self._ready():
                try:
                    self._runner(["docker", "compose", "version"], cwd=self._root,
                                 check=True, capture_output=True, text=True, timeout=20)
                    self._runner(["docker", "compose", "-f", "docker-compose.web.yml",
                                  "up", "-d", "--no-recreate", "mongodb", "brc", "api", "web"],
                                 cwd=self._root, check=True, capture_output=True,
                                 text=True, timeout=300)
                except (OSError, subprocess.SubprocessError) as error:
                    raise RuntimeError("Could not start the web stack. Check Docker/Compose "
                                       "and run docker compose -f docker-compose.web.yml logs on the host.") from error
                deadline = self._clock() + self._timeout
                while not self._ready():
                    if self._clock() >= deadline:
                        raise RuntimeError("Web readiness timed out. Check API/MongoDB container logs; "
                                           "the stack has not been stopped or deleted.")
                    self._sleep(1)
        opened = False
        if not self._container:
            try:
                opened = bool(self._browser(self._url))
            except (webbrowser.Error, OSError):
                pass
        return {"url": self._url, "browser_opened": opened}
