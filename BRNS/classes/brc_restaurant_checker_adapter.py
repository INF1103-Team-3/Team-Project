"""Adapter isolating BRNS from the existing BRC module shape."""

from BRNS.classes.restaurant_verification_interface import (
    RestaurantVerificationInterface,
)


class BRCRestaurantCheckerAdapter(RestaurantVerificationInterface):
    """Expose the existing BRC service through a focused BRNS contract."""

    def __init__(self, checker_module):
        self._checker = checker_module

    def database_missing(self):
        return not self._checker.data_manager.CLEAN_DATABASE_PATH.exists()

    def verify(self, restaurant):
        return self._checker.run(restaurant)
