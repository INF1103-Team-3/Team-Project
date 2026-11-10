"""Restaurant input record sent to BRC."""

from BRC.classes.address import Address


class RestaurantRecord:
    """Preserve caller fields while exposing normalized outlet identity."""

    def __init__(self, data):
        self._data = dict(data)
        self._address = Address(
            str(data.get("address")), str(data.get("postal_code") or ""))

    @property
    def name(self):
        return self._data["name"]

    @property
    def address(self):
        return self._address

    def to_dict(self):
        return dict(self._data)
