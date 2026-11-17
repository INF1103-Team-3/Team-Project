"""Own BRC database warm-up, refresh scheduling and non-blocking rebuilds."""

import os
import threading
from pathlib import Path

from BRC.classes.data.data_manager import DataManager
from common import debug_log


class DatabaseRefreshService:
    """Coordinate persisted-data freshness without owning HTTP transport."""

    DEFAULT_REFRESH_CHECK_INTERVAL = 3600.0

    def __init__(
        self,
        handler,
        refresh_interval=None,
        data_factory=DataManager,
        thread_factory=None,
    ):
        self._handler = handler
        self._data_factory = data_factory
        self._thread_factory = thread_factory or threading.Thread
        self._refresh_interval = (
            self._env_refresh_interval()
            if refresh_interval is None
            else float(refresh_interval)
        )
        self._stop_event = threading.Event()
        self._refresh_lock = threading.Lock()

    def stop(self):
        self._stop_event.set()

    def start_warm(self):
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

        self._thread_factory(target=warm, daemon=True).start()

    def start_watcher(self):
        if os.getenv("BRC_AUTO_WARM", "1") == "0":
            return
        if self._refresh_interval <= 0:
            return

        def watch():
            while not self._stop_event.wait(self._refresh_interval):
                self.start_warm()

        self._thread_factory(target=watch, daemon=True).start()

    def _database_state(self):
        path = self._handler.database_path
        if not path.exists():
            return "missing"
        if not isinstance(path, (str, Path)):
            return "fresh"
        return self._data_factory(clean_path=Path(path)).clean_database_state()

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
