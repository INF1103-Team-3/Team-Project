"""Singapore address value object."""

import re
from difflib import SequenceMatcher


class Address:
    """Normalize a Singapore address and expose postal/unit identities."""

    UNIT_PATTERN = re.compile(
        r"(?:#\s*|\b)((?:B\d{1,2}|\d{2})[-/]\d{2,3}(?:/\d{2,3})?[A-Z]?)\b",
        re.I)

    def __init__(self, text, postal_code=""):
        self._text = text
        self._postal_code = postal_code

    @property
    def text(self):
        return self._text

    @property
    def postal_code(self):
        return self._postal_code

    @staticmethod
    def normalise(text):
        return " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))

    @property
    def postal(self):
        if re.fullmatch(r"\d{6}", self._postal_code):
            return self._postal_code
        found = re.findall(r"\b\d{6}\b", self._text)
        return found[-1] if found else None

    @property
    def unit(self):
        match = self.UNIT_PATTERN.search(self._text)
        if match is None:
            return None
        return re.sub(r"[^A-Z0-9]", "", match.group(1).upper())

    @property
    def key(self):
        return self.normalise(self._text)

    @property
    def street_key(self):
        street = self.UNIT_PATTERN.sub(" ", self._text)
        street = re.sub(
            r"\b(?:singapore|\d{6})\b", " ", street, flags=re.I)
        return self.normalise(street)

    def street_similarity(self, other):
        return SequenceMatcher(
            None, self.street_key, other.street_key).ratio()
