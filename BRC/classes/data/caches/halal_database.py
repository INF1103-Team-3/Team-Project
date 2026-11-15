"""Aggregate of independently usable MUIS halal outlets."""

from BRC.classes.data.models.common.address import Address
from BRC.classes.data.models.common.model_constants import SOURCE_URL


class HalalDatabase:
    """Index and query the cleaned collection of certified outlets."""

    MAX_CANDIDATES = 25

    def __init__(self, outlets, source_url=SOURCE_URL, source_fetched_at=None):
        self._outlets = list(outlets)
        self._source_url = source_url
        self._source_fetched_at = source_fetched_at
        self._by_certificate = {
            outlet.certificate.number: outlet for outlet in self._outlets}

    def __len__(self):
        return len(self._outlets)

    def __iter__(self):
        return iter(self._outlets)

    @property
    def source_url(self):
        return self._source_url

    @property
    def source_fetched_at(self):
        return self._source_fetched_at

    def get(self, certificate_number):
        if not certificate_number:
            return None
        return self._by_certificate.get(certificate_number)

    def filter(self, keep):
        return [outlet for outlet in self._outlets if keep(outlet)]

    def candidates_for(self, record):
        postal = record.address.postal
        candidates = [
            outlet for outlet in self._outlets
            if postal and outlet.postal_code == postal]
        if not candidates:
            name = Address.normalise(record.name)
            candidates = [
                outlet for outlet in self._outlets
                if Address.normalise(outlet.name) == name
                or outlet.address.key == record.address.key]
        return candidates[:self.MAX_CANDIDATES]

    def to_list(self):
        return [outlet.to_dict() for outlet in self._outlets]
