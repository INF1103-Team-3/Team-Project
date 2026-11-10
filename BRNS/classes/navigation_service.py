"""Prepare BRNS route and Maps-link responses."""


class NavigationService:
    """Coordinate route IO for one selected restaurant."""

    def __init__(self, io_manager, logger):
        self._io = io_manager
        self._log = logger

    def route_to(self, restaurant, request):
        self._log.debug_log(
            "Route requested.", "INFO", "BRNS.main.route_to")
        origin = (
            request["origin"]["latitude"],
            request["origin"]["longitude"],
        )
        latitude, longitude = restaurant.get("lat"), restaurant.get("lng")
        if latitude is None or longitude is None:
            raise ValueError(
                "No verified coordinates are available for that restaurant.")
        destination = (latitude, longitude)
        mode = request["mode"]
        result = {
            "name": restaurant["name"],
            "route": self._io.get_route(
                origin, destination, mode,
                request.get("traffic_aware", False),
            ),
            "link": self._io.build_maps_link(origin, destination, mode),
            "mode": mode,
            "traffic_aware": request.get("traffic_aware", False),
        }
        self._log.debug_log(
            "Route response prepared with directions."
            if result["route"]
            else "Route response prepared with map link.",
            "INFO", "BRNS.main.route_to",
        )
        return result
