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
    validate_value,
)

_color_handler = None


def set_color_handler(handler):
    """Bind the current account's persisted color command to all prompts."""
    global _color_handler
    _color_handler = handler


def display_message(message, role="body"):
    ui.message(message, "error" if isinstance(message, Exception) else role)


def display_debug(message):
    print(message, file=sys.stderr)


def read_input(prompt="You: "):
    while True:
        try:
            value = ui.read_input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        lowered = " ".join(value.lower().split())
        if lowered == "/help":
            display_help()
            continue
        if lowered.startswith("/help "):
            display_help(lowered[6:].lstrip("/"))
            continue
        if lowered in {"/color off", "/color on"}:
            if _color_handler is None:
                display_message("Sign in before changing your color setting.")
            else:
                _color_handler(lowered == "/color on")
            continue
        if lowered == "/color" or lowered.startswith("/color "):
            display_help("color")
            continue
        return value


def ask_yes_no(question, config=None):
    """None cancels the pending update; an empty answer is never approval."""
    while True:
        value = read_input(question + " (yes/no): ")
        if value is None or value.lower() in {"/quit", "/exit", "/cancel"}:
            return None
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
        value = read_input("Travel by walking or driving? (walk/drive, /cancel): ")
        if _cancelled(value):
            return None
        mode = value.lower()
        if mode in {"walk", "walking"}:
            return "walk"
        if mode in {"drive", "driving"}:
            return "drive"
        if config and value and not value.startswith("/"):
            suggested = ai_manager.interpret_search_choice(
                value, ("walk", "drive"), config)
            if suggested:
                confirmed = ask_yes_no(f"Did you mean {suggested}?", config)
                if confirmed is None:
                    return None
                if confirmed:
                    return suggested
                continue
        display_message("Choose walk or drive.")


def ask_search_distance(profile, mode, config=None):
    default = profile["max_distance_km"] if mode == "walk" else None
    while True:
        hint = f" [Enter = {default:g} km from profile]" if default else ""
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


def ask_search_cuisine(profile, config=None):
    liked = profile["liked_cuisines"] or []
    if liked:
        ui.section("Saved liked cuisines")
        for number, cuisine in enumerate(liked, 1):
            ui.item(number, cuisine.title())
    while True:
        value = read_input(
            "Choose one saved number, cuisine, or none (/cancel): "
        )
        if _cancelled(value):
            return None
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


def ask_search_budget(profile, config=None):
    default = profile["budget_per_person"]
    while True:
        value = read_input(
            f"Budget today in SGD [Enter = {default:g} from profile] "
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
            "What are you looking for today? Describe any extra wishes "
            "[Enter = none; all, saved numbers, or new text] (/cancel): "
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
    distance = ask_search_distance(profile, mode, config)
    if distance is None:
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
        "cuisine": cuisine, "budget_per_person": budget,
        OTHER_PREFERENCES: other,
        "dietary_requirements": list(profile["dietary_requirements"] or []),
        "disliked_cuisines": [item for item in
                              (profile["disliked_cuisines"] or [])
                              if item != cuisine],
    }
    return {"request": request, "today_request": wishes["text"],
            "save_cuisine": cuisine if save_cuisine else None}


def display_search_summary(request):
    ui.section("Today's search")
    ui.field("From", request['origin']['label'])
    ui.field("Travel", f"{request['mode']} up to {request['max_distance_km']} km")
    ui.field("Cuisine", request['cuisine'])
    ui.field("Budget", f"SGD {request['budget_per_person']}")
    ui.field("Other preferences",
             ', '.join(request[OTHER_PREFERENCES]) or 'none')


def confirm_search_request(request, config=None):
    """Require explicit approval of the interpreted live search."""
    display_search_summary(request)
    return ask_yes_no("Search with these choices?", config)


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


def resolve_proposed_updates(preferences, updates, from_ai=False):
    """Confirm interpretations and conflicts before returning updates."""
    updates = validate_updates(updates)
    if from_ai:
        confirm_ai_updates(updates)
    for cuisine in logic_manager.cuisine_conflicts(preferences, updates):
        resolve_cuisine_conflict(cuisine, preferences, updates)
    return validate_updates(updates)


def command_action(text):
    lowered = " ".join(text.lower().split())
    if lowered == "/edit":
        return {"action": "help", "topic": "edit_hint"}
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


def interpretation_action(preferences, field, text):
    return {"action": "interpret", "record": {
        "preferences": preferences, "field": field, "text": text,
    }}


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
    text = clean_text(text, 1000)
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
        if not config.get("ai_bypass") and (
            logic_manager.needs_cuisine_interpretation(text, field)
        ):
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
