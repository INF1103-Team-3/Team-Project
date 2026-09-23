"""AI-assisted ingestion requires grounded quotes and a final human review."""

import io
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ai_manager import extract_restaurants, parse_extracted_restaurants
from data_manager import load_restaurants, save_json
from io_manager import extract_catalog
from logic_manager import prepare_extracted_bundle, quoted_price_matches
from support import function_suite

CONFIG = {"api_key": "test-placeholder", "model": "test-model", "timeout": 1}


def excerpt():
    return {
        "source": {"source_id": "fixture-source", "source_reference":
                   "https://example.org/synthetic-test-only", "evidence_type": "official",
                   "collected_at": "2026-09-23", "last_verified_at": "2026-09-23"},
        "text": "Synthetic Cafe, Synthetic Road. Italian.\nPasta SGD 10.00",
    }


def extracted():
    return [{
        "restaurant_id": "synthetic-cafe", "name": "Synthetic Cafe",
        "address": "Synthetic Road", "cuisines": ["italian"], "location": None,
        "opening_hours": None, "source_ids": ["fixture-source"],
        "evidence_quote": "Synthetic Cafe, Synthetic Road. Italian.",
        "menu": [{"name": "Pasta", "price": 10, "currency": "SGD",
                  "food_tags": ["pasta"], "source_ids": ["fixture-source"],
                  "evidence_quote": "Pasta SGD 10.00", "dietary": {}, "allergen_free": {}}],
    }]


def test_valid_extraction_schema_and_grounding():
    content = json.dumps({"restaurants": extracted()})
    records, error = parse_extracted_restaurants(content, "fixture-source")
    assert error is None
    bundle, error = prepare_extracted_bundle(records, excerpt())
    assert error is None and bundle["restaurants"] == extracted()


def test_extra_fields_and_invented_values_are_rejected():
    records = extracted()
    records[0]["rating"] = 5
    assert parse_extracted_restaurants(json.dumps({"restaurants": records}), "fixture-source")[1]
    for field, value in (("name", "Invented Cafe"), ("address", "Invented Road"),
                         ("cuisines", ["japanese"]), ("location", [1.3, 103.8])):
        records = extracted()
        records[0][field] = value
        assert prepare_extracted_bundle(records, excerpt())[1]
    records = extracted()
    records[0]["menu"][0]["price"] = 5
    assert prepare_extracted_bundle(records, excerpt())[1]


def test_unquoted_menu_and_ai_safety_claims_are_rejected():
    records = extracted()
    records[0]["menu"][0]["evidence_quote"] = "Invented quote"
    assert prepare_extracted_bundle(records, excerpt())[1]
    records = extracted()
    records[0]["menu"][0]["dietary"] = {"vegan": {
        "confirmed": True, "evidence_type": "official", "source_ids": ["fixture-source"]}}
    assert prepare_extracted_bundle(records, excerpt())[1]


def test_currency_and_ambiguous_price_quotes_fail_closed():
    assert quoted_price_matches("Pasta S$10.00", 10)
    assert quoted_price_matches("Pasta SGD 10", 10)
    for text in ("Pasta $10", "Pasta US$10", "SGD 10 or SGD 12", "SGD 10.001", "SGD 1,000"):
        assert not quoted_price_matches(text, 10)
    assert quoted_price_matches("Price unavailable", None)


def test_extraction_retries_schema_once_but_not_http_errors():
    valid = json.dumps({"restaurants": extracted()})
    with patch("ai_manager.request_completion", side_effect=[("{}", None), (valid, None)]) as api:
        records, error = extract_restaurants(excerpt(), CONFIG)
        assert error is None and records == extracted()
        assert api.call_count == 2 and api.call_args.kwargs["max_tokens"] == 4000
    with patch("ai_manager.request_completion", return_value=(None, "Unavailable")) as api:
        assert extract_restaurants(excerpt(), CONFIG)[1]
        assert api.call_count == 1


def test_empty_invalid_and_unconfigured_extraction():
    assert prepare_extracted_bundle([], excerpt())[1]
    for value in (None, {}, {"source": {}, "text": "bad"}):
        with patch("ai_manager.request_completion") as api:
            assert extract_restaurants(value, CONFIG)[1]
            assert not api.called
    with patch("ai_manager.request_completion") as api:
        assert extract_restaurants(excerpt(), {})[1]
        assert not api.called


def test_cli_extraction_only_persists_after_review():
    for answer in ("n", "y"):
        with tempfile.TemporaryDirectory() as directory:
            save_json(Path(directory) / "incoming" / "source.json", excerpt())
            config = dict(CONFIG, data_dir=Path(directory))
            with patch("builtins.input", side_effect=["source.json", answer]):
                with patch("ai_manager.request_completion", return_value=(
                        json.dumps({"restaurants": extracted()}), None)):
                    with patch("sys.stdout", new_callable=io.StringIO):
                        extract_catalog(config)
            records, error = load_restaurants(directory)
            assert error is None and len(records) == (1 if answer == "y" else 0)


def test_grounding_failure_never_reaches_import_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        save_json(Path(directory) / "incoming" / "source.json", excerpt())
        records = deepcopy(extracted())
        records[0]["menu"][0]["price"] = 999
        with patch("builtins.input", side_effect=["source.json"]) as inputs:
            with patch("io_manager.extract_restaurants", return_value=(records, None)):
                with patch("sys.stdout", new_callable=io.StringIO):
                    extract_catalog(dict(CONFIG, data_dir=Path(directory)))
        assert inputs.call_count == 1
        assert not (Path(directory) / "catalog_imports.json").exists()


def load_tests(loader, tests, pattern):
    return function_suite(globals())
