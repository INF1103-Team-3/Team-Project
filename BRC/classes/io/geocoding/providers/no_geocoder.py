"""No-op geocoder used when coordinate lookup is disabled."""

from BRC.classes.io.geocoding.contracts.geocoder_interface import GeocoderInterface


class NoGeocoder(GeocoderInterface):
    """Return listings unchanged without claiming coordinates were added."""

    adds_coordinates = False

    def geocode(self, listings):
        return list(listings)
