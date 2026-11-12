"""Adapter isolating BRNS from the existing BRC module shape."""

from BRNS.classes.restaurant_verification_interface import (
    RestaurantVerificationInterface,
)


class BRCRestaurantCheckerAdapter(RestaurantVerificationInterface):
    """Expose the existing BRC service through a focused BRNS contract."""

    def __init__(self, checker_module):
        self._checker = checker_module

    def database_missing(self):
        if hasattr(self._checker, "database_missing"):
            return self._checker.database_missing()
        return not self._checker.data_manager.CLEAN_DATABASE_PATH.exists()

    def verify(self, restaurant):
        if hasattr(self._checker, "verify"):
            return self._checker.verify(restaurant)
        return self._checker.run(restaurant)

    def supports_batch(self):
        return hasattr(self._checker, "verify_batch")

    def verify_batch(self, restaurants):
        if hasattr(self._checker, "verify_batch"):
            return self._checker.verify_batch(restaurants)
        return [self.verify(restaurant) for restaurant in restaurants]
