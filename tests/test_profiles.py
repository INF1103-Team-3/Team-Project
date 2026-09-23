"""Profile changes must be deliberate, persisted and isolated per local user."""

import io
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from data_manager import load_history, load_profile, save_json, save_profile
from io_manager import edit_profile, run_cli
from logic_manager import prepare_request
from support import function_suite, request


def test_editor_clears_safety_only_after_confirmation():
    with tempfile.TemporaryDirectory() as directory:
        profile = {"allergies": ["peanuts"], "cuisine_counts": {"italian": 3}}
        with patch("builtins.input", side_effect=["e", "", "vegan", "Italian", "pasta", "y"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                edit_profile({"data_dir": Path(directory)}, "alex", profile)
        stored, error = load_profile(directory, "alex")
        assert error is None and stored == profile
        assert stored["allergies"] == []
        assert stored["dietary_requirements"] == ["vegan"]
        assert stored["preferred_cuisines"] == ["italian"]
        assert stored["cuisine_counts"] == {"italian": 3}


def test_cancel_and_failed_save_preserve_active_profile():
    for confirm, failure in (("n", None), ("y", "Write failed")):
        profile = {"allergies": ["peanuts"]}
        original = deepcopy(profile)
        answers = ["e", "", "", "", "", confirm]
        with patch("builtins.input", side_effect=answers):
            with patch("io_manager.save_profile", return_value=failure) as save:
                with patch("sys.stdout", new_callable=io.StringIO):
                    edit_profile({"data_dir": Path("unused")}, "alex", profile)
        assert profile == original
        assert save.call_count == (1 if confirm == "y" else 0)


def test_reset_keeps_explicit_preferences_and_safety():
    with tempfile.TemporaryDirectory() as directory:
        profile = {"allergies": ["soy"], "preferred_foods": ["rice"],
                   "cuisine_counts": {"italian": 3}, "selected_ids": ["a"]}
        with patch("builtins.input", side_effect=["r", "y"]):
            with patch("sys.stdout", new_callable=io.StringIO):
                edit_profile({"data_dir": Path(directory)}, "alex", profile)
        assert profile["allergies"] == ["soy"]
        assert profile["preferred_foods"] == ["rice"]
        assert profile["cuisine_counts"] == {} and profile["selected_ids"] == []


def test_search_overrides_soft_defaults_but_keeps_safety():
    profile = {"allergies": ["peanuts"], "preferred_cuisines": ["italian"],
               "preferred_foods": ["pasta"]}
    result, error = prepare_request(request(cuisines=["japanese"]), profile)
    assert error is None and result["cuisines"] == ["japanese"]
    assert result["foods"] == ["pasta"] and result["allergies"] == ["peanuts"]
    assert prepare_request(request(), {"preferred_foods": "rice"})[1]


def test_history_filters_user_and_limits_to_recent_rows():
    with tempfile.TemporaryDirectory() as directory:
        rows = [{"profile": "alex", "sequence": n} for n in range(12)]
        rows += [None, {"profile": "other", "sequence": 99}]
        save_json(Path(directory) / "interactions.json", rows)
        result, error = load_history(directory, "alex")
        assert error is None and len(result) == 10
        assert result[0]["sequence"] == 2 and result[-1]["sequence"] == 11


def test_profile_menu_round_trip_and_validation():
    with tempfile.TemporaryDirectory() as directory:
        answers = ["alex", "p", "e", "soy", "", "italian", "", "y", "h", "q"]
        with patch("builtins.input", side_effect=answers):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                run_cli({"data_dir": Path(directory)})
        assert "Profile saved" in output.getvalue()
        assert load_profile(directory, "alex")[0]["allergies"] == ["soy"]
        assert save_profile(directory, "alex", {"preferred_foods": "invalid"})
        assert load_profile(directory, "alex")[0]["allergies"] == ["soy"]


def load_tests(loader, tests, pattern):
    return function_suite(globals())
