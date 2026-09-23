import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from data_manager import load_json, load_restaurants, save_json
from io_manager import ask_location, ask_number, run_cli
from support import function_suite, request, restaurant


def seed(directory):
    save_json(Path(directory) / "restaurants.json", [restaurant("a"), restaurant("b")])
    save_json(Path(directory) / "sources.json", [{"source_id": "test-source",
              "source_reference": "https://example.org/synthetic-test-only"}])


def test_ai_to_recommendations_to_selection_persistence():
    with tempfile.TemporaryDirectory() as directory:
        seed(directory)
        config = {"data_dir": Path(directory), "api_key": "test-placeholder",
                  "model": "test-model", "timeout": 1}
        answers = ["test-profile", "a", "Japanese food under $15", "y", "1", "q"]
        with patch("builtins.input", side_effect=answers), patch("sys.stdout", new_callable=io.StringIO) as output:
            with patch("ai_manager.request_completion", return_value=(json.dumps(request(
                    cuisines=["japanese"], budget_max=15)), None)):
                run_cli(config)
        assert "Synthetic test restaurant" in output.getvalue()
        records, error = load_json(Path(directory) / "interactions.json")
        assert error is None
        assert [r["action"] for r in records] == ["search", "selected"]
        assert records[0]["recommendations"] == ["a", "b"]
        users, _ = load_json(Path(directory) / "users.json", dict)
        assert users["test-profile"]["cuisine_counts"]["japanese"] == 1


def test_rejected_interpretation_never_searches_or_saves():
    with tempfile.TemporaryDirectory() as directory:
        config = {"data_dir": Path(directory)}
        with patch("builtins.input", side_effect=["test", "a", "rice", "n", "q"]):
            with patch("io_manager.interpret_request", return_value=(request(), None)):
                with patch("sys.stdout", new_callable=io.StringIO):
                    run_cli(config)
        assert not (Path(directory) / "interactions.json").exists()


def test_invalid_input_reprompts_and_eof_exits():
    with patch("builtins.input", side_effect=["nan", "-2", "10"]), patch("sys.stdout", new_callable=io.StringIO):
        assert ask_number("number: ") == 10
    with patch("builtins.input", side_effect=["100,0", "1.3,103.8"]), patch("sys.stdout", new_callable=io.StringIO):
        assert ask_location() == [1.3, 103.8]
    with patch("builtins.input", side_effect=EOFError), patch("sys.stdout", new_callable=io.StringIO) as output:
        run_cli({})
        assert "closed" in output.getvalue()


def test_invalid_restaurants_and_duplicates_reported():
    with tempfile.TemporaryDirectory() as directory:
        seed(directory)
        save_json(Path(directory) / "restaurants.json", [restaurant(), restaurant(), None])
        records, warning = load_restaurants(directory)
        assert len(records) == 1
        assert "2 invalid or duplicate" in warning


def load_tests(loader, tests, pattern):
    return function_suite(globals())


def test_corrupt_profile_fields_fail_gracefully():
    from data_manager import load_profile
    with tempfile.TemporaryDirectory() as directory:
        save_json(Path(directory) / "users.json", {"bad": {"cuisine_counts": {"rice": "high"}}})
        assert load_profile(directory, "bad")[1]


def test_manual_search_runs_against_sourced_starter_data():
    from config import ROOT
    with tempfile.TemporaryDirectory() as directory:
        for filename in ("restaurants.json", "sources.json"):
            (Path(directory) / filename).write_bytes((ROOT / "data" / filename).read_bytes())
        answers = ["manual-test", "m", "", "10", "", "", "", "italian", "pasta", "", "n", "", "y", "s", "q"]
        with patch("builtins.input", side_effect=answers), patch("sys.stdout", new_callable=io.StringIO) as output:
            run_cli({"data_dir": Path(directory)})
        assert output.getvalue().count("Saizeriya —") == 3
        history, error = load_json(Path(directory) / "interactions.json")
        assert error is None and len(history[0]["recommendations"]) == 3
