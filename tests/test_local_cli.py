"""Fixed-answer CLI validation and network bypass regression checks."""

from unittest.mock import Mock

import pytest

import iomanager as io


@pytest.fixture(autouse=True)
def local_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(io.os, "environ", io.os.environ.copy())
    for key in list(io.os.environ):
        if key.startswith("OPENROUTER_") or key == "AI_BYPASS":
            monkeypatch.delenv(key)
    for name, path in {
        "ENV_FILE": tmp_path / ".env", "USERS_FILE": tmp_path / "users.json",
        "LOG_FILE": tmp_path / "logs" / "test.log",
        "DATA_DIR": tmp_path / "data", "LOG_DIR": tmp_path / "logs",
    }.items():
        monkeypatch.setattr(io, name, path)
    monkeypatch.setattr(io.requests, "post", Mock(
        side_effect=AssertionError("Local mode must not call OpenRouter"),
    ))


def test_local_config_needs_no_model_or_keys(monkeypatch):
    io.ENV_FILE.write_text('AI_BYPASS=true\n')
    monkeypatch.setenv("OPENROUTER_API_KEYS_FILE", "/missing/keys.json")
    config = io.load_config()
    assert config["ai_bypass"] is True
    assert config["openrouter_api_keys"] == []
    assert config["openrouter_model"] == ""
    assert io.validate_config(config) == []


def test_ai_enabled_by_default():
    config = io.load_config()
    assert config["ai_bypass"] is False
    assert len(io.validate_config(config)) == 2


@pytest.mark.parametrize("field, answer", [
    ("name", ""), ("name", "x" * 201), ("name", "/invalid"),
    ("location", "!!!"), ("location", "a\tb"),
    ("max_distance_km", "10"), ("max_distance_km", "-2 km"),
    ("max_distance_km", "0 km"), ("max_distance_km", "101 km"),
    ("max_distance_km", "2001 mins"), ("max_distance_km", "0.001 km"),
    ("budget_per_person", "$20"), ("budget_per_person", "nan"),
    ("budget_per_person", "-1"), ("budget_per_person", "1001"),
    ("budget_per_person", "10.005"), ("budget_per_person", "0"),
    ("allergies", "peanuts,"), ("allergies", "none, peanuts"),
    ("liked_cuisines", "123"), ("spice_preference", "spicy"),
])
def test_local_invalid_answers_rejected(field, answer):
    with pytest.raises(ValueError):
        io.parse_local_answer(answer, field)


@pytest.mark.parametrize("field, answer, expected", [
    ("name", " Alex ", {"name": "Alex"}),
    ("location", "123456", {"location": "123456"}),
    ("max_distance_km", "10 mins", {
        "max_distance_km": 0.5, "max_travel_time_minutes": 10,
    }),
    ("max_distance_km", "1 KM", {
        "max_distance_km": 1, "max_travel_time_minutes": 20,
    }),
    ("budget_per_person", "20.50", {"budget_per_person": 20.5}),
    ("allergies", "none", {"allergies": []}),
    ("liked_cuisines", "Thai, Japanese", {
        "liked_cuisines": ["Thai", "Japanese"],
    }),
    ("spice_preference", "MILD", {"spice_preference": "mild"}),
])
def test_local_valid_answers(field, answer, expected):
    assert io.parse_local_answer(answer, field)["profile_updates"] == expected


def test_complete_local_onboarding_retries_invalid_answers(
    monkeypatch, capsys,
):
    config = {"ai_bypass": True, "smtp_bypass": True, "app_name": "Test"}
    user_id = io.register_user("person@example.com")["userID"]
    answers = iter([
        "Alex", "Punggol", "bad", "10 mins", "-5", "20", "none",
        "peanuts", "Thai, Japanese", "none", "spicy", "mild", "cafes",
        "/profile", "/help", "/quit",
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    io.run_profile_chatbot(config, user_id)
    profile = io.load_profile(user_id, config)
    assert io.get_next_question(profile) == (None, None)
    assert profile["name"] == "Alex"
    assert profile["max_distance_km"] == 0.5
    assert profile["max_travel_time_minutes"] == 10
    assert profile["budget_per_person"] == 20
    assert profile["allergies"] == ["peanuts"]
    assert profile["spice_preference"] == "mild"
    assert io.load_users()[user_id]["preferences"] == profile
    output = capsys.readouterr().out
    assert "Local CLI profile setup" in output
    assert "Comma-separated answers" in output
    assert output.count("Your profile was not changed.") == 3
    io.requests.post.assert_not_called()


@pytest.mark.parametrize("answer", [
    "123", "peanuts2", "milk, 3 eggs", "milk²",
])
def test_allergy_answers_reject_numbers(answer):
    with pytest.raises(ValueError, match="cannot contain numbers"):
        io.parse_local_answer(answer, "allergies")


@pytest.mark.parametrize("value", [123, "peanuts2", ["milk", 3], ["egg3"]])
def test_ai_allergy_updates_reject_numbers(value):
    profile = io.create_empty_profile()
    profile["allergies"] = ["peanuts"]
    io.update_profile(profile, {"allergies": value})
    assert profile["allergies"] == ["peanuts"]


def test_logout_resumes_another_email_and_preserves_profiles(monkeypatch):
    config = {"ai_bypass": True, "smtp_bypass": True, "app_name": "Test"}
    first = io.register_user("first@example.com")["userID"]
    second = io.register_user("second@example.com")["userID"]
    monkeypatch.setattr(io, "load_config", lambda: config)
    monkeypatch.setattr(io.sys, "argv", ["iomanager.py"])
    answers = iter([
        "2", "first@example.com", "Alex", "/logout",
        "2", "second@example.com", "Sam", "/logout",
        "2", "first@example.com", "Punggol", "/quit",
    ])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    io.main()
    first_profile = io.load_profile(first, config)
    second_profile = io.load_profile(second, config)
    assert first_profile["name"] == "Alex"
    assert first_profile["location"] == "Punggol"
    assert second_profile["name"] == "Sam"
    assert second_profile["location"] is None
    assert io.LOG_FILE.read_text().count("session.logout") == 2
    io.requests.post.assert_not_called()


def test_logout_does_not_succeed_if_save_fails(monkeypatch, capsys):
    config = {"ai_bypass": True, "smtp_bypass": True, "app_name": "Test"}
    user_id = io.register_user("first@example.com")["userID"]
    monkeypatch.setattr("builtins.input", lambda _: "/logout")
    monkeypatch.setattr(io, "save_profile", Mock(side_effect=RuntimeError))
    with pytest.raises(RuntimeError):
        io.run_profile_chatbot(config, user_id)
    assert "Logged out" not in capsys.readouterr().out
