"""Compatibility imports for BRC domain model classes."""

from BRC.classes.data.models.common.address import Address
from BRC.classes.data.models.common.certificate import Certificate
from BRC.classes.data.models.restaurant.checked_restaurant import CheckedRestaurant
from BRC.classes.data.caches.cuisine_cache import CuisineCache
from BRC.classes.data.caches.halal_database import HalalDatabase
from BRC.classes.data.models.muis.halal_outlet import HalalOutlet
from BRC.classes.data.models.common.model_constants import EATING_ESTABLISHMENT, SOURCE_URL
from BRC.classes.data.models.muis.muis_listing import MuisListing
from BRC.classes.data.models.muis.muis_snapshot import MuisSnapshot
from BRC.classes.data.models.restaurant.restaurant_record import RestaurantRecord


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
