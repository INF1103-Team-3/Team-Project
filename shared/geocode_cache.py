"""One durable geocode cache shared by BIS, BRC, and BRNS."""

import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "geocode_cache.json"


def _key(query):
    return query.strip().lower() if isinstance(query, str) else ""


def _point(value):
    if not isinstance(value, list) or len(value) != 2:
        return None
    if any(type(number) not in (int, float) or not math.isfinite(number)
           for number in value):
        return None
    latitude, longitude = value
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _read():
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise RuntimeError("Cannot read the shared geocode cache.") from error
    if not isinstance(data, dict):
        raise RuntimeError("The shared geocode cache must contain a JSON object.")
    return data


def lookup(query):
    """Return validated coordinates, or None when the query is not cached."""
    key = _key(query)
    return _point(_read().get(key)) if key else None


@contextmanager
def _cache_lock(path):
    """Hold one lock file across the read-modify-write on each platform."""
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def remember(queries, latitude, longitude):
    """Atomically save successful lookups under every supplied query."""
    point = _point([latitude, longitude])
    if point is None:
        raise ValueError("Invalid geocode coordinates.")
    keys = {_key(query) for query in queries}
    keys.discard("")
    if not keys:
        return
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = CACHE_FILE.with_suffix(".lock")
    with _cache_lock(lock_path):
        data = _read()
        for key in keys:
            data[key] = list(point)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=CACHE_FILE.parent,
                prefix=".geocode-", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(data, file, indent=2, ensure_ascii=False, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, CACHE_FILE)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
