"""Compatibility imports for BRC domain model classes."""

from BRC.classes.address import Address
from BRC.classes.certificate import Certificate
from BRC.classes.checked_restaurant import CheckedRestaurant
from BRC.classes.cuisine_cache import CuisineCache
from BRC.classes.halal_database import HalalDatabase
from BRC.classes.halal_outlet import HalalOutlet
from BRC.classes.model_constants import EATING_ESTABLISHMENT, SOURCE_URL
from BRC.classes.muis_listing import MuisListing
from BRC.classes.muis_snapshot import MuisSnapshot
from BRC.classes.restaurant_record import RestaurantRecord


__all__ = [
    "Address",
    "Certificate",
    "CheckedRestaurant",
    "CuisineCache",
    "EATING_ESTABLISHMENT",
    "HalalDatabase",
    "HalalOutlet",
    "MuisListing",
    "MuisSnapshot",
    "RestaurantRecord",
    "SOURCE_URL",
]
