"""All terminal input/output for BiteFinder profiles and search setup."""

import os
import re
import sys
import time

from sources.prompts import (
    COMMANDS, COMMAND_HELP, EDIT_ALIASES, EDIT_HINT, HELP_TEXT, LABELS,
    QUESTIONS,
)

from BIS import ai_manager, data_manager, logic_manager
from BIS.classes.io_manager import IOManager
from BIS.classes.password_hasher import PasswordHasher
from BIS.support.email_verification import challenge as email_challenge
from BIS.support.email_verification import service as email_service
from common import terminal_ui as ui
from common import geocode_cache
from BIS.classes.location_gateway import LocationGateway
from sources.profile_schema import (
    CUISINES, CUISINE_FIELDS, OTHER_PREFERENCES, PREFERENCE_FIELDS,
    clean_text, normalize_email, normalize_username, validate_updates,
    validate_value, validate_travel_minutes,
)

_PASSWORD_HASHER = PasswordHasher()
_color_handler = None
_MANAGER = None
_LOCATION_GATEWAY = LocationGateway(
    logic_manager,
    geocode_cache,
    os.getenv(
        "BITEFINDER_GEOCODE_URL",
        "https://maps.googleapis.com/maps/api/geocode/json",
    ),
)


def manager():
    """Return the configured BIS IO Manager."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = IOManager(
            sys.modules[__name__],
            ai_manager.review_prompt_text,
            logic_manager.manager(),
        )
    return _MANAGER


def set_color_handler(handler):
    """Bind the current account's persisted color command to all prompts."""
    global _color_handler
    _color_handler = handler


def apply_color_setting(enabled):
    """Apply the signed-in account's persisted color preference."""
    if _color_handler is None:
        display_message("Sign in before changing your color setting.")
        return
    _color_handler(enabled)


def display_message(message, role="body"):
    ui.message(message, "error" if isinstance(message, Exception) else role)


def display_debug(message):
    print(message, file=sys.stderr)


def read_input(prompt="You: "):
    while True:
        try:
            value = ui.read_input(prompt).strip()
        except EOFError:
            return None
        lowered = " ".join(value.lower().split())
        if lowered == "/help":
            display_help()
            continue
        if lowered.startswith("/help "):
            display_help(lowered[6:].lstrip("/"))
            continue
        if lowered in {"/color off", "/color on"}:
            apply_color_setting(lowered == "/color on")
            continue
        if lowered == "/color" or lowered.startswith("/color "):
            display_help("color")
            continue
        return value


def ask_yes_no(question, config=None, default=None):
    """Ask for a decision; only callers with an explicit default accept Enter."""
    while True:
        hint = " (yes/no, Enter = yes): " if default is True else " (yes/no): "
        value = read_input(question + hint)
        if value is None or value.lower() in {"/quit", "/exit", "/cancel"}:
            return None
        if not value and default is not None:
            return default
        if value.lower() in {"yes", "y"}:
            return True
        if value.lower() in {"no", "n"}:
            return False
        if config and value and not value.startswith("/"):
            suggested = ai_manager.interpret_search_choice(
                value, ("yes", "no"), config)
            if suggested:
                answer = read_input(f"Did you mean {suggested}? (yes/no): ")
                if _cancelled(answer):
                    return None
                if answer.lower() in {"yes", "y"}:
                    return suggested == "yes"
                if answer.lower() in {"no", "n"}:
                    continue
        display_message("Please answer yes or no, or /cancel.")


def prompt_username():
    while True:
        value = read_input("What username should I use? (1–50 characters): ")
        if value is None or value.lower() in {"/quit", "/cancel"}:
            return None
        try:
            return normalize_username(value)
        except ValueError as error:
            display_message(error)


def read_secret_input(prompt="Password: "):
    try:
        return ui.read_secret(prompt)
    except EOFError:
        return None


def prompt_new_password(confirm=True, *, cancel_raises=False):
    while True:
        value = read_secret_input("Password (6-128 characters, or /cancel): ")
        if value is None or value.strip().lower() in {"/quit", "/exit"}:
            return None
        if value.strip().lower() == "/cancel":
            if cancel_raises:
                raise ValueError("Password setup cancelled.")
            return None
        try:
            credential = _PASSWORD_HASHER.create(value)
        except ValueError as error:
            display_message(error)
            continue
        if not confirm:
            return credential
        repeated = read_secret_input("Confirm password (or /cancel): ")
        if repeated is None or repeated.strip().lower() in {"/quit", "/exit"}:
            return None
        if repeated.strip().lower() == "/cancel":
            if cancel_raises:
                raise ValueError("Password setup cancelled.")
            return None
        if repeated != value:
            display_message("Passwords do not match. Please try again.")
            continue
        return credential


def verify_user_password(user_id, *, max_attempts=5, cancel_raises=True):
    credential = data_manager.get_credentials(user_id)
    if credential is None:
        return "enroll"
    for _ in range(max_attempts):
        password = read_secret_input("Password (or /cancel): ")
        if password is None or password.strip().lower() in {"/quit", "/exit"}:
            return None
        if password.strip().lower() == "/cancel":
            if cancel_raises:
                raise ValueError("Sign-in cancelled.")
            return False
        if _PASSWORD_HASHER.verify(password, credential):
            return True
        display_message("Incorrect password.", role="error")
    message = "Too many incorrect password attempts."
    if cancel_raises:
        raise ValueError(message)
    display_message(message, role="error")
    return False


def format_preference_value(field, value):
    if value is None:
        return "Not answered"
    if value == [] or value == "":
        return "None"
    if isinstance(value, list):
        return ", ".join(value)
    formats = {
        "max_distance_km": "{} km", "max_travel_time_minutes": "{} minutes",
        "budget_per_person": "SGD {}",
    }
    return formats.get(field, "{}").format(value)


def display_profile(user):
    ui.section("Your profile")
    ui.field("Username", user['username'] or 'Not answered', indent=0)
    for field in PREFERENCE_FIELDS:
        rendered = format_preference_value(field, user["preferences"][field])
        ui.field(LABELS[field], rendered, indent=0)
    if user["preferences"]["max_distance_km"] is not None:
        ui.line("Conversions are approximate: 1 km ≈ 20 minutes on foot.",
                "muted")


def display_record(record):
    """Display one BiteFinder profile record."""
    display_profile(record)


def display_list(records):
    """Display a numbered list through the terminal IO boundary."""
    for number, record in enumerate(records, 1):
        ui.item(number, str(record))


def display_result(result):
    """Display one validated BIS search result."""
    display_search_summary(result)


def display_help(topic=None):
    """Show brief command help or detailed editing instructions."""
    if topic is None:
        ui.section("Help")
        ui.line(HELP_TEXT, highlight_commands=True)
        return
    if topic == "edit_hint":
        ui.section("Editing preferences")
        ui.line(EDIT_HINT, highlight_commands=True)
        return
    ui.section(f"Help: {topic}")
    ui.line(COMMAND_HELP.get(
        topic, "Unknown help topic. Type /help to see available commands.",
    ), highlight_commands=True)


def display_welcome(user):
    """Keep startup brief; detailed commands are available on request."""
    display_message(f"Hi {user['username']}! Let's set up your preferences.")
    display_message("Type /help for commands.")


def verify_email_interactively(user, config):
    if config.get("smtp_bypass"):
        if not user["email_verified"]:
            display_message("SMTP verification bypass is enabled for testing.",
                            role="bypass")
        return user
    pending = email_service.get_challenge(user["userID"])
    needs_code = (
        not pending or time.time() >= pending["expires_at"]
        or pending["attempts"] >= email_challenge.VERIFICATION_MAX_ATTEMPTS
    )
    if needs_code:
        try:
            email_service.request_code(user, config)
            display_message("A verification code was emailed to you.")
        except (ValueError, RuntimeError) as error:
            display_message(error)
    else:
        display_message(
            "Enter the code recently emailed to you, or use /resend.")
    while True:
        code = read_input("Verification code (/resend or /quit): ")
        if code is None or code.lower() in {"/quit", "/exit"}:
            return None
        try:
            if code.lower() == "/resend":
                email_service.request_code(user, config)
                display_message("A new verification code was emailed to you.")
                continue
            was_verified = user["email_verified"]
            user = email_service.verify_code(user, code, config)
            display_message(
                "Email confirmed. Welcome back." if was_verified
                else "Email verified.")
            return user
        except (ValueError, RuntimeError) as error:
            display_message(error)


def find_or_register_user(choice, email):
    email = normalize_email(email)
    if choice == "2":
        return data_manager.find_user(email)
    if data_manager.email_exists(email):
        raise ValueError("This email is already registered. Choose sign in.")
    username = prompt_username()
    if username is None:
        return None
    credential = prompt_new_password(confirm=True, cancel_raises=True)
    if credential is None:
        return None
    user = data_manager.register_user(email, username)
    data_manager.save_credentials(user["userID"], credential)
    display_message("Signed up. Sign in using your email and password.")
    return user


def complete_account(user, config):
    if user is None:
        return None
    user = verify_email_interactively(user, config)
    if user is None:
        return None
    if user["username"] is not None:
        return user
    username = prompt_username()
    if username is None:
        return None
    return data_manager.save(dict(user, username=username))


def _signin_with_password(user, config):
    password_status = verify_user_password(user["userID"], cancel_raises=True)
    if password_status is None:
        return None
    if password_status == "enroll":
        verified_user = complete_account(user, config)
        if verified_user is None:
            return None
        display_message(
            "No password is set for this account yet. "
            "Create a password to secure your account."
        )
        credential = prompt_new_password(confirm=True, cancel_raises=True)
        if credential is None:
            return None
        data_manager.save_credentials(verified_user["userID"], credential)
        display_message("Password saved.")
        return verified_user
    return complete_account(user, config)


def select_user(config):
    while True:
        ui.section("Welcome to BiteFinder")
        ui.item(1, "Sign up")
        ui.item(2, "Sign in")
        ui.item(3, "Quit")
        choice = read_input("Choose 1, 2, or 3: ")
        if choice is None or choice.lower() in {
            "3", "quit", "exit", "/quit", "/exit",
        }:
            return None
        if choice not in {"1", "2"}:
            display_message("Choose 1, 2, or 3.")
            continue
        email = read_input("Email: ")
        if email is None:
            return None
        try:
            user = find_or_register_user(choice, email)
            if user is None:
                return None
            if choice == "2":
                return _signin_with_password(user, config)
            return complete_account(user, config)
        except (ValueError, RuntimeError) as error:
            display_message(error)


def _cancelled(value):
    return value is None or value.lower() in {"/cancel", "/quit", "/exit"}


def ask_search_location(config):
    while True:
        raw = read_input(
            "Where are you now? Postal code, address, landmark, or "
            "lat,lng (/cancel): "
        )
        if _cancelled(raw):
            return None
        if raw.lower() in {"here", "current", "current location", "my location"}:
            display_message("Enter an address, postal code, landmark, or coordinates.")
            continue
        try:
            raw = clean_text(raw, 200)
            cached = _LOCATION_GATEWAY.lookup_cached(raw)
            query = raw
            if not cached and not logic_manager.is_direct_location_input(raw):
                try:
                    query = ai_manager.interpret_location(raw, config)
                except RuntimeError:
                    # Google can geocode the original landmark when the AI is unavailable.
                    query = raw
            location = _LOCATION_GATEWAY.resolve(
                query, config.get("google_maps_api_key", ""))
            _LOCATION_GATEWAY.remember((raw, query), location)
        except (ValueError, RuntimeError, OSError) as error:
            display_message(error)
            continue
        ui.line(
            f"Found: {location['label']} "
            f"({location['latitude']:.6f}, {location['longitude']:.6f})",
            "success")
        confirmed = ask_yes_no("Is this your current location?", config)
        if confirmed is None:
            return None
        if confirmed:
            return location


def ask_search_mode(config=None):
    while True:
        value = read_input(
            "Travel by walking, driving, or transit? "
            "(walk/drive/transit, /cancel): ")
        if _cancelled(value):
            return None
        mode = value.lower()
        if mode in {"walk", "walking"}:
            return "walk"
        if mode in {"drive", "driving"}:
            return "drive"
        if mode in {"transit", "public transport", "public transit"}:
            return "transit"
        if config and value and not value.startswith("/"):
            suggested = ai_manager.interpret_search_choice(
                value, ("walk", "drive", "transit"), config)
            if suggested:
                confirmed = ask_yes_no(f"Did you mean {suggested}?", config)
                if confirmed is None:
                    return None
                if confirmed:
                    return suggested
                continue
        display_message("Choose walk, drive, or transit.")


def ask_search_distance(profile, mode, config=None, default_source="profile"):
    try:
        default = validate_value("max_distance_km", profile.get("max_distance_km"))
    except ValueError:
        default = None
    while True:
        hint = (f" [Enter = {default:g} km from {default_source}]"
                if default else "")
        value = read_input(f"Maximum {mode} distance in km{hint} (/cancel): ")
        if _cancelled(value):
            return None
        if not value and default is not None:
            return default
        match = re.fullmatch(r"(\d+(?:\.\d{1,2})?)\s*(?:km)?", value.lower())
        if match:
            try:
                return validate_value("max_distance_km", float(match[1]))
            except ValueError as error:
                display_message(error)
                continue
        if value and config and not config.get("ai_bypass"):
            try:
                suggested = ai_manager.interpret_search_number(
                    value, "max_distance_km", config)
                if suggested is not None:
                    suggested = validate_value("max_distance_km", suggested)
                    confirmed = ask_yes_no(
                        f"Use {suggested:g} km as your maximum {mode} distance?",
                        config)
                    if confirmed is None:
                        return None
                    if confirmed:
                        return suggested
                    continue
            except (RuntimeError, ValueError) as error:
                display_message(error)
                continue
        display_message("Enter a positive distance in km, such as 2 or 2.5 km.")


def ask_search_travel_minutes(mode, config=None, default=None,
                              default_source=None):
    """Ask for a verified route duration limit for the chosen mode."""
    while True:
        source = f" from {default_source}" if default_source else ""
        hint = (f" [Enter = {default:g} min{source}]"
                if default is not None else "")
        value = read_input(
            f"Maximum {mode} journey time in minutes{hint} (/cancel): ")
        if _cancelled(value):
            return None
        if not value and default is not None:
            return default
        match = re.fullmatch(
            r"(\d+(?:\.\d{1,2})?)\s*(?:minutes?|mins?)?", value.lower())
        if match:
            try:
                return validate_travel_minutes(float(match[1]))
            except ValueError as error:
                display_message(error)
                continue
        if value and config and not config.get("ai_bypass"):
            try:
                suggested = ai_manager.interpret_search_number(
                    value, "max_travel_minutes", config)
                if suggested is not None:
                    suggested = validate_travel_minutes(suggested)
                    confirmed = ask_yes_no(
                        f"Use {suggested:g} minutes as your maximum "
                        f"{mode} journey time?", config)
                    if confirmed is None:
                        return None
                    if confirmed:
                        return suggested
                    continue
            except (RuntimeError, ValueError) as error:
                display_message(error)
                continue
        display_message("Enter a travel time from 1 to 240 minutes.")


def ask_search_limit(profile, mode, config=None, current=None):
    """Return one selected distance or duration for the chosen travel mode."""
    try:
        profile_minutes = validate_travel_minutes(
            profile.get("max_travel_time_minutes"))
    except ValueError:
        profile_minutes = None
    if mode == "transit":
        if current is None:
            return None, ask_search_travel_minutes(
                mode, config, default=profile_minutes,
                default_source="profile")
        return None, ask_search_travel_minutes(
            mode, config, default=current[1])
    while True:
        ui.section("Choose a travel limit")
        ui.item(1, "Distance in km")
        ui.item(2, "Journey time in minutes")
        default = "2" if current and current[1] is not None else "1"
        answer = read_input(f"Choose 1 or 2 [Enter = {default}]: ")
        if _cancelled(answer):
            return None, None
        choice = answer or default
        if choice == "1":
            defaults = dict(profile)
            if current and current[0] is not None:
                defaults["max_distance_km"] = current[0]
            distance = ask_search_distance(
                defaults, mode, config,
                default_source=("current search" if current and current[0] is not None
                                else "profile"))
            return distance, None
        if choice == "2":
            use_current = current and current[1] is not None
            minutes = ask_search_travel_minutes(
                mode, config,
                default=current[1] if use_current else profile_minutes,
                default_source="current search" if use_current else "profile")
            return None, minutes
        display_message("Choose 1 or 2, or press Enter for the default.")


def ask_drive_traffic(config=None):
    """Offer traffic-aware route durations only after a driving time choice."""
    while True:
        ui.section("Use live traffic for driving time?")
        ui.item(1, "No live traffic (default)")
        ui.item(2, "Use live traffic")
        answer = read_input("Choose 1 or 2 [Enter = 1] (/cancel): ")
        if _cancelled(answer):
            return None
        if answer in ("", "1"):
            return False
        if answer == "2":
            return True
        display_message("Choose 1 or 2, or press Enter for no live traffic.")


def ask_search_cuisine(profile, config=None, current_cuisine=None):
    liked = profile["liked_cuisines"] or []
    if liked:
        ui.section("Saved liked cuisines")
        for number, cuisine in enumerate(liked, 1):
            ui.item(number, cuisine.title())
    while True:
        hint = (f" [Enter = {current_cuisine}]"
                if current_cuisine else "")
        value = read_input(
            f"Choose one saved number, cuisine, or none{hint} (/cancel): ")
        if _cancelled(value):
            return None
        if not value and current_cuisine:
            return current_cuisine
        if value.isdigit() and 1 <= int(value) <= len(liked):
            return liked[int(value) - 1]
        cuisine = value.lower().strip()
        if cuisine == "none":
            return "none"
        if cuisine in CUISINES:
            return cuisine
        suggestions = []
        if config and not config.get("ai_bypass"):
            suggested = ai_manager.interpret_search_choice(
                cuisine, (*CUISINES, "none"), config)
            if suggested:
                suggestions = [suggested]
        if not suggestions:
            suggestions = logic_manager.cuisine_suggestions(cuisine)
        if len(suggestions) == 1:
            confirmed = ask_yes_no(
                f"Did you mean {suggestions[0].title()}?", config)
            if confirmed is None:
                return None
            if confirmed:
                return suggestions[0]
        display_message("Choose a saved number, supported cuisine, or none.")


def ask_search_budget(profile, config=None, default_source="profile"):
    default = profile["budget_per_person"]
    while True:
        value = read_input(
            f"Budget today in SGD [Enter = {default:g} "
            f"from {default_source}] "
            "(/cancel): "
        )
        if _cancelled(value):
            return None
        if not value:
            return default
        if re.fullmatch(r"\d+(?:\.\d{1,2})?", value):
            try:
                return validate_value("budget_per_person", float(value))
            except ValueError as error:
                display_message(error)
                continue
        if config and not config.get("ai_bypass"):
            try:
                suggested = ai_manager.interpret_search_number(
                    value, "budget_per_person", config)
                if suggested is not None:
                    suggested = validate_value("budget_per_person", suggested)
                    confirmed = ask_yes_no(
                        f"Use SGD {suggested:g} as today's budget?", config)
                    if confirmed is None:
                        return None
                    if confirmed:
                        return suggested
                    continue
            except (RuntimeError, ValueError) as error:
                display_message(error)
                continue
        display_message("Enter a positive SGD amount, such as 12 or 12.50.")


def ask_search_wishes(profile, config):
    """Preserve the CLI helper API through the IO-owned wish collector."""
    return manager().ask_search_wishes(profile, config)



def ask_search_clarification(config):
    """Collect a new description when BIS AI conflicts with a confirmed choice."""
    while True:
        value = read_input(
            "What are you looking for today? Describe any extra wishes "
            "(/cancel): "
        )
        if _cancelled(value):
            return None
        try:
            text = logic_manager.validate_special_request_text(value)
            try:
                reviewed = ai_manager.review_special_request(text, config)
            except RuntimeError:
                display_message(
                    "Could not check the wording. Please try again, "
                    "or enter /cancel.")
                continue
            if reviewed is None:
                display_message(
                    "I could not understand that request. Please rephrase it.")
                continue
            logic_manager.validate_special_request_text(reviewed)
            if reviewed != text:
                confirmed = ask_yes_no(
                    f"Use '{reviewed}' instead?", config)
                if confirmed is None:
                    return None
                if not confirmed:
                    continue
            return reviewed
        except ValueError as error:
            display_message(error)


def collect_search(user, config):
    """Collect one search request without changing the saved user profile."""
    return manager().collect_search(user, config)


def choose_results_action(result_count, alternatives_hidden=False):
    """Let the user keep exploring or adjust today's search."""
    actions = []
    if alternatives_hidden:
        actions.append(("alternatives", "Show other restaurants"))
    if result_count:
        actions.extend((("route", "Show a route"),
                        ("email", "Email a Google Maps link"),
                        ("more", "Show full restaurant details"),
                        ("sort", "Sort results by rating or distance")))
    actions.extend((("again", "Change travel limit, budget, cuisine, or other preferences"),
                    ("repeat", "Search again with the same choices"),
                    ("done", "Finish and return to commands")))
    while True:
        ui.section("What would you like to do?")
        for number, (_, label) in enumerate(actions, 1):
            ui.item(number, label)
        ui.line("  Press Enter without typing to finish.")
        answer = read_input("Choose a number, or press Enter to finish: ")
        if answer is None or not answer.strip():
            return "done"
        answer = answer.lower().strip()
        if answer in {"/cancel", "/quit", "/exit", "enter"}:
            return "done"
        if answer.isdigit() and 1 <= int(answer) <= len(actions):
            return actions[int(answer) - 1][0]
        if answer in {name for name, _ in actions}:
            return answer
        display_message("Choose one of the numbers shown, or press Enter.")


def choose_result_sort():
    """Choose how BRNS should reorder the displayed search results."""
    choices = (
        ("rating", "Google rating (highest first)"),
        ("distance", "Travel distance (nearest first)"),
    )
    while True:
        ui.section("Sort results")
        for number, (_, label) in enumerate(choices, 1):
            ui.item(number, label)
        ui.line("  Press Enter without typing to keep the current order.")
        answer = read_input(
            "Choose a number, or press Enter to keep the current order: ")
        if answer is None or not answer.strip():
            return None
        answer = answer.lower().strip()
        if answer in {"/cancel", "/quit", "/exit"}:
            return None
        aliases = {
            "1": "rating", "rating": "rating", "ratings": "rating",
            "google rating": "rating",
            "2": "distance", "distance": "distance", "nearest": "distance",
        }
        if answer in aliases:
            return aliases[answer]
        display_message("Choose 1 for rating, 2 for distance, or press Enter.")


def choose_route_result(result_count):
    """Ask which numbered restaurant to use for a route or email."""
    while True:
        answer = read_input(
            f"Result number (1–{result_count}), or press Enter to go back: ")
        if answer is None or not answer.strip():
            return None
        answer = answer.strip().lower()
        if answer in {"/cancel", "/quit", "/exit"}:
            return None
        if answer.isdigit() and 1 <= int(answer) <= result_count:
            return int(answer)
        display_message(f"Choose a result number from 1 to {result_count}.")


def refine_search_request(request, profile, config):
    """Change one confirmed search choice without repeating every prompt."""
    travel_choice = "time" if request["mode"] == "transit" else "travel"
    choices = (
        (travel_choice, "Change journey time" if travel_choice == "time"
         else "Change travel limit"),
        ("budget", "Change budget"),
        ("cuisine", "Change specific cuisine"),
        ("other preferences", "Change other preferences"),
    )
    while True:
        ui.section("Change today's search")
        for number, (_, label) in enumerate(choices, 1):
            ui.item(number, label)
        ui.line("  Press Enter without typing to return to the results.")
        choice = read_input(
            "Choose a number or option, or press Enter for results: ")
        if _cancelled(choice) or not choice:
            return None
        choice = choice.lower().strip()
        aliases = {
            "1": travel_choice, travel_choice: travel_choice,
            "travel": travel_choice, "time": travel_choice,
            "2": "budget", "budget": "budget",
            "3": "cuisine", "cuisine": "cuisine",
            "4": "other preferences", "other": "other preferences",
            "other preference": "other preferences",
            "other preferences": "other preferences",
            "other_preferences": "other preferences",
            "preferences": "other preferences", "wishes": "other preferences",
            "extra": "other preferences",
            "change other preference": "other preferences",
            "change other preferences": "other preferences",
            "change preferences": "other preferences",
        }
        normalized_choice = aliases.get(choice)
        if normalized_choice is None and not config.get("ai_bypass"):
            suggested = ai_manager.interpret_search_choice(
                choice, tuple(name for name, _ in choices), config)
            if suggested:
                confirmed = ask_yes_no(f"Did you mean {suggested}?", config)
                if confirmed is None:
                    return None
                if confirmed:
                    normalized_choice = suggested
        if normalized_choice is None:
            display_message(
                "Choose one of the numbers shown, or press Enter for results.")
            continue
        choice = normalized_choice
        defaults = dict(profile)
        if request["max_distance_km"] is not None:
            defaults["max_distance_km"] = request["max_distance_km"]
        defaults["budget_per_person"] = request["budget_per_person"]
        if choice == travel_choice:
            distance, minutes = ask_search_limit(
                defaults, request["mode"], config,
                current=(request["max_distance_km"], request["max_travel_minutes"]))
            if distance is None and minutes is None:
                return None
            traffic_aware = (ask_drive_traffic(config) if request["mode"] == "drive"
                             and minutes is not None else False)
            if traffic_aware is None:
                return None
            return dict(request, max_distance_km=distance,
                        max_travel_minutes=minutes, traffic_aware=traffic_aware)
        elif choice == "budget":
            value = ask_search_budget(
                defaults, config, default_source="current search")
            field = "budget_per_person"
        elif choice == "cuisine":
            value = ask_search_cuisine(
                profile, config, current_cuisine=request["cuisine"])
            field = "cuisine"
        elif choice == "other preferences":
            defaults[OTHER_PREFERENCES] = list(dict.fromkeys(
                (profile.get(OTHER_PREFERENCES) or [])
                + (request.get(OTHER_PREFERENCES) or [])
            ))
            wishes = ask_search_wishes(defaults, config)
            if wishes is None:
                return None
            other = wishes["selected"]
            if wishes["text"]:
                other = validate_value(
                    OTHER_PREFERENCES, other + [wishes["text"]])
            field = OTHER_PREFERENCES
            value = other
        if value is None:
            return None
        refined = dict(request, **{field: value})
        if field == "cuisine":
            refined["disliked_cuisines"] = [
                item for item in request["disliked_cuisines"]
                if item != value]
        return refined


def _capitalize_display_text(value):
    """Capitalize display text without changing saved search values."""
    return value[:1].upper() + value[1:]


def display_search_summary(request):
    ui.section("Today's search")
    ui.field("From", _capitalize_display_text(request['origin']['label']))
    if request["max_travel_minutes"] is not None:
        traffic = (" (live traffic)" if request["traffic_aware"] else
                   " (regular route time)" if request["mode"] == "drive" else "")
        ui.field("Travel", f"{_capitalize_display_text(request['mode'])} "
                 f"up to {request['max_travel_minutes']:g} min{traffic}")
    else:
        ui.field("Travel", f"{_capitalize_display_text(request['mode'])} "
                 f"up to {request['max_distance_km']} km")
    ui.field("Specific cuisine today",
             _capitalize_display_text(request['cuisine']))
    ui.field("Budget", f"SGD {request['budget_per_person']}")
    dietary = request["dietary_requirements"]
    restrictions = [label for key, label in (
        ("halal", "Halal"), ("vegetarian", "Vegetarian"))
        if key in dietary]
    ui.field("Dietary Restrictions", ", ".join(restrictions) or "None")
    ui.field("Disliked cuisines",
             ", ".join(_capitalize_display_text(item)
                       for item in request["disliked_cuisines"]) or "None")
    ui.field("Other preferences",
             ", ".join(_capitalize_display_text(item)
                       for item in request[OTHER_PREFERENCES]) or "None")


def confirm_search_request(request, config=None):
    """Require explicit approval of the interpreted live search."""
    display_search_summary(request)
    return ask_yes_no("Search with these choices?", config, default=True)


def resolve_cuisine_token(token, field, config=None):
    """Return a confirmed cuisine or explicitly accepted extra preference."""
    if token in CUISINES:
        return token, None
    candidates = logic_manager.cuisine_suggestions(token)
    if len(candidates) == 1:
        confirmed = ask_yes_no(
            f"Did you mean {candidates[0].title()}?", config)
        if confirmed is not True:
            raise ValueError("No changes saved. Please clarify the cuisine.")
        return candidates[0], None
    if candidates:
        ui.message("Possible matches: " + ", ".join(candidates), "warning")
        selected = read_input("Choose a cuisine by name, or /cancel: ")
        if selected is None or selected.lower() not in candidates:
            raise ValueError("No changes saved. Please clarify the cuisine.")
        return selected.lower(), None
    if token not in logic_manager.UNSUPPORTED_CUISINES:
        raise ValueError(
            "Unrecognized cuisine. Choose from: " + ", ".join(CUISINES))
    display_message(f"{token.title()} is outside the supported cuisine list.")
    confirmed = ask_yes_no(
        "Include it in your other preferences instead?", config)
    if confirmed is not True:
        raise ValueError("Choose another cuisine, or none.")
    prefix = {"liked_cuisines": "Likes ",
              "disliked_cuisines": "Avoids "}[field]
    return None, prefix + token


def resolve_cuisines(text, field, preferences, config=None):
    """Resolve the whole answer before returning any proposed update."""
    tokens = logic_manager.cuisine_tokens(text, field)
    resolved = []
    extras = []
    for token in tokens:
        cuisine, extra = resolve_cuisine_token(token, field, config)
        if cuisine is not None:
            resolved.append(cuisine)
        if extra is not None:
            extras.append(extra)
    updates = {}
    if resolved or not tokens:
        updates[field] = list(dict.fromkeys(resolved))
    if extras:
        existing = preferences[OTHER_PREFERENCES] or []
        updates[OTHER_PREFERENCES] = list(dict.fromkeys(existing + extras))
    return validate_updates(updates)


def confirm_ai_updates(updates):
    """Require approval before using AI-interpreted cuisines or extra text."""
    for field in CUISINE_FIELDS + (OTHER_PREFERENCES,):
        if field not in updates:
            continue
        value = updates[field]
        text = ", ".join(value) if isinstance(value, list) else value
        confirmed = ask_yes_no(
            f"Save {LABELS[field].lower()} as {text or 'none'}?")
        if confirmed is not True:
            raise ValueError("No changes saved. Please clarify your answer.")


def confirm_location_update(locations, operation):
    """Show the exact parsed area list before it changes the profile."""
    labels = ", ".join(location[:1].upper() + location[1:]
                       for location in locations)
    questions = {
        "add": f"Add these locations: {labels}?",
        "replace": f"Replace saved locations with: {labels}?",
        "remove": f"Remove these locations: {labels}?",
    }
    if operation not in questions:
        raise ValueError("Choose add, replace, or remove for locations.")
    if ask_yes_no(questions[operation]) is not True:
        raise ValueError("No locations were saved. Please clarify your answer.")


def resolve_cuisine_conflict(cuisine, preferences, updates):
    choice = read_input(
        f"{cuisine.title()} is both liked and disliked. "
        "Keep in likes or dislikes? "
    )
    if choice is None or choice.lower() not in {"likes", "dislikes"}:
        raise ValueError("No changes saved. Choose likes or dislikes.")
    keep, remove = {
        "likes": ("liked_cuisines", "disliked_cuisines"),
        "dislikes": ("disliked_cuisines", "liked_cuisines"),
    }[choice.lower()]
    keep_values = list(updates.get(keep, preferences[keep]) or [])
    if cuisine not in keep_values:
        keep_values.append(cuisine)
    updates[keep] = keep_values
    previous = updates.get(remove, preferences[remove]) or []
    updates[remove] = [value for value in previous if value != cuisine]


def resolve_proposed_updates(preferences, updates, from_ai=False,
                             location_action="add"):
    """Confirm interpretations and conflicts before returning updates."""
    updates = validate_updates(updates)
    if "location" in updates:
        confirm_location_update(updates["location"], location_action)
    if from_ai:
        confirm_ai_updates(updates)
    for cuisine in logic_manager.cuisine_conflicts(preferences, updates):
        resolve_cuisine_conflict(cuisine, preferences, updates)
    return validate_updates(updates)


def command_action(text):
    lowered = " ".join(text.lower().split())
    if lowered == "/edit":
        return {"action": "edit_menu"}
    if lowered.startswith("/help "):
        return {"action": "help", "topic": lowered[6:].lstrip("/")}
    if lowered in COMMANDS:
        return {"action": COMMANDS[lowered]}
    operations = {"/add-location": "add", "/remove-location": "remove"}
    if lowered in operations:
        return {"action": "edit", "field": "location",
                "location_action": operations[lowered]}
    if lowered.startswith("/edit "):
        target = lowered[6:].strip()
        target = EDIT_ALIASES.get(target, target)
        if target not in PREFERENCE_FIELDS + ("username", "password"):
            raise ValueError(
                "Unknown field. Try /edit budget, "
                "or /help edit for all options."
            )
        if target == "username":
            return {"action": "rename", "field": target, "location_action": "replace"}
        if target == "password":
            return {"action": "change_password"}
        return {"action": "edit", "field": target, "location_action": "replace"}
    if text.startswith("/"):
        raise ValueError("Unknown command. Use /help.")
    return None


def _interpreted_command_action(command, field=None):
    """Translate a validated command label into the normal BIS action."""
    if command == "profile":
        return {"action": "show_profile"}
    if command == "search":
        return {"action": "search"}
    if command == "help":
        return {"action": "help"}
    if command == "reset":
        return {"action": "reset_profile"}
    if command == "logout":
        return {"action": "logout"}
    if command == "change_password":
        return {"action": "change_password"}
    if command == "quit":
        return {"action": "exit"}
    if command in {"color_on", "color_off"}:
        return {"action": "color", "enabled": command == "color_on"}
    if command in {"add_location", "remove_location"}:
        return {"action": "edit", "field": "location",
                "location_action": (
                    "add" if command == "add_location" else "remove")}
    if command == "edit":
        if field is None:
            return {"action": "edit_menu"}
        if field == "username":
            return {"action": "rename"}
        if field == "password":
            return {"action": "change_password"}
        return {"action": "edit", "field": field,
                "location_action": "replace"}
    return None


def natural_command_action(text, config, *, allow_ai=False):
    """Recognize clear slashless commands, then optionally ask BIS AI."""
    lowered = " ".join(text.casefold().strip().rstrip(".!?").split())
    local = None
    if re.fullmatch(
            r"(?:(?:please|can you) )?(?:turn |switch )?"
            r"(?:the )?colou?rs? off", lowered) or lowered in {
                "color off", "disable color", "disable colors",
                "disable colour", "disable colours"}:
        local = ("color_off", None)
    elif re.fullmatch(
            r"(?:(?:please|can you) )?(?:turn |switch )?"
            r"(?:the )?colou?rs? on", lowered) or lowered in {
                "color on", "enable color", "enable colors",
                "enable colour", "enable colours"}:
        local = ("color_on", None)
    elif re.search(
            r"\b(?:search|find|recommend|look for)\b.*"
            r"\b(?:restaurant|restaurants|food|place to eat)\b", lowered):
        local = ("search", None)
    elif re.fullmatch(
            r"(?:i want to |let me )?(?:change|update|edit) "
            r"(?:my )?profile", lowered):
        local = ("edit", None)
    elif (lowered in {"profile", "my profile", "show profile",
                      "show my profile", "view profile", "view my profile"}
          or re.fullmatch(
              r"(?:i want to |let me )?(?:view|show|open) "
              r"(?:my )?profile", lowered)):
        local = ("profile", None)
    elif lowered in {"help", "show help", "what can i do",
                     "show commands", "list commands"}:
        local = ("help", None)
    elif lowered in {"logout", "log out", "sign out"}:
        local = ("logout", None)
    elif re.fullmatch(
            r"(?:change|update|edit) (?:my )?password", lowered):
        local = ("change_password", None)
    elif lowered in {"quit", "exit", "close bitefinder", "goodbye"}:
        local = ("quit", None)
    elif re.fullmatch(
            r"(?:reset|clear|erase) (?:my )?(?:profile|preferences)",
            lowered):
        local = ("reset", None)
    elif re.fullmatch(r"(?:add|save) (?:a |new )?location", lowered):
        local = ("add_location", None)
    elif re.fullmatch(r"(?:remove|delete) (?:a |saved )?location", lowered):
        local = ("remove_location", None)
    else:
        edit = re.fullmatch(
            r"(?:change|update|edit)(?: my)? "
            r"(budget|travel|travel time|diet|likes|dislikes|"
            r"other preferences|username|location)", lowered)
        if edit:
            aliases = {
                "budget": "budget_per_person",
                "travel": "max_distance_km",
                "travel time": "max_travel_time_minutes",
                "diet": "dietary_requirements",
                "likes": "liked_cuisines",
                "dislikes": "disliked_cuisines",
                "other preferences": OTHER_PREFERENCES,
            }
            local = ("edit", aliases.get(edit.group(1), edit.group(1)))
    if local:
        return _interpreted_command_action(*local)
    if not allow_ai or config.get("ai_bypass") or not lowered:
        return None
    try:
        interpreted = ai_manager.interpret_command(text, config)
    except (RuntimeError, ValueError):
        return None
    return _interpreted_command_action(
        interpreted["command"], interpreted["field"])


def choose_profile_edit():
    """Let the user choose one profile field to replace."""
    choices = (
        ("username", "Username"),
        ("location", "Saved locations"),
        ("max_distance_km", "Travel distance or journey time"),
        ("budget_per_person", "Budget per person"),
        ("dietary_requirements", "Dietary restrictions"),
        ("liked_cuisines", "Liked cuisines"),
        ("disliked_cuisines", "Disliked cuisines"),
        (OTHER_PREFERENCES, "Other preferences"),
        ("password", "Password"),
    )
    while True:
        ui.section("Edit profile")
        for number, (_, label) in enumerate(choices, 1):
            ui.item(number, label)
        ui.line("  Press Enter without typing to cancel.")
        answer = read_input(
            "Choose what to change, or press Enter to cancel: ")
        if answer is None or not answer.strip() or _cancelled(answer):
            return None
        answer = answer.lower().strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            field = choices[int(answer) - 1][0]
            if field == "username":
                return {"action": "rename"}
            if field == "password":
                return {"action": "change_password"}
            return {"action": "edit", "field": field,
                    "location_action": "replace"}
        display_message("Choose one of the numbers shown, or press Enter.")


def interpretation_action(preferences, field, text):
    return {"action": "interpret", "record": {
        "preferences": preferences, "field": field, "text": text,
    }}


def ask_profile_travel_unit(amount):
    """Resolve a bare profile travel number without guessing its unit."""
    while True:
        ui.section(f"What unit did you mean for {amount}?")
        ui.item(1, "Kilometres")
        ui.item(2, "Minutes")
        choice = read_input("Choose 1 for km or 2 for minutes (/cancel): ")
        if _cancelled(choice):
            raise ValueError("No travel preference was saved.")
        if choice == "1":
            return f"{amount} km"
        if choice == "2":
            return f"{amount} mins"
        display_message("Choose 1 or 2, or /cancel.")


def _declared_travel_unit(text):
    """Read only units explicitly present in the original user answer."""
    lowered = text.lower()
    distance = bool(re.search(
        r"\b(?:km|kilomet(?:er|re)s?|met(?:er|re)s?)\b", lowered))
    minutes = bool(re.search(
        r"\b(?:mins?|minutes?|hours?|hrs?)\b", lowered))
    if distance and minutes:
        raise ValueError("Use one travel unit: km or minutes.")
    return "km" if distance else "minutes" if minutes else None


def _profile_travel_action(text, field, config, location_action):
    declared_unit = _declared_travel_unit(text)
    if re.fullmatch(r"\d+(?:\.\d{1,2})?", text):
        resolved = ask_profile_travel_unit(text)
    elif config.get("ai_bypass"):
        resolved = text
    else:
        try:
            updates = logic_manager.parse_local_answer(text, field)
        except ValueError:
            interpreted = ai_manager.interpret_profile_travel(text, config)
            amount = interpreted["value"]
            if amount is None:
                raise ValueError(
                    "Enter one travel amount, such as 10 km or ten minutes.")
            if declared_unit and interpreted["unit"] != declared_unit:
                raise ValueError("Could not confirm the travel unit. Please retry.")
            resolved = (f"{amount:g} {declared_unit}" if declared_unit else
                        ask_profile_travel_unit(f"{amount:g}"))
            updates = logic_manager.parse_local_answer(resolved, field)
            if ask_yes_no(f"Use {resolved} for your travel preference?", config) is not True:
                raise ValueError("No travel preference was saved.")
        else:
            return {"action": "profile_update", "updates": updates,
                    "location_action": location_action}
        return {"action": "profile_update", "updates": updates,
                "location_action": location_action}
    return {"action": "profile_update",
            "updates": logic_manager.parse_local_answer(resolved, field),
            "location_action": location_action}


def collect_action(user, config, field=None, location_action="add"):
    """Collect and review a typed action without persisting it."""
    return manager().collect_action(
        user, config, field, location_action)
