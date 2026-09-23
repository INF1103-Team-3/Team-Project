import io
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from routing_service import cache_key, fetch_walking_route, resolve_routes
from support import function_suite, restaurant

CONFIG = {"routing_key": "test-placeholder", "timeout": 1}
ORIGIN = [1.301, 103.801]
DESTINATION = [1.3, 103.8]
ROUTE = {"minutes": 5, "distance_m": 400, "provider": "openrouteservice"}


def test_walking_profile_coordinate_order_and_units():
    body = {"routes": [{"summary": {"duration": 300, "distance": 400}}]}
    with patch("routing_service.urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as call:
        route, error = fetch_walking_route(ORIGIN, DESTINATION, CONFIG)
        assert error is None and route == ROUTE
        sent = call.call_args.args[0]
        assert "/foot-walking/json" in sent.full_url
        assert json.loads(sent.data)["coordinates"] == [[103.801, 1.301], [103.8, 1.3]]
        assert call.call_args.kwargs["timeout"] == 1


def test_missing_key_or_coordinates_does_not_send_request():
    with patch("routing_service.urlopen") as call:
        assert fetch_walking_route(ORIGIN, DESTINATION, {})[1]
        assert fetch_walking_route(None, DESTINATION, CONFIG)[1]
        assert not call.called


def test_bad_routes_and_failures_are_unknown():
    for payload in ({}, {"routes": []}, {"routes": [{"summary": {"duration": -1, "distance": 4}}]},
                    {"routes": [{"summary": {"duration": True, "distance": 4}}]}):
        with patch("routing_service.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            assert fetch_walking_route(ORIGIN, DESTINATION, CONFIG)[0] is None
    for failure in (URLError("private data"), TimeoutError(), HTTPError("url", 429, "private data", {}, None)):
        with patch("routing_service.urlopen", side_effect=failure):
            route, error = fetch_walking_route(ORIGIN, DESTINATION, CONFIG)
            assert route is None and "private data" not in error


def test_cache_reused_and_destination_change_invalidates():
    record = restaurant()
    with patch("routing_service.fetch_walking_route", return_value=(ROUTE, None)) as call:
        routes, cache, warnings = resolve_routes(ORIGIN, [record], CONFIG, {}, now=1000)
        assert not warnings and len(routes) == 1 and call.call_count == 1
        resolve_routes(ORIGIN, [record], CONFIG, cache, now=1100)
        assert call.call_count == 1
        record["location"] = [1.31, 103.81]
        resolve_routes(ORIGIN, [record], CONFIG, cache, now=1100)
        assert call.call_count == 2


def test_expired_future_and_malformed_cache_entries_never_pass():
    key = cache_key(ORIGIN, DESTINATION)
    for entry in ({"stored_at": 0, "route": ROUTE}, {"stored_at": 99999, "route": ROUTE},
                  {"stored_at": 4999, "route": {"minutes": -1}}, "bad"):
        routes, cache, warnings = resolve_routes(ORIGIN, [restaurant()], {}, {key: entry}, now=5000)
        assert not routes and not cache and warnings


def test_route_failures_not_cached_and_request_limit():
    records = []
    for index in range(12):
        record = restaurant(str(index))
        record["location"] = [1.3 + index / 1000, 103.8]
        records.append(record)
    with patch("routing_service.fetch_walking_route", return_value=(None, "Unavailable")) as call:
        routes, cache, warnings = resolve_routes(ORIGIN, records, CONFIG, {}, now=1000)
        assert not routes and not cache and warnings and call.call_count == 10


def load_tests(loader, tests, pattern):
    return function_suite(globals())


def test_interrupted_http_read_is_reported():
    from http.client import IncompleteRead
    with patch("routing_service.urlopen", side_effect=IncompleteRead(b"partial")):
        result, error = fetch_walking_route(ORIGIN, DESTINATION, CONFIG)
        assert result is None and error
