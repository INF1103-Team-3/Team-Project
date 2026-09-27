"""Regression checks for signup, persistence, and the consolidated chatbot."""

import json
from unittest.mock import Mock

import pytest
import requests

import iomanager as io


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Use temporary data only; never touch real profiles or logs."""
    monkeypatch.setattr(io, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(io, "LEGACY_PROFILE_FILE", tmp_path / "old.json")
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "logs" / "test.log")
    monkeypatch.setattr(io, "DEBUG_ENABLED", False)


def test_signup_is_unique_and_persisted():
    first = io.register_user(" Alex@Example.com ")
    second = io.register_user("sam@example.com")
    assert first["userID"] != second["userID"]
    assert first["email"] == "alex@example.com"
    assert io.find_user(" ALEX@example.com ") == first
    assert len(io.load_users()) == 2
    with pytest.raises(ValueError, match="already registered"):
        io.register_user("alex@EXAMPLE.com")
    assert io.find_user("sam@example.com") == second
    with pytest.raises(ValueError, match="No profile found"):
        io.find_user("unknown@example.com")


@pytest.mark.parametrize("email", ["", "abc", "a@b", "a b@c.com",
                                   ".a@b.com", "a..b@c.com", None])
def test_invalid_email_never_creates_registry(email):
    with pytest.raises(ValueError):
        io.register_user(email)
    assert not io.USERS_FILE.exists()


def test_preferences_and_reset_are_isolated():
    first = register_verified_user("a@example.com")["userID"]
    second = register_verified_user("b@example.com")["userID"]
    io.save_profile(first, {"name": "Alex", "allergies": ["peanuts"]})
    io.save_profile(second, {"name": "Sam", "budget_per_person": 20})
    io.reset_profile(first)
    assert io.load_profile(first) == io.create_empty_profile()
    assert io.load_profile(second)["name"] == "Sam"
    assert io.load_users()[first]["email"] == "a@example.com"
    with pytest.raises(ValueError, match="sign up"):
        io.save_profile("unknown", {"name": "No signup"})


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"x": {}}'])
def test_bad_storage_is_preserved(contents):
    io.USERS_FILE.write_text(contents)
    with pytest.raises(RuntimeError):
        register_verified_user("a@example.com")
    assert io.USERS_FILE.read_text() == contents


def test_failed_save_keeps_previous_file(monkeypatch):
    user_id = register_verified_user("a@example.com")["userID"]
    original = io.USERS_FILE.read_bytes()
    monkeypatch.setattr(io.os, "replace", Mock(side_effect=OSError))
    with pytest.raises(RuntimeError, match="previous saved file"):
        io.save_profile(user_id, {"name": "New"})
    assert io.USERS_FILE.read_bytes() == original
    assert not list(io.USERS_FILE.parent.glob(".users-*.tmp"))


def test_explicit_legacy_import():
    io.LEGACY_PROFILE_FILE.write_text(json.dumps({"name": "Original"}))
    user_id = register_verified_user("a@example.com")["userID"]
    assert io.load_profile(user_id)["name"] is None
    io.import_legacy_profile(user_id)
    assert io.load_profile(user_id)["name"] == "Original"
    assert io.LEGACY_PROFILE_FILE.exists()


def test_validation_preserves_original_rules():
    updates = io.validate_profile_updates({
        "name": " Alex ", "allergies": [], "liked_cuisines": ["Thai"],
        "budget_per_person": "30", "max_distance_km": -1,
        "email": "intruder@example.com", "userID": "intruder",
    })
    assert updates == {
        "name": "Alex", "allergies": [], "liked_cuisines": ["Thai"],
        "budget_per_person": 30,
    }
    profile = io.create_empty_profile()
    io.update_profile(profile, updates)
    assert io.get_next_question(profile)[0] == "location"
    assert "Allergies: None" in io.format_profile(profile)


def test_ai_request_and_chat_corrections(monkeypatch, capsys):
    user_id = register_verified_user("a@example.com")["userID"]
    response = Mock()
    response.json.side_effect = [
        {"choices": [{"message": {"content": json.dumps({
            "intent": "profile_update",
            "profile_updates": {"name": "Alex", "budget_per_person": 20},
        })}}]},
        {"choices": [{"message": {"content": json.dumps({
            "intent": "profile_update",
            "profile_updates": {"budget_per_person": 30},
        })}}]},
    ]
    post = Mock(return_value=response)
    monkeypatch.setattr(io.requests, "post", post)
    answers = iter(["I'm Alex, budget 20", "actually 30", "/profile",
                    "/help", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    config = {
        "app_name": "BiteFinder", "openrouter_model": "test",
        "openrouter_api_key": "secret", "openrouter_base_url": "https://test",
        "openrouter_timeout_seconds": 30,
    }
    io.run_profile_chatbot(config, user_id)
    assert io.load_profile(user_id)["budget_per_person"] == 30
    assert post.call_count == 2
    context = json.loads(
        post.call_args.kwargs["json"]["messages"][1]["content"])
    assert context["current_profile"]["budget_per_person"] == 20
    assert "email" not in context["current_profile"]
    assert "Profile saved. Goodbye!" in capsys.readouterr().out
    assert "secret" not in io.LOG_FILE.read_text()


def test_signup_resume_and_cancel(monkeypatch):
    monkeypatch.setattr(io, "send_verification_email", Mock())
    monkeypatch.setattr(io.secrets, "randbelow", lambda _: 123456)
    answers = iter(["1", "a@example.com", "123456"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    user = io.select_user({})
    answers = iter(["2", user["email"]])
    assert io.select_user({}) == user
    answers = iter(["3"])
    assert io.select_user({}) is None


def test_chat_reset_and_eof(monkeypatch):
    user_id = register_verified_user("a@example.com")["userID"]
    io.save_profile(user_id, {"name": "Alex"})
    monkeypatch.setattr("builtins.input", Mock(
        side_effect=["/reset", EOFError]))
    io.run_profile_chatbot({"app_name": "Test", "openrouter_model": "test"},
                           user_id)
    assert io.load_profile(user_id) == io.create_empty_profile()


def test_bad_ai_response_and_network_errors(monkeypatch):
    assert io._parse_json_response('```json\n{"intent": "help"}\n```') == {
        "intent": "help",
    }
    for content in ("not json", "[]"):
        with pytest.raises(RuntimeError):
            io._parse_json_response(content)
    monkeypatch.setattr(io.requests, "post", Mock(
        side_effect=requests.Timeout))
    config = {"app_name": "Test", "openrouter_base_url": "https://test",
              "openrouter_api_key": "secret", "openrouter_timeout_seconds": 1}
    with pytest.raises(RuntimeError, match="timed out"):
        io._call_openrouter({}, config)


def test_debug_levels_and_unwritable_log(monkeypatch, capsys):
    monkeypatch.setattr(io, "DEBUG_ENABLED", True)
    io.debug_log("Saved.", "INFO", "storage.save")
    text = io.LOG_FILE.read_text()
    assert "INFO" in text and "storage.save | Saved." in text
    assert "storage.save" in capsys.readouterr().err
    monkeypatch.setattr(io, "LOG_FILE", io.LOG_FILE / "invalid.log")
    io.debug_log("Must not crash.")
    assert "could not be written" in capsys.readouterr().err


def register_verified_user(email):
    """Seed a previously verified account for unrelated regression tests."""
    user = io.register_user(email)
    users = io.load_users()
    users[user["userID"]]["email_verified"] = True
    io.write_users(users)
    return users[user["userID"]]
