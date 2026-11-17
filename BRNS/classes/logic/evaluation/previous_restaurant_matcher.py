"""Match candidate restaurants against previously returned entries."""


class PreviousRestaurantMatcher:
    """Identify seen places by place ID or normalized (name, address)."""

    def __init__(self, previous_restaurants=()):
        self.__place_ids = set()
        self.__name_address_keys = set()
        for item in previous_restaurants or ():
            if not isinstance(item, dict):
                continue
            place_id = item.get("google_place_id")
            if isinstance(place_id, str) and place_id.strip():
                self.__place_ids.add(place_id.strip())
            name = self.__clean_field(item.get("name"))
            if not name:
                continue
            address = self.__clean_field(item.get("address"))
            self.__name_address_keys.add((name, address))

    @staticmethod
    def __clean_field(value):
        if value is None:
            return ""
        return str(value).casefold().strip()

    @property
    def is_empty(self):
        """Return True when no usable place IDs or keys were provided."""
        return not self.__place_ids and not self.__name_address_keys

    def matches(self, restaurant):
        """Return True when restaurant matches a seen ID or name/address."""
        if not isinstance(restaurant, dict):
            return False
        place_id = restaurant.get("google_place_id")
        if isinstance(place_id, str) and place_id.strip() in self.__place_ids:
            return True
        name = self.__clean_field(restaurant.get("name"))
        if not name:
            return False
        address = self.__clean_field(restaurant.get("address"))
        return (name, address) in self.__name_address_keys
