"""Dependency-free function tests wrapped by the standard unittest runner."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import load_config
from data_manager import append_interaction, load_json, save_json
from debug import debug_log


def test_missing_and_corrupt_files():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "interactions.json"
        assert load_json(path) == ([], None)
        path.write_text("broken")
        assert load_json(path)[1]
        assert append_interaction(directory, {"action": "search"})
        assert path.read_text() == "broken"


def test_atomic_roundtrip_and_invalid_write():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "records.json"
        assert save_json(path, [{"name": "Food"}]) is None
        assert load_json(path) == ([{"name": "Food"}], None)
        assert save_json(path, float("nan"))
        assert load_json(path)[0] == [{"name": "Food"}]
        assert save_json(Path(directory), [])


def test_history_persists_across_reads():
    with tempfile.TemporaryDirectory() as directory:
        for index in range(2):
            assert append_interaction(directory, {"id": index}) is None
        records, error = load_json(Path(directory) / "interactions.json")
        assert error is None and len(records) == 2


def test_log_rejects_uncontrolled_content():
    with tempfile.TemporaryDirectory() as directory:
        with patch.dict(os.environ, {"BITEFINDER_LOG_DIR": directory}):
            assert debug_log("config_loaded", count=2)
            assert not debug_log("uncontrolled text")
            path = Path(directory) / "bitefinder_debug.log"
            records = path.read_text().splitlines()
            assert len(records) == 1
            assert json.loads(records[0])["count"] == 2


def test_configuration_without_credentials():
    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
        assert config["api_key"] == ""
        assert config["model"] == ""
        assert config["timeout"] > 0


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(
        unittest.FunctionTestCase(function)
        for name, function in globals().items() if name.startswith("test_")
    )
