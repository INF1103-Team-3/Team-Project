import io
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from ai_manager import interpret_request, parse_interpretation, request_completion
from support import function_suite, request

CONFIG = {"api_key": "test-placeholder", "model": "test-model", "timeout": 1}


def test_valid_json_and_missing_fields():
    assert parse_interpretation(json.dumps(request()))[1] is None
    for bad in ("not json", "{}", "[]", "null", '{"budget_max": 10}'):
        assert parse_interpretation(bad)[1]


def test_missing_config_never_calls_network():
    with patch("ai_manager.urlopen") as network:
        assert interpret_request("rice", {})[1]
        assert not network.called


def test_http_response_extraction():
    payload = {"choices": [{"message": {"content": json.dumps(request())}}]}
    with patch("ai_manager.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as network:
        content, error = request_completion([], CONFIG)
        assert error is None and json.loads(content) == request()
        assert network.call_args.kwargs["timeout"] == 1
        body = json.loads(network.call_args.args[0].data)
        assert body["response_format"] == {"type": "json_object"}


def test_network_and_http_errors_are_sanitized():
    for failure in (URLError("private upstream data"), TimeoutError(),
                    HTTPError("url", 401, "private upstream data", {}, None)):
        with patch("ai_manager.urlopen", side_effect=failure):
            result, error = request_completion([], CONFIG)
            assert result is None and error
            assert "private upstream data" not in error


def test_malformed_envelopes_and_size_limit():
    for payload in ({}, [], {"choices": []}, {"choices": [{"message": {"content": ""}}]}):
        with patch("ai_manager.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            assert request_completion([], CONFIG)[1]
    with patch("ai_manager.urlopen", return_value=io.BytesIO(b"x" * 100001)):
        assert request_completion([], CONFIG)[1]


def test_malformed_interpretation_retried_once():
    with patch("ai_manager.request_completion", side_effect=[("{}", None),
               (json.dumps(request(cuisines=["Japanese"])), None)]) as network:
        result, error = interpret_request("Japanese food", CONFIG)
        assert error is None and result["cuisines"] == ["japanese"]
        assert network.call_count == 2
    with patch("ai_manager.request_completion", return_value=("{}", None)) as network:
        assert interpret_request("rice", CONFIG)[1]
        assert network.call_count == 2


def load_tests(loader, tests, pattern):
    return function_suite(globals())
