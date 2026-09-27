"""Canonical AI/CLI categories and rejection of invalid saved preferences."""

import json
from unittest.mock import Mock

import pytest

import iomanager as io


@pytest.fixture(autouse=True)
def isolated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(io, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(io, "LOG_FILE", tmp_path / "test.log")
    monkeypatch.setattr(io, "LEGACY_PROFILE_FILE", tmp_path / "old.json")


@pytest.mark.parametrize("spice", io.SPICE_CHOICES)
def test_ai_and_cli_spice_terms_match(spice):
    expected = {"spice_preference": spice}
    assert io.validate_profile_updates(
        {"spice_preference": spice.upper()}, strict=True,
    ) == expected
    assert io.parse_local_answer(spice, "spice_preference")[
        "profile_updates"
    ] == expected


@pytest.mark.parametrize("value", ["dkdk", "spicy", "lava", "7", [], True])
def test_invalid_ai_spice_rejected(value):
    with pytest.raises(ValueError, match="Spice choices"):
        io.validate_profile_updates({"spice_preference": value}, strict=True)


def test_dietary_synonyms_are_canonical_and_deduplicated():
    values = [" GLUTEN FREE ", "gluten-free", "Halal", "halal"]
    expected = {"dietary_requirements": ["gluten-free", "halal"]}
    assert io.validate_profile_updates(
        {"dietary_requirements": values}, strict=True,
    ) == expected
    assert io.parse_local_answer(
        ", ".join(values), "dietary_requirements",
    )["profile_updates"] == expected
    assert io.normalize_dietary_requirements(["lactose free"]) == [
        "lactose-free",
    ]
    assert io.normalize_dietary_requirements(["dairy free"]) == ["dairy-free"]


@pytest.mark.parametrize("value", [
    ["dkdk"], ["halal", "dkdk"], ["vegan", 42], ["none", "vegan"],
    ["no food"], ["whatever"], [""], ["!!!"],
])
def test_unknown_dietary_terms_never_become_saved_constraints(value):
    with pytest.raises(ValueError, match="Choose dietary requirements"):
        io.validate_profile_updates(
            {"dietary_requirements": value}, strict=True)


def test_cli_rejects_nonsense_and_preserves_explicit_none():
    with pytest.raises(ValueError, match="Choose dietary requirements"):
        io.parse_local_answer("dkdk", "dietary_requirements")
    assert io.parse_local_answer("none", "dietary_requirements")[
        "profile_updates"
    ] == {"dietary_requirements": []}


def test_ai_invalid_answer_does_not_apply_partial_update(monkeypatch):
    profile = io.create_empty_profile()
    profile["dietary_requirements"] = ["halal"]
    reply = json.dumps({
        "intent": "profile_update",
        "profile_updates": {
            "name": "Changed", "dietary_requirements": ["dkdk"],
        },
    })
    monkeypatch.setattr(io, "_call_openrouter", Mock(return_value=reply))
    with pytest.raises(ValueError, match="Please clarify"):
        io.understand_user_message(
            "dkdk", profile, "dietary_requirements", "Requirements?",
            {"openrouter_model": "test"},
        )
    assert profile["name"] is None
    assert profile["dietary_requirements"] == ["halal"]


def test_direct_save_rejects_invalid_value_and_keeps_previous_file():
    config = {"smtp_bypass": True}
    user_id = io.register_user("person@example.com")["userID"]
    io.save_profile(user_id, {"dietary_requirements": ["halal"]}, config)
    original = io.USERS_FILE.read_bytes()
    with pytest.raises(ValueError):
        io.save_profile(user_id, {"dietary_requirements": ["dkdk"]}, config)
    assert io.USERS_FILE.read_bytes() == original


@pytest.mark.parametrize("field, value", [
    ("name", "!?!"), ("location", "x" * 201), ("liked_cuisines", ["Thai", 2]),
    ("dining_preferences", ["cafes", ""]), ("allergies", ["peanuts", "123"]),
])
def test_ai_field_structure_is_not_silently_truncated(field, value):
    with pytest.raises(ValueError):
        io.validate_profile_updates({field: value}, strict=True)


def test_signup_never_offers_another_users_legacy_preferences(monkeypatch):
    original = '{"name": "Another person", "allergies": ["peanuts"]}'
    io.LEGACY_PROFILE_FILE.write_text(original)
    answers = iter(["1", "new@example.com"])
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    user = io.select_user({"smtp_bypass": True})
    assert user["preferences"] == io.create_empty_profile()
    assert all("Import" not in prompt for prompt in prompts)
    assert io.LEGACY_PROFILE_FILE.read_text() == original
