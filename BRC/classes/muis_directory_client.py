"""HTTP client for the official MUIS establishment directory."""

import requests
from bs4 import BeautifulSoup

from BRC.classes.model_constants import EATING_ESTABLISHMENT, SOURCE_URL
from BRC.classes.muis_listing import MuisListing


class MuisDirectoryClient:
    """Retrieve validated eating-establishment rows from MUIS."""

    SEARCH_URL = "https://halal.muis.gov.sg/api/halal/establishments"
    MAX_RESULTS = 200
    TIMEOUT = (5, 20)

    def __init__(self, session=None):
        self._session = session or requests.Session()
        self._token = None

    def connect(self):
        response = self._session.get(SOURCE_URL, timeout=self.TIMEOUT)
        response.raise_for_status()
        field = BeautifulSoup(response.text, "html.parser").find(
            "input", attrs={"name": "__RequestVerificationToken"})
        if field is None or not field.get("value"):
            raise ValueError("MUIS portal did not provide a search token.")
        self._token = field["value"]

    def search(self, text):
        response = self._session.post(
            self.SEARCH_URL, json={"text": text},
            headers={
                "Accept": "application/json",
                "X-CSRF-TOKEN": self._token,
            },
            timeout=self.TIMEOUT)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError(
                f"MUIS returned invalid JSON for {text!r}.") from error
        if not isinstance(payload, dict):
            raise ValueError(f"MUIS returned an invalid result for {text!r}.")
        count, rows = payload.get("totalRecords"), payload.get("data")
        if (type(count) is not int or not 0 <= count <= self.MAX_RESULTS
                or not isinstance(rows, list) or len(rows) != count):
            raise ValueError(
                f"MUIS returned an incomplete result for {text!r}.")
        if count == self.MAX_RESULTS:
            return [], True
        listings = [MuisListing.from_api_row(row, text) for row in rows]
        return [item for item in listings if item is not None], False
