"""Catalog imports are complete, reviewed additions; existing records survive failures."""

import io
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from data_manager import (
    load_restaurants, prepare_import, read_import_file, save_import, save_json,
)
from io_manager import import_catalog
from support import function_suite, restaurant


def bundle():
    return {
        "sources": [{"source_id": "test-source", "source_reference":
                     "https://example.org/synthetic-test-only", "evidence_type": "official",
                     "collected_at": "2026-09-23", "last_verified_at": "2026-09-23"}],
        "restaurants": [restaurant()],
    }


def incoming(directory, value):
    path = Path(directory) / "incoming" / "test.json"
    assert save_json(path, value) is None
    return path


def test_import_roundtrip_makes_new_records_searchable():
    with tempfile.TemporaryDirectory() as directory:
        incoming(directory, bundle())
        value, error = read_import_file(directory, "test.json")
        assert error is None
        assert save_import(directory, value) is None
        records, error = load_restaurants(directory)
        assert error is None and len(records) == 1
        assert records[0]["restaurant_id"] == "fixture-a"
        assert not (Path(directory) / "restaurants.json").exists()
        assert save_import(directory, value)
        assert len(load_restaurants(directory)[0]) == 1


def test_duplicate_id_and_matching_name_address_rejected():
    with tempfile.TemporaryDirectory() as directory:
        first = bundle()
        assert save_import(directory, first) is None
        duplicate = deepcopy(first)
        duplicate["restaurants"][0]["restaurant_id"] = "other-id"
        duplicate["restaurants"][0]["name"] = "  SYNTHETIC  test restaurant "
        assert prepare_import(directory, duplicate)[1]
        assert len(load_restaurants(directory)[0]) == 1


def test_bad_records_or_source_evidence_reject_whole_bundle():
    with tempfile.TemporaryDirectory() as directory:
        value = bundle()
        value["restaurants"].append(None)
        assert save_import(directory, value)
        assert not (Path(directory) / "catalog_imports.json").exists()
        value = bundle()
        value["sources"][0]["evidence_type"] = "third_party"
        assert save_import(directory, value)
        value = bundle()
        value["sources"][0]["last_verified_at"] = "unknown"
        assert save_import(directory, value)


def test_source_id_conflicts_and_duplicates_within_bundle():
    with tempfile.TemporaryDirectory() as directory:
        assert save_import(directory, bundle()) is None
        value = bundle()
        value["sources"][0]["source_reference"] = "https://example.org/changed"
        assert prepare_import(directory, value)[1]
    with tempfile.TemporaryDirectory() as directory:
        value = bundle()
        value["restaurants"].append(deepcopy(value["restaurants"][0]))
        assert save_import(directory, value)


def test_path_traversal_symlinks_and_oversized_input_rejected():
    with tempfile.TemporaryDirectory() as directory:
        incoming(directory, bundle())
        assert read_import_file(directory, "../test.json")[1]
        assert read_import_file(directory, "/absolute.json")[1]
        target = Path(directory) / "outside.json"
        save_json(target, bundle())
        link = Path(directory) / "incoming" / "link.json"
        link.symlink_to(target)
        assert read_import_file(directory, "link.json")[1]
        large = Path(directory) / "incoming" / "large.json"
        large.write_bytes(b" " * 1_000_001)
        assert read_import_file(directory, "large.json")[1]


def test_failed_save_and_corruption_preserve_existing_catalog():
    with tempfile.TemporaryDirectory() as directory:
        assert save_import(directory, bundle()) is None
        path = Path(directory) / "catalog_imports.json"
        before = path.read_bytes()
        value = bundle()
        value["restaurants"][0].update(restaurant_id="second", name="Other test restaurant")
        with patch("data_manager.save_json", return_value="Write failed"):
            assert save_import(directory, value)
        assert path.read_bytes() == before
        path.write_text("broken")
        assert save_import(directory, value)
        assert path.read_text() == "broken"


def test_cli_import_cancel_and_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        incoming(directory, bundle())
        config = {"data_dir": Path(directory)}
        with patch("builtins.input", side_effect=["test.json", "n"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                import_catalog(config)
        assert not (Path(directory) / "catalog_imports.json").exists()
        with patch("builtins.input", side_effect=["test.json", "y"]):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                import_catalog(config)
        assert "Imported 1" in output.getvalue()
        assert len(load_restaurants(directory)[0]) == 1


def load_tests(loader, tests, pattern):
    return function_suite(globals())


def test_tampered_import_conflicts_are_reported_on_load():
    with tempfile.TemporaryDirectory() as directory:
        save_json(Path(directory) / "restaurants.json", [restaurant()])
        save_json(Path(directory) / "sources.json", bundle()["sources"])
        save_json(Path(directory) / "catalog_imports.json", [bundle()])
        records, error = load_restaurants(directory)
        assert not records and "conflicts" in error


def test_non_scalar_evidence_types_are_validation_errors():
    from schemas import validate_bundle
    for invalid in ([], {}, True, None):
        value = bundle()
        value["sources"][0]["evidence_type"] = invalid
        assert validate_bundle(value)
        value = bundle()
        value["restaurants"][0]["menu"][0]["dietary"]["halal"]["evidence_type"] = invalid
        assert validate_bundle(value)
