"""Travel time extraction, conversion, and per-user persistence checks."""

import json
from unittest.mock import Mock

import pytest

import iomanager as io


@pytest.mark.parametrize("updates, expected", [
    ({"max_travel_time_minutes": 10}, (0.5, 10)),
    ({"max_travel_time_minutes": 15}, (0.75, 15)),
    ({"max_distance_km": 2}, (2, 40)),
    ({"max_distance_km": 0.5}, (0.5, 10)),
    ({"max_travel_time_minutes": 1000}, (50, 1000)),
    ({"max_travel_time_minutes": 2000}, (100, 2000)),
    ({"max_distance_km": 100}, (100, 2000)),
    ({"max_distance_km": 2, "max_travel_time_minutes": 15}, (2, 15)),
])
def test_travel_limit_conversion(updates, expected, tmp_path, monkeypatch):
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "test.log")
    result = io.validate_profile_updates(updates)
    assert (result["max_distance_km"], result["max_travel_time_minutes"]) == (
        expected
    )


@pytest.mark.parametrize("value", [0, -10, True, 2001, "NaN", "inf", "ten"])
def test_invalid_time_does_not_create_distance(value, tmp_path, monkeypatch):
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "test.log")
    assert io.validate_profile_updates(
        {"max_travel_time_minutes": value}) == {}


def test_travel_corrections_replace_old_estimates(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "test.log")
    profile = io.create_empty_profile()
    io.update_profile(profile, {"max_distance_km": 8})
    io.update_profile(profile, {"max_travel_time_minutes": 10})
    assert profile["max_distance_km"] == 0.5
    assert profile["max_travel_time_minutes"] == 10
    io.update_profile(profile, {"max_distance_km": 2})
    assert profile["max_travel_time_minutes"] == 40
    io.update_profile(profile, {"name": "Alex"})
    assert profile["max_travel_time_minutes"] == 40


def test_time_answer_is_saved_displayed_and_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "test.log")
    user_id = io.register_user("person@example.com")["userID"]
    other_id = io.register_user("other@example.com")["userID"]
    config = {"smtp_bypass": True, "app_name": "Test",
              "openrouter_model": "test"}
    reply = json.dumps({
        "intent": "profile_update",
        "profile_updates": {"max_travel_time_minutes": 10},
    })
    call = Mock(return_value=reply)
    monkeypatch.setattr(io, "_call_openrouter", call)
    profile = io.create_empty_profile()
    result = io.understand_user_message(
        "10 mins away", profile, "max_distance_km",
        io.QUESTION_MAP["max_distance_km"], config,
    )
    io.update_profile(profile, result["profile_updates"])
    io.save_profile(user_id, profile, config)
    saved = io.load_profile(user_id, config)
    assert saved["max_distance_km"] == 0.5
    assert saved["max_travel_time_minutes"] == 10
    other_profile = io.load_profile(other_id, config)
    assert other_profile["max_travel_time_minutes"] is None
    summary = io.format_profile(saved)
    assert "Max travel time: 10 minutes" in summary
    assert "Max travel distance: 0.5 km" in summary
    assert "actual travel times may vary" in summary
    log = io.LOG_FILE.read_text()
    assert "profile.travel" in log
    assert "max_travel_time_minutes=10, max_distance_km=0.5" in log
    assert io.load_users()[user_id]["preferences"] == saved


def test_legacy_profile_gains_time_without_extra_question(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(io, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "test.log")
    user_id = io.register_user("person@example.com")["userID"]
    users = io.load_users()
    users[user_id]["preferences"] = {
        "name": "Alex", "location": "Punggol", "max_distance_km": 3,
    }
    io.write_users(users)
    config = {"smtp_bypass": True}
    profile = io.load_profile(user_id, config)
    assert profile["max_travel_time_minutes"] == 60
    assert io.get_next_question(profile)[0] == "budget_per_person"
    io.save_profile(user_id, profile, config)
    assert io.load_users()[
        user_id]["preferences"]["max_travel_time_minutes"] == 60
    io.reset_profile(user_id, config)
    profile = io.load_profile(user_id, config)
    assert profile["max_distance_km"] is None
    assert profile["max_travel_time_minutes"] is None
