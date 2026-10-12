"""All terminal input/output for BiteFinder profiles and search setup."""

import re
import sys
import time

from sources.prompts import (
    COMMANDS, COMMAND_HELP, EDIT_ALIASES, EDIT_HINT, HELP_TEXT, LABELS,
    QUESTIONS,
)

import data_manager
import ai_manager
from support.email_verification import challenge as email_challenge
from support.email_verification import service as email_service
import logic_manager
from shared import terminal_ui as ui
from sources.profile_schema import (
    CUISINES, CUISINE_FIELDS, OTHER_PREFERENCES, PREFERENCE_FIELDS,
    clean_text, normalize_email, normalize_username, validate_updates,
    validate_value, validate_travel_minutes,
)

_color_handler = None


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
        raise ValueError("This email is already registered. Choose resume.")
    username = prompt_username()
    if username is None:
        return None
    user = data_manager.register_user(email, username)
    display_message("Signed up. Resume this account using your email.")
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


def select_user(config):
    while True:
        ui.section("Welcome to BiteFinder")
        ui.item(1, "Sign up")
        ui.item(2, "Resume by email")
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
            cached = data_manager.lookup_cached_location(raw)
            query = raw
            if not cached and not logic_manager.is_direct_location_input(raw):
                try:
                    query = ai_manager.interpret_location(raw, config)
                except RuntimeError:
                    # Google can geocode the original landmark when the AI is unavailable.
                    query = raw
            location = data_manager.resolve_location(
                query, config.get("google_maps_api_key", ""))
            data_manager.remember_location((raw, query), location)
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
    """Select earlier wishes or collect one new request for today's search."""
    saved = profile[OTHER_PREFERENCES] or []
    if saved:
        ui.section("Previous special requests")
        for number, item in enumerate(saved, 1):
            ui.item(number, item)
    while True:
        value = read_input(
            "What are you looking for today?\n"
            "Describe any extra wishes, such as 'spicy', 'minimum 4.5 "
            "stars', or 'only Korean'.\n"
            "Use 'minimum', 'at least', or 'only' for a hard requirement "
            "(this may give no matches).\n"
            "[Press Enter = none; all = every saved request; saved numbers; "
            "or new text] (/cancel): "
        )
        if _cancelled(value):
            return None
        if not value or value.lower() == "none":
            return {"selected": [], "text": ""}
        if value.lower() == "all":
            return {"selected": list(saved), "text": ""}
        if re.fullmatch(r"\d+(?:\s*,\s*\d+)*", value):
            numbers = [int(part.strip()) for part in value.split(",")]
            if saved and all(1 <= number <= len(saved) for number in numbers):
                selected = list(dict.fromkeys(
                    saved[number - 1] for number in numbers))
                return {"selected": selected, "text": ""}
            display_message("Choose numbers shown in the previous requests list.")
            continue
        try:
            text = logic_manager.validate_special_request_text(value)
            if not config.get("ai_bypass"):
                try:
                    reviewed = ai_manager.review_special_request(text, config)
                except RuntimeError:
                    display_message(
                        "Could not check the wording. Please try again, "
                        "or press Enter for none.")
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
                    text = reviewed
                if saved:
                    try:
                        equivalent = ai_manager.equivalent_saved_request(
                            text, saved, config)
                    except RuntimeError:
                        display_message(
                            "Could not compare this with your saved requests. "
                            "Please try again.")
                        continue
                    if equivalent is not None:
                        display_message(
                            f"This matches your saved request '{equivalent}'. "
                            "Using the first saved version.")
                        return {"selected": [equivalent], "text": ""}
                if re.search(
                        r"\b(?:only|must|required|minimum|at least|"
                        r"no less than|exclusively|[1-5](?:\.\d+)?\s*"
                        r"(?:stars?|/\s*5))\b", text, re.IGNORECASE):
                    try:
                        constraints = ai_manager.classify_search_constraints(
                            text, config)
                    except RuntimeError:
                        display_message(
                            "Could not check whether this is a hard "
                            "requirement. Please try again.")
                        continue
                    hard_confirmed = False
                    rating = constraints["rating"]
                    if rating is not None and not constraints[
                            "rating_is_minimum"]:
                        hard_confirmed = ask_yes_no(
                            f"Make {rating:g} stars a hard minimum? "
                            "This may return no matching restaurants.", config)
                        if hard_confirmed is None:
                            return None
                        if hard_confirmed:
                            constraints["hard_requirement"] = True
                            constraints["rating_is_minimum"] = True
                    if constraints["hard_requirement"] and not hard_confirmed:
                        confirmed = ask_yes_no(
                            "Treat this as a hard requirement? Budget and "
                            "travel limits will become secondary, and there "
                            "may be no matching restaurants.", config)
                        if confirmed is None:
                            return None
                        if not confirmed:
                            continue
                    if constraints["hard_requirement"]:
                        additions = []
                        cuisine = constraints["hard_cuisine"]
                        if cuisine and not (
                                re.search(
                                    rf"\bonly\s+{re.escape(cuisine)}\b",
                                    text, re.IGNORECASE)
                                or re.search(
                                    rf"\b{re.escape(cuisine)}\s+only\b",
                                    text, re.IGNORECASE)
                                or re.search(
                                    rf"\b(?:must be|exclusively)\s+"
                                    rf"{re.escape(cuisine)}\b",
                                    text, re.IGNORECASE)):
                            additions.append(f"only {cuisine} cuisine")
                        if (constraints["rating_is_minimum"]
                                and not re.search(
                                    r"\b(?:minimum|at least|no less than)\b",
                                    text, re.IGNORECASE)):
                            additions.append(f"at least {rating:g} stars")
                        if (not additions and not cuisine
                                and not constraints["rating_is_minimum"]
                                and not re.search(
                                    r"\b(?:only|must|required|minimum|"
                                    r"at least|no less than|exclusively)\b",
                                    text, re.IGNORECASE)):
                            additions.append("hard requirement")
                        for addition in additions:
                            if (addition not in text.casefold()
                                    and len(text) + len(addition) + 2 <= 100):
                                text += ", " + addition
            return {"selected": [], "text": text}
        except ValueError as error:
            display_message(error)


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
    profile = user["preferences"]
    location = ask_search_location(config)
    if location is None:
        return None
    mode = ask_search_mode(config)
    if mode is None:
        return None
    distance, minutes = ask_search_limit(profile, mode, config)
    if distance is None and minutes is None:
        return None
    traffic_aware = ask_drive_traffic(config) if mode == "drive" and minutes is not None else False
    if traffic_aware is None:
        return None
    cuisine = ask_search_cuisine(profile, config)
    if cuisine is None:
        return None
    save_cuisine = False
    if cuisine != "none" and cuisine not in (profile["liked_cuisines"] or []):
        disliked = cuisine in (profile["disliked_cuisines"] or [])
        question = (f"Add {cuisine.title()} to your saved liked cuisines"
                    + (" and remove it from disliked cuisines?" if disliked
                       else "?"))
        save_cuisine = ask_yes_no(question, config)
        if save_cuisine is None:
            return None
    budget = ask_search_budget(profile, config)
    if budget is None:
        return None
    wishes = ask_search_wishes(profile, config)
    if wishes is None:
        return None
    other = wishes["selected"]
    if config.get("ai_bypass") and wishes["text"]:
        other = validate_value(OTHER_PREFERENCES, other + [wishes["text"]])
    request = {
        "origin": location, "mode": mode, "max_distance_km": distance,
        "max_travel_minutes": minutes, "traffic_aware": traffic_aware,
        "cuisine": cuisine, "budget_per_person": budget,
        OTHER_PREFERENCES: other,
        "dietary_requirements": list(profile["dietary_requirements"] or []),
        "disliked_cuisines": [item for item in
                              (profile["disliked_cuisines"] or [])
                              if item != cuisine],
    }
    return {"request": request, "today_request": wishes["text"],
            "save_cuisine": cuisine if save_cuisine else None}


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
        if target not in PREFERENCE_FIELDS + ("username",):
            raise ValueError(
                "Unknown field. Try /edit budget, "
                "or /help edit for all options."
            )
        return {"action": "rename" if target == "username" else "edit",
                "field": target, "location_action": "replace"}
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
    preferences = user["preferences"]
    field = field or logic_manager.next_field(preferences)
    if field is not None:
        display_message(QUESTIONS[field])
    text = read_input()
    if text is None:
        return {"action": "exit"}
    command = command_action(text)
    if command is not None:
        return command
    natural_command = natural_command_action(
        text, config, allow_ai=field is None)
    if natural_command is not None:
        return natural_command
    if field == OTHER_PREFERENCES and not text.strip():
        return {"action": "profile_update",
                "updates": {OTHER_PREFERENCES: []},
                "location_action": location_action}
    text = clean_text(text, 1000)
    if field in {"max_distance_km", "max_travel_time_minutes"}:
        return _profile_travel_action(text, field, config, location_action)
    if (field is not None and field not in {
            "max_distance_km", "max_travel_time_minutes", "budget_per_person"}
            and text.lower() not in {"none", "both"}
            and not config.get("ai_bypass")):
        reviewed = ai_manager.review_prompt_text(
            text, config, QUESTIONS[field], 1000)
        if reviewed is None:
            raise ValueError("Please rephrase your answer in English.")
        if reviewed != text:
            if ask_yes_no(f"Use '{reviewed}' instead?", config) is not True:
                raise ValueError("No changes saved. Please re-enter your answer.")
            text = reviewed
    if field in CUISINE_FIELDS:
        if not config.get("ai_bypass") and text.lower() not in {
            "none", "no preference", "no preferences",
        }:
            return interpretation_action(preferences, field, text)
        updates = resolve_cuisines(text, field, preferences, config)
        return {"action": "profile_update", "updates": updates,
                "location_action": location_action}
    if field == OTHER_PREFERENCES:
        updates = logic_manager.parse_local_answer(text, field)
        return {"action": "profile_update", "updates": updates,
                "location_action": location_action}
    if not config.get("ai_bypass"):
        return interpretation_action(preferences, field, text)
    if field is None:
        raise ValueError("Use /edit to change a completed profile.")
    updates = logic_manager.parse_local_answer(text, field)
    return {"action": "profile_update", "updates": updates,
            "location_action": location_action}
