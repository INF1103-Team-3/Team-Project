"""Match candidate restaurants against previously returned entries."""


class PreviousRestaurantMatcher:
    """Identify seen places by place ID or normalized (name, address)."""

    def __init__(self, previous_restaurants=()):
        self._place_ids = set()
        self._name_address_keys = set()
        for item in previous_restaurants or ():
            if not isinstance(item, dict):
                continue
            place_id = item.get("google_place_id")
            if isinstance(place_id, str) and place_id.strip():
                self._place_ids.add(place_id.strip())
            name = self._clean_field(item.get("name"))
            if not name:
                continue
            address = self._clean_field(item.get("address"))
            self._name_address_keys.add((name, address))

    @staticmethod
    def _clean_field(value):
        if value is None:
            return ""
        return str(value).casefold().strip()

    @property
    def is_empty(self):
        """Return True when no usable place IDs or keys were provided."""
        return not self._place_ids and not self._name_address_keys

    def matches(self, restaurant):
        """Return True when restaurant matches a seen ID or name/address."""
        if not isinstance(restaurant, dict):
            return False
        place_id = restaurant.get("google_place_id")
        if isinstance(place_id, str) and place_id.strip() in self._place_ids:
            return True
        name = self._clean_field(restaurant.get("name"))
        if not name:
            return False
        address = self._clean_field(restaurant.get("address"))
        return (name, address) in self._name_address_keys
