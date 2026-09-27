"""Email ownership and round-robin routing regression checks."""

import json
from unittest.mock import MagicMock, Mock

import pytest
import requests

import iomanager as io


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Isolate credentials, delivery, and profiles from real data."""
    monkeypatch.setattr(io.os, "environ", io.os.environ.copy())
    monkeypatch.setattr(io, "BASE_DIR", tmp_path)
    monkeypatch.setattr(io, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(io, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(io, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(io, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "logs" / "test.log")
    monkeypatch.setattr(io, "LEGACY_PROFILE_FILE", tmp_path / "old.json")
    for name in list(io.os.environ):
        if name.startswith(("OPENROUTER_", "SMTP_")):
            monkeypatch.delenv(name)


@pytest.fixture
def mail_capture(monkeypatch):
    sender = Mock()
    monkeypatch.setattr(io, "send_verification_email", sender)
    monkeypatch.setattr(io.secrets, "randbelow", lambda _: 123456)
    return sender


def test_email_verification_required_and_consumed(mail_capture):
    user_id = io.register_user("person@example.com")["userID"]
    with pytest.raises(ValueError, match="Verify your email"):
        io.load_profile(user_id)
    with pytest.raises(ValueError, match="Verify your email"):
        io.save_profile(user_id, {"name": "Person"})
    io.request_email_verification(user_id, {})
    mail_capture.assert_called_once_with("person@example.com", "123456", {})
    stored = io.USERS_FILE.read_text()
    assert "123456" not in stored
    assert "123456" not in io.LOG_FILE.read_text()
    assert len(io.load_users()[user_id]
               ["email_verification"]["code_hash"]) == 64
    user = io.verify_email_code(user_id, "123456")
    assert user["email_verified"] is True
    assert "email_verification" not in user
    assert io.load_profile(user_id) == io.create_empty_profile()
    with pytest.raises(ValueError, match="Request a verification code"):
        io.verify_email_code(user_id, "123456")


def test_expiry_and_resend_replace_old_code(mail_capture, monkeypatch):
    monkeypatch.setattr(io.time, "time", lambda: 1000)
    user_id = io.register_user("person@example.com")["userID"]
    io.request_email_verification(user_id, {})
    with pytest.raises(ValueError, match="Wait 60"):
        io.request_email_verification(user_id, {})
    monkeypatch.setattr(io.time, "time", lambda: 1600)
    with pytest.raises(ValueError, match="expired"):
        io.verify_email_code(user_id, "123456")
    monkeypatch.setattr(io.secrets, "randbelow", lambda _: 654321)
    io.request_email_verification(user_id, {})
    with pytest.raises(ValueError, match="Incorrect"):
        io.verify_email_code(user_id, "123456")
    assert io.verify_email_code(user_id, "654321")["email_verified"]


def test_failed_attempts_persist_and_are_bounded(mail_capture):
    user_id = io.register_user("person@example.com")["userID"]
    io.request_email_verification(user_id, {})
    for attempt in range(5):
        with pytest.raises(ValueError, match="Incorrect"):
            io.verify_email_code(user_id, "not-a-code")
        assert io.load_users()[user_id]["email_verification"]["attempts"] == (
            attempt + 1
        )
    with pytest.raises(ValueError, match="Too many"):
        io.verify_email_code(user_id, "123456")
    assert io.load_users()[user_id]["email_verified"] is False


def test_codes_are_specific_to_each_user(mail_capture, monkeypatch):
    first = io.register_user("first@example.com")["userID"]
    second = io.register_user("second@example.com")["userID"]
    io.request_email_verification(first, {})
    monkeypatch.setattr(io.secrets, "randbelow", lambda _: 654321)
    io.request_email_verification(second, {})
    with pytest.raises(ValueError, match="Incorrect"):
        io.verify_email_code(second, "123456")
    assert io.verify_email_code(first, "123456")["email_verified"]
    assert not io.load_users()[second]["email_verified"]


def test_old_profiles_must_verify_and_keep_preferences(mail_capture):
    user_id = io.register_user("person@example.com")["userID"]
    users = io.load_users()
    del users[user_id]["email_verified"]
    users[user_id]["preferences"]["name"] = "Existing person"
    io.write_users(users)
    with pytest.raises(ValueError, match="Verify your email"):
        io.load_profile(user_id)
    io.request_email_verification(user_id, {})
    io.verify_email_code(user_id, "123456")
    assert io.load_profile(user_id)["name"] == "Existing person"


def test_quit_keeps_signup_pending(mail_capture, monkeypatch):
    answers = iter(["1", "person@example.com", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert io.select_user({}) is None
    user = next(iter(io.load_users().values()))
    assert user["email_verified"] is False
    answers = iter(["2", user["email"], "123456"])
    assert io.select_user({})["email_verified"] is True
    assert mail_capture.call_count == 1


@pytest.mark.parametrize("security", ["starttls", "ssl"])
def test_smtp_delivery_uses_tls_and_auth(security, monkeypatch):
    config = {
        "smtp_host": "smtp.example.com", "smtp_port": 587,
        "smtp_security": security, "smtp_username": "sender",
        "smtp_password": "smtp-secret", "smtp_from_email": "a@example.com",
    }
    factory = MagicMock()
    server = factory.return_value.__enter__.return_value
    server.send_message.return_value = {}
    monkeypatch.setattr(io.smtplib, "SMTP", factory)
    monkeypatch.setattr(io.smtplib, "SMTP_SSL", factory)
    io.send_verification_email("b@example.com", "123456", config)
    server.login.assert_called_once_with("sender", "smtp-secret")
    assert server.starttls.call_count == (1 if security == "starttls" else 0)
    message = server.send_message.call_args.args[0]
    assert message["To"] == "b@example.com"
    assert "123456" in message.get_content()
    assert "123456" not in io.LOG_FILE.read_text()
    assert "smtp-secret" not in io.LOG_FILE.read_text()


def test_delivery_failure_does_not_verify_or_store_code(monkeypatch):
    user_id = io.register_user("person@example.com")["userID"]
    config = {
        "smtp_host": "smtp.example.com", "smtp_port": 587,
        "smtp_security": "starttls", "smtp_from_email": "a@example.com",
    }
    monkeypatch.setattr(io.smtplib, "SMTP", Mock(
        side_effect=io.smtplib.SMTPException("private provider detail"),
    ))
    with pytest.raises(RuntimeError, match="Could not send") as error:
        io.request_email_verification(user_id, config)
    assert "private provider detail" not in str(error.value)
    user = io.load_users()[user_id]
    assert user["email_verified"] is False
    assert "email_verification" not in user
    assert "private provider detail" not in io.LOG_FILE.read_text()


@pytest.mark.parametrize("email", [
    "a@" + "b" * 64 + ".com", "a\nb@example.com", "a@-domain.com",
    "a@domain-.com", "a@domain..com", "a" * 65 + "@example.com",
])
def test_email_regex_rejects_invalid_addresses(email):
    with pytest.raises(ValueError):
        io.normalize_email(email)


def test_config_reads_model_keys_and_smtp_from_env_file():
    io.ENV_FILE.write_text(
        'OPENROUTER_MODEL=chosen/model\n'
        'OPENROUTER_API_KEYS=alpha,beta,alpha\n'
        'SMTP_HOST=smtp.example.com\n'
        'SMTP_FROM_EMAIL=sender@example.com\n'
    )
    config = io.load_config()
    assert config["openrouter_model"] == "chosen/model"
    assert config["openrouter_api_keys"] == ["alpha", "beta"]
    assert config["smtp_host"] == "smtp.example.com"
    assert io.validate_config(config) == []
    payload = io._build_payload("hi", {}, "name", "Name?", config)
    assert payload["model"] == "chosen/model"


def test_missing_model_has_no_hardcoded_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy-key")
    config = io.load_config()
    assert config["openrouter_model"] == ""
    assert any("OPENROUTER_MODEL" in error
               for error in io.validate_config(config))


@pytest.mark.parametrize("content", ['["alpha", "beta"]', "alpha\nbeta\n",
                                     "alpha,beta"])
def test_key_file_and_source_precedence(content, monkeypatch):
    (io.BASE_DIR / "keys.txt").write_text(content)
    monkeypatch.setenv("OPENROUTER_API_KEYS_FILE", "keys.txt")
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy")
    assert io.load_api_keys() == ["alpha", "beta"]
    monkeypatch.setenv("OPENROUTER_API_KEYS", '["selected", "other"]')
    assert io.load_api_keys() == ["selected", "other"]
    monkeypatch.delenv("OPENROUTER_API_KEYS")
    monkeypatch.delenv("OPENROUTER_API_KEYS_FILE")
    assert io.load_api_keys() == ["legacy"]


@pytest.mark.parametrize("value", ['[]', '["key", null]', '["key", ""]',
                                   '[broken', 'key,', 'replace_with_key'])
def test_invalid_key_lists_rejected(value, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEYS", value)
    with pytest.raises(ValueError):
        io.load_api_keys()


def test_bad_key_file_does_not_fall_back_to_other_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEYS_FILE", "missing.json")
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy")
    with pytest.raises(ValueError, match="Cannot read"):
        io.load_api_keys()


def test_router_round_robin_including_failed_requests(monkeypatch):
    response = Mock()
    response.json.return_value = {
        "choices": [{"message": {"content": "{}"}}],
    }
    post = Mock(side_effect=[response, requests.Timeout, response, response])
    monkeypatch.setattr(io.requests, "post", post)
    config = {
        "openrouter_api_keys": ["alpha", "beta", "gamma"],
        "openrouter_base_url": "https://test", "app_name": "BiteFinder",
        "openrouter_timeout_seconds": 30,
    }
    io._call_openrouter({}, config)
    with pytest.raises(RuntimeError, match="timed out"):
        io._call_openrouter({}, config)
    io._call_openrouter({}, config)
    io._call_openrouter({}, config)
    assert [call.kwargs["headers"]["Authorization"]
            for call in post.call_args_list] == [
                "Bearer alpha", "Bearer beta", "Bearer gamma", "Bearer alpha",
    ]
    assert all(secret not in io.LOG_FILE.read_text()
               for secret in ["alpha", "beta", "gamma"])


@pytest.mark.parametrize("value, expected", [
    (None, False), ("false", False), ("true", True), ("TRUE", True),
])
def test_smtp_bypass_config(value, expected, monkeypatch):
    if value is not None:
        io.ENV_FILE.write_text(f"SMTP_BYPASS={value}\n")
    assert io.load_config()["smtp_bypass"] is expected


def test_bypass_signup_chat_and_resume_without_smtp(monkeypatch):
    sender = Mock(side_effect=AssertionError("SMTP must not be called"))
    monkeypatch.setattr(io, "send_verification_email", sender)
    config = {"smtp_bypass": True, "app_name": "Test",
              "openrouter_model": "test"}
    answers = iter(["1", "person@example.com"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    user = io.select_user(config)
    user_id = user["userID"]
    io.save_profile(user_id, {"name": "Test"}, config)
    assert io.load_profile(user_id, config)["name"] == "Test"
    answers = iter(["/profile", "/reset", "/quit"])
    io.run_profile_chatbot(config, user_id)
    assert io.load_profile(user_id, config) == io.create_empty_profile()
    answers = iter(["2", user["email"]])
    assert io.select_user(config)["userID"] == user_id
    assert io.load_users()[user_id]["email_verified"] is False
    assert "email_verified_at" not in io.load_users()[user_id]
    sender.assert_not_called()
    with pytest.raises(ValueError, match="Verify your email"):
        io.load_profile(user_id, {"smtp_bypass": False})


def test_bypass_allows_legacy_import_but_still_validates_email():
    config = {"smtp_bypass": True}
    with pytest.raises(ValueError):
        io.register_user("invalid-email")
    user_id = io.register_user("person@example.com")["userID"]
    io.LEGACY_PROFILE_FILE.write_text('{"name": "Original"}')
    io.import_legacy_profile(user_id, config)
    assert io.load_profile(user_id, config)["name"] == "Original"
    assert io.load_users()[user_id]["email_verified"] is False
