"""Complete postal-prefix crawler for the capped MUIS API."""

import time

from BRC.classes.data_unavailable_error import DataUnavailableError
from BRC.classes.model_constants import SOURCE_URL
from BRC.classes.muis_listing import MuisListing


class PostalPrefixCrawler:
    """Split capped searches and checkpoint complete MUIS crawl progress."""

    def __init__(self, directory, progress_file, delay=0.1, progress=None):
        self._directory = directory
        self._progress_file = progress_file
        self._delay = delay
        self._progress = progress

    def crawl(self):
        state = self._load_state()
        pending = state["pending_prefixes"]
        done = state["completed_prefixes"]
        found = state["listings"]
        since_save = 0
        while pending:
            prefix = pending.pop(0)
            self._report(
                len(done), len(done) + len(pending) + 1,
                f"Searching postal prefix {prefix}")
            rows, capped = self._directory.search(prefix)
            if capped:
                if len(prefix) >= 6:
                    raise ValueError(
                        "MUIS results for postal prefix "
                        f"{prefix!r} remain capped.")
                pending[0:0] = [prefix + digit for digit in "0123456789"]
            else:
                done.append(prefix)
                for number, row in enumerate(rows, 1):
                    if row.postal_code.startswith(prefix):
                        found[row.crawl_identity] = row.to_dict(geocoded=False)
                        self._report(
                            len(done), len(done) + len(pending),
                            f"{row.name} ({number}/{len(rows)} in {prefix})")
            since_save += 1
            if since_save >= 10 or not pending:
                self._progress_file.write(state)
                since_save = 0
            if self._delay and pending:
                time.sleep(self._delay)
        self._report(1, 1, f"Retrieved {len(found)} restaurant outlets")
        return [
            MuisListing.from_dict(row) for row in found.values()], done

    def clear(self):
        self._progress_file.delete()

    def _report(self, current, total, detail):
        if self._progress:
            self._progress("retrieve", current, total, detail)

    def _load_state(self):
        fresh = {
            "source_url": SOURCE_URL,
            "pending_prefixes": list("0123456789"),
            "completed_prefixes": [],
            "listings": {},
        }
        if not self._progress_file.exists():
            return fresh
        try:
            saved = self._progress_file.read()
        except DataUnavailableError:
            return fresh
        usable = (
            isinstance(saved, dict)
            and saved.get("source_url") == SOURCE_URL
            and isinstance(saved.get("pending_prefixes"), list)
            and isinstance(saved.get("completed_prefixes"), list)
            and isinstance(saved.get("listings"), dict))
        return saved if usable else fresh
