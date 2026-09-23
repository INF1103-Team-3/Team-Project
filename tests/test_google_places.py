"""Google discovery uses mocked responses and persists only place IDs."""

import io
import json
import os
import tempfile
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from config import load_config
from data_manager import load_google_place_ids, save_google_place_ids
from google_places_service import (
    get_place_details, parse_google_place, search_nearby_restaurants,
)
from io_manager import discover_google, display_google_places, run_cli
from support import function_suite

CONFIG = {"google_maps_key": "test-placeholder", "timeout": 1}
ORIGIN = [1.3, 103.8]


def raw_place(identifier="test-place-a"):
    return {
        "id": identifier, "displayName": {"text": "Synthetic Google test restaurant"},
        "formattedAddress": "Synthetic test address",
        "location": {"latitude": 1.31, "longitude": 103.81},
        "googleMapsUri": "https://maps.google.com/",
        "primaryType": "restaurant", "businessStatus": "OPERATIONAL",
        "attributions": [{"provider": "Synthetic data provider",
                          "providerUri": "https://example.org/provider"}],
    }


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


def test_nearby_request_uses_mask_header_and_single_call():
    with patch("google_places_service.urlopen", return_value=response({"places": [raw_place()]})) as api:
        places, error = search_nearby_restaurants(ORIGIN, 1000, 20, CONFIG)
    assert error is None and len(places) == 1 and api.call_count == 1
    sent = api.call_args.args[0]
    body = json.loads(sent.data)
    assert sent.get_method() == "POST" and sent.full_url.endswith(":searchNearby")
    assert body["includedTypes"] == ["restaurant"]
    assert body["rankPreference"] == "DISTANCE" and body["maxResultCount"] == 20
    assert body["locationRestriction"]["circle"]["center"] == {
        "latitude": 1.3, "longitude": 103.8}
    headers = {key.lower(): value for key, value in sent.header_items()}
    assert headers["x-goog-api-key"] == "test-placeholder"
    assert "*" not in headers["x-goog-fieldmask"]
    assert "places.attributions" in headers["x-goog-fieldmask"]
    assert "test-placeholder" not in sent.full_url
    assert api.call_args.kwargs["timeout"] == 1


def test_invalid_inputs_and_missing_key_make_no_requests():
    with patch("google_places_service.urlopen") as api:
        for origin, radius, limit in (([91, 0], 1000, 20), (ORIGIN, 0, 20),
                                     (ORIGIN, 50001, 20), (ORIGIN, float("nan"), 20),
                                     (ORIGIN, 1000, True), (ORIGIN, 1000, 21)):
            assert search_nearby_restaurants(origin, radius, limit, CONFIG)[1]
        assert search_nearby_restaurants(ORIGIN, 1000, 20, {})[1]
        assert get_place_details("../../invalid", CONFIG)[1]
        assert not api.called


def test_empty_duplicate_and_malformed_responses():
    with patch("google_places_service.urlopen", return_value=response({})):
        assert search_nearby_restaurants(ORIGIN, 1000, 20, CONFIG) == ([], None)
    with patch("google_places_service.urlopen", return_value=response({"places": [raw_place(), raw_place()]})):
        assert len(search_nearby_restaurants(ORIGIN, 1000, 20, CONFIG)[0]) == 1
    for payload in ({"places": None}, {"places": [None]}, [], {"error": {"message": "private"}}):
        with patch("google_places_service.urlopen", return_value=response(payload)):
            places, error = search_nearby_restaurants(ORIGIN, 1000, 20, CONFIG)
            assert not places and error and "private" not in error


def test_http_failures_are_sanitized_and_not_retried():
    failures = [URLError("private upstream text"), TimeoutError(), IncompleteRead(b"private")]
    failures += [HTTPError("url", status, "private upstream text", {}, None)
                 for status in (400, 403, 429, 500)]
    for failure in failures:
        with patch("google_places_service.urlopen", side_effect=failure) as api:
            places, error = search_nearby_restaurants(ORIGIN, 1000, 20, CONFIG)
        assert not places and error and "private" not in error and api.call_count == 1


def test_response_size_is_bounded():
    with patch("google_places_service.urlopen", return_value=io.BytesIO(b"x" * 1_000_001)):
        assert search_nearby_restaurants(ORIGIN, 1000, 20, CONFIG)[1]


def test_detail_request_extracts_optional_fields():
    raw = raw_place()
    raw.update(websiteUri="https://example.org/menu", priceLevel="PRICE_LEVEL_MODERATE",
               currentOpeningHours={"openNow": False},
               regularOpeningHours={"weekdayDescriptions": ["Monday: 10:00 AM – 9:00 PM"]})
    with patch("google_places_service.urlopen", return_value=response(raw)) as api:
        place, error = get_place_details("test-place-a", CONFIG)
    assert error is None and place["open_now"] is False
    assert place["website"] == "https://example.org/menu" and len(place["opening_hours"]) == 1
    assert api.call_args.args[0].get_method() == "GET"
    assert "menu" not in place and "allergen_free" not in place
    with patch("google_places_service.urlopen", return_value=response(raw_place("other"))):
        assert get_place_details("test-place-a", CONFIG)[1]


def test_unknown_and_untrusted_optional_fields_are_not_invented():
    place = parse_google_place({"id": "test-minimal"})
    assert place["name"] is None and place["location"] is None and place["open_now"] is None
    raw = raw_place()
    raw.update(websiteUri="javascript:invalid", displayName={"text": "bad\x1b[2J"},
               currentOpeningHours={"openNow": "true"})
    place = parse_google_place(raw)
    assert place["website"] is None and place["name"] is None and place["open_now"] is None


def test_google_and_third_party_attribution_displayed():
    with patch("sys.stdout", new_callable=io.StringIO) as output:
        display_google_places([parse_google_place(raw_place())])
    rendered = output.getvalue()
    assert "Google Maps" in rendered and "Synthetic data provider" in rendered
    assert "https://example.org/provider" in rendered
    assert "have not been verified" in rendered


def test_ids_are_deduplicated_and_corruption_preserved():
    with tempfile.TemporaryDirectory() as directory:
        assert save_google_place_ids(directory, ["test-a", "test-b"]) is None
        assert save_google_place_ids(directory, ["test-a", "test-c"]) is None
        assert load_google_place_ids(directory) == (["test-a", "test-b", "test-c"], None)
        path = Path(directory) / "google_place_ids.json"
        path.write_text("broken")
        assert save_google_place_ids(directory, ["test-d"])
        assert path.read_text() == "broken"


def test_discovery_persists_no_google_content_or_key():
    with tempfile.TemporaryDirectory() as directory:
        config = dict(CONFIG, data_dir=Path(directory))
        with patch("google_places_service.urlopen", return_value=response({"places": [raw_place()]})):
            with patch("sys.stdout", new_callable=io.StringIO):
                places, status = discover_google(config, ORIGIN, 1000, 20)
        assert status == 0 and places
        files = list(Path(directory).iterdir())
        assert [file.name for file in files] == ["google_place_ids.json"]
        assert json.loads(files[0].read_text()) == ["test-place-a"]
        assert "Synthetic" not in files[0].read_text() and "test-placeholder" not in files[0].read_text()


def test_noninteractive_command_and_exit_status():
    with tempfile.TemporaryDirectory() as directory:
        config = dict(CONFIG, data_dir=Path(directory))
        with patch("google_places_service.urlopen", return_value=response({"places": [raw_place()]})) as api:
            with patch("sys.stdout", new_callable=io.StringIO):
                status = run_cli(config, ["--discover-google", "1.3", "103.8", "--limit", "5"])
        assert status == 0 and api.call_count == 1
        with patch("sys.stdout", new_callable=io.StringIO):
            assert run_cli(config, ["--discover-google", "91", "0"]) == 1


def test_menu_nearby_and_saved_lookup_are_bounded():
    with tempfile.TemporaryDirectory() as directory:
        config = dict(CONFIG, data_dir=Path(directory))
        answers = ["alex", "g", "n", "1.3,103.8", "", "b", "g", "s", "1", "q"]
        responses = [response({"places": [raw_place()]}), response(raw_place())]
        with patch("builtins.input", side_effect=answers):
            with patch("google_places_service.urlopen", side_effect=responses) as api:
                with patch("sys.stdout", new_callable=io.StringIO):
                    run_cli(config)
        assert api.call_count == 2
        assert load_google_place_ids(directory)[0] == ["test-place-a"]
        assert not (Path(directory) / "interactions.json").exists()


def test_google_key_configuration_from_environment():
    with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "test-placeholder"}, clear=True):
        assert load_config()["google_maps_key"] == "test-placeholder"


def load_tests(loader, tests, pattern):
    return function_suite(globals())
