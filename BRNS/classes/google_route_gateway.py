"""Google Routes and deterministic travel-estimate IO for BRNS."""

import math

import requests


class GoogleRouteGateway:
    """Own route-matrix, directions, estimate and Maps-link behavior."""

    def __init__(self, config, logger, error_logger):
        self._config = config
        self._log = logger
        self._error_logger = error_logger

    @staticmethod
    def haversine_km(first, second):
        lat1, lng1, lat2, lng2 = map(
            math.radians,
            (first[0], first[1], second[0], second[1]),
        )
        value = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2)
            * math.sin((lng2 - lng1) / 2) ** 2
        )
        return 2 * 6371.0 * math.asin(math.sqrt(value))

    def estimate_travel_minutes(self, origin, restaurant, mode):
        if mode not in {"walk", "drive"}:
            raise ValueError("Transit journey times require a real route.")
        speed = 80 if mode == "walk" else 500
        meters = self.haversine_km(
            origin, (restaurant["lat"], restaurant["lng"])) * 1000 * 1.2
        return max(1, round(meters / speed))

    def travel_times_matrix(
            self, origin, restaurants, mode, traffic_aware=False):
        if not restaurants:
            return
        self._log.debug_log(
            f"Route matrix requested for {len(restaurants)} candidates.",
            "INFO", "BRNS.io_manager.travel_times_matrix")
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._config.GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": (
                "originIndex,destinationIndex,duration,"
                "distanceMeters,status,condition"),
        }
        body = {
            "origins": [{"waypoint": {"location": {"latLng": {
                "latitude": origin[0], "longitude": origin[1],
            }}}}],
            "destinations": [{"waypoint": {"location": {"latLng": {
                "latitude": restaurant["lat"],
                "longitude": restaurant["lng"],
            }}}} for restaurant in restaurants],
            "travelMode": {
                "walk": "WALK", "drive": "DRIVE", "transit": "TRANSIT",
            }[mode],
        }
        if traffic_aware and mode == "drive":
            body["routingPreference"] = "TRAFFIC_AWARE"
        try:
            response = requests.post(
                self._config.MATRIX_URL,
                headers=headers,
                json=body,
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
            elements = (
                data if isinstance(data, list) else data.get("elements", []))
            for element in elements:
                try:
                    index = element["destinationIndex"]
                    if element.get("condition") == "ROUTE_NOT_FOUND":
                        continue
                    status_code = (element.get("status") or {}).get("code", 0)
                    if status_code not in (0, None):
                        continue
                    restaurants[index][f"{mode}_minutes"] = (
                        int(element["duration"].rstrip("s")) / 60)
                    restaurants[index][f"{mode}_meters"] = int(
                        element["distanceMeters"])
                    restaurants[index][f"{mode}_source"] = "route"
                except (KeyError, ValueError, TypeError):
                    continue
        except (
                requests.RequestException, AttributeError,
                KeyError, ValueError) as error:
            self._error_logger(f"routes_matrix_{mode}", error)
        routed = sum(
            restaurant.get(f"{mode}_source") == "route"
            for restaurant in restaurants)
        self._log.debug_log(
            f"Route matrix supplied {routed} routes.", "INFO",
            "BRNS.io_manager.travel_times_matrix")

    def fill_travel_estimates(self, origin, restaurants):
        for restaurant in restaurants:
            for mode in ("walk", "drive"):
                if restaurant.get(f"{mode}_minutes") is None:
                    restaurant[f"{mode}_minutes"] = (
                        self.estimate_travel_minutes(
                            origin, restaurant, mode))
                    restaurant[f"{mode}_meters"] = int(
                        self.haversine_km(
                            origin,
                            (restaurant["lat"], restaurant["lng"]),
                        ) * 1000)
                    restaurant[f"{mode}_source"] = "estimate"

    @staticmethod
    def format_transit_step(step):
        details = step.get("transitDetails") or {}
        if not details:
            return step.get("navigationInstruction", {}).get("instructions")
        line = details.get("transitLine") or {}
        vehicle = (line.get("vehicle") or {}).get("name") or {}
        service = (
            line.get("nameShort") or line.get("name")
            or vehicle.get("text") or "Transit")
        text = f"Take {service}"
        if details.get("headsign"):
            text += f" toward {details['headsign']}"
        stops = details.get("stopDetails") or {}
        departure = (stops.get("departureStop") or {}).get("name")
        arrival = (stops.get("arrivalStop") or {}).get("name")
        if departure:
            text += f" from {departure}"
        if arrival:
            text += f" to {arrival}"
        if details.get("stopCount"):
            text += f" ({details['stopCount']} stops)"
        return text

    def get_route(self, origin, destination, mode, traffic_aware=False):
        self._log.debug_log(
            "Directions request started.", "INFO",
            "BRNS.io_manager.get_route")
        body = {
            "origin": {"location": {"latLng": {
                "latitude": origin[0], "longitude": origin[1],
            }}},
            "destination": {"location": {"latLng": {
                "latitude": destination[0], "longitude": destination[1],
            }}},
            "travelMode": {
                "walk": "WALK", "drive": "DRIVE", "transit": "TRANSIT",
            }[mode],
        }
        if traffic_aware and mode == "drive":
            body["routingPreference"] = "TRAFFIC_AWARE"
        field_mask = (
            "routes.duration,routes.distanceMeters,"
            "routes.legs.steps.navigationInstruction")
        if mode == "transit":
            field_mask += (
                ",routes.legs.steps.travelMode,"
                "routes.legs.steps.transitDetails")
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._config.GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": field_mask,
        }
        try:
            response = requests.post(
                self._config.ROUTES_URL,
                headers=headers,
                json=body,
                timeout=15,
            )
            response.raise_for_status()
            routes = response.json().get("routes", [])
            if not routes:
                self._log.debug_log(
                    "Directions returned no route.", "WARNING",
                    "BRNS.io_manager.get_route")
                return None
            route = routes[0]
            steps = []
            for leg in route.get("legs", []):
                for step in leg.get("steps", []):
                    text = (
                        self.format_transit_step(step)
                        if mode == "transit"
                        else step.get("navigationInstruction", {}).get(
                            "instructions"))
                    if text:
                        steps.append(text)
            self._log.debug_log(
                "Directions route returned.", "INFO",
                "BRNS.io_manager.get_route")
            return {
                "duration_min": round(
                    int(route["duration"].rstrip("s")) / 60),
                "distance_m": route["distanceMeters"],
                "steps": steps,
            }
        except (requests.RequestException, KeyError, ValueError) as error:
            self._error_logger("get_route", error)
            return None

    @staticmethod
    def build_maps_link(origin, destination, mode):
        travelmode = {
            "walk": "walking", "drive": "driving", "transit": "transit",
        }[mode]
        return (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={origin[0]},{origin[1]}"
            f"&destination={destination[0]},{destination[1]}"
            f"&travelmode={travelmode}"
        )
