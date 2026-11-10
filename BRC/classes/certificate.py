"""MUIS certificate value object."""

from datetime import date, datetime


class Certificate:
    """Expose the stable fields and active status of one MUIS certificate."""

    FIELDS = (
        "certificate_number", "listing_id", "scheme", "category",
        "valid_until", "source_url", "raw_fetched_at")
    DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")

    def __init__(self, data):
        self._data = {field: data.get(field) for field in self.FIELDS}

    @property
    def number(self):
        return self._data["certificate_number"]

    @property
    def listing_id(self):
        return self._data["listing_id"]

    @property
    def valid_until(self):
        return self._data["valid_until"]

    @property
    def source_url(self):
        return self._data["source_url"]

    def is_active(self, today=None):
        if not self.valid_until:
            return True
        for date_format in self.DATE_FORMATS:
            try:
                expiry = datetime.strptime(
                    str(self.valid_until)[:10], date_format).date()
            except ValueError:
                continue
            return expiry >= (today or date.today())
        return False

    def to_dict(self):
        return dict(self._data)
