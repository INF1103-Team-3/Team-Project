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
from support import email_delivery
import logic_manager
from support.debug_log import debug_log
from sources.profile_schema import (
    CUISINES, CUISINE_FIELDS, OTHER_PREFERENCES, PREFERENCE_FIELDS,
    clean_text, normalize_email, normalize_username, validate_updates,
    validate_value,
)


def display_message(message):
    print(f"BiteFinder: {message}")


def display_debug(message):
    print(message, file=sys.stderr)


def read_input(prompt="You: "):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def ask_yes_no(question):
    """None cancels the pending update; an empty answer is never approval."""
    while True:
        value = read_input(question + " (yes/no): ")
        if value is None or value.lower() in {"/quit", "/exit", "/cancel"}:
            return None
        if value.lower() in {"yes", "y"}:
            return True
        if value.lower() in {"no", "n"}:
            return False
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
    print(f"Username: {user['username'] or 'Not answered'}")
    for field in PREFERENCE_FIELDS:
        rendered = format_preference_value(field, user["preferences"][field])
        print(f"{LABELS[field]}: {rendered}")
    if user["preferences"]["max_distance_km"] is not None:
        print("Conversions are approximate: 1 km ≈ 20 minutes on foot.")


def display_help(topic=None):
    """Show brief command help or detailed editing instructions."""
    if topic is None:
        print(HELP_TEXT)
        return
    if topic == "edit_hint":
        print(EDIT_HINT)
        return
    print(COMMAND_HELP.get(
        topic, "Unknown help topic. Type /help to see available commands.",
    ))


def display_welcome(user):
    """Keep startup brief; detailed commands are available on request."""
    display_message(f"Hi {user['username']}! Let's set up your preferences.")
    display_message("Type /help for commands.")


def get_verification(user_id):
    challenge = data_manager.get_state("verification", user_id)
    if challenge:
        logic_manager.validate_challenge(challenge)
    return challenge


def request_verification(user, config):
    code, challenge = logic_manager.new_challenge(
        get_verification(user["userID"]))
    email_delivery.send_verification_email(user["email"], code, config)
    data_manager.set_state("verification", user["userID"], challenge)
    display_message("A verification code was emailed to you.")


def verify_email_interactively(user, config):
    if user["email_verified"] or config.get("smtp_bypass"):
        if not user["email_verified"]:
            display_message("SMTP verification bypass is enabled for testing.")
        return user
    user_id = user["userID"]
    challenge = get_verification(user_id)
    needs_code = (
        not challenge or time.time() >= challenge["expires_at"]
        or challenge["attempts"] >= logic_manager.VERIFICATION_MAX_ATTEMPTS
    )
    if needs_code:
        try:
            request_verification(user, config)
        except (ValueError, RuntimeError) as error:
            display_message(error)
    while True:
        code = read_input("Verification code (/resend or /quit): ")
        if code is None or code.lower() in {"/quit", "/exit"}:
            return None
        try:
            if code.lower() == "/resend":
                request_verification(user, config)
                continue
            updated, error = logic_manager.check_challenge(
                get_verification(user_id), code)
            if updated:
                data_manager.set_state("verification", user_id, updated)
            if error:
                raise ValueError(error)
            user["email_verified"] = True
            user = data_manager.save(user)
            data_manager.set_state("verification", user_id, None)
            display_message("Email verified.")
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
        print("\n1. Sign up\n2. Resume by email\n3. Quit")
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
        print(
            f"Found: {location['label']} "
            f"({location['latitude']:.6f}, {location['longitude']:.6f})"
        )
        confirmed = ask_yes_no("Is this your current location?")
        if confirmed is None:
            return None
        if confirmed:
            return location


def ask_search_mode():
    while True:
        value = read_input("Travel by walking or driving? (walk/drive, /cancel): ")
        if _cancelled(value):
            return None
        mode = value.lower()
        if mode in {"walk", "walking"}:
            return "walk"
        if mode in {"drive", "driving"}:
            return "drive"
        display_message("Choose walk or drive.")


def ask_search_distance(profile, mode):
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
        display_message("Enter a positive distance in km, such as 2 or 2.5 km.")


def ask_search_cuisine(profile):
    liked = profile["liked_cuisines"] or []
    if liked:
        print("Saved liked cuisines:")
        for number, cuisine in enumerate(liked, 1):
            print(f"  {number}. {cuisine.title()}")
    while True:
        value = read_input(
            "Choose one number or enter a new cuisine (/cancel): "
        )
        if _cancelled(value):
            return None
        if value.isdigit() and 1 <= int(value) <= len(liked):
            return liked[int(value) - 1]
        cuisine = value.lower().strip()
        if cuisine in CUISINES:
            return cuisine
        suggestions = logic_manager.cuisine_suggestions(cuisine)
        if len(suggestions) == 1:
            confirmed = ask_yes_no(f"Did you mean {suggestions[0].title()}?")
            if confirmed is None:
                return None
            if confirmed:
                return suggestions[0]
        display_message("Choose one saved number or one supported cuisine name.")


def ask_search_budget(profile):
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
        display_message("Enter a positive SGD amount, such as 12 or 12.50.")


def ask_search_other(profile):
    saved = profile[OTHER_PREFERENCES] or []
    if saved:
        print("Saved other preferences:")
        for number, item in enumerate(saved, 1):
            print(f"  {number}. {item}")
    while True:
        value = read_input(
            "Other preferences today [Enter = all saved; numbers, none, "
            "or new comma-separated items] (/cancel): "
        )
        if _cancelled(value):
            return None
        if not value or value.lower() == "all":
            return list(saved)
        if value.lower() == "none":
            return []
        if re.fullmatch(r"\d+(?:\s*,\s*\d+)*", value):
            numbers = [int(part.strip()) for part in value.split(",")]
            if saved and all(1 <= number <= len(saved) for number in numbers):
                return list(dict.fromkeys(saved[number - 1] for number in numbers))
            display_message("Choose numbers shown in the saved list.")
            continue
        try:
            return validate_value(OTHER_PREFERENCES, value.split(","))
        except ValueError as error:
            display_message(error)


def collect_search(user, config):
    """Collect one search request without changing the saved user profile."""
    profile = user["preferences"]
    location = ask_search_location(config)
    if location is None:
        return None
    mode = ask_search_mode()
    if mode is None:
        return None
    distance = ask_search_distance(profile, mode)
    if distance is None:
        return None
    cuisine = ask_search_cuisine(profile)
    if cuisine is None:
        return None
    budget = ask_search_budget(profile)
    if budget is None:
        return None
    other = ask_search_other(profile)
    if other is None:
        return None
    return {
        "origin": location, "mode": mode, "max_distance_km": distance,
        "cuisine": cuisine, "budget_per_person": budget,
        OTHER_PREFERENCES: other,
        "dietary_requirements": list(profile["dietary_requirements"] or []),
        "disliked_cuisines": list(profile["disliked_cuisines"] or []),
    }


def display_search_summary(request):
    display_message("Today's search is ready:")
    print(f"  From: {request['origin']['label']}")
    print(f"  Travel: {request['mode']} up to {request['max_distance_km']} km")
    print(f"  Cuisine: {request['cuisine']}")
    print(f"  Budget: SGD {request['budget_per_person']}")
    print(f"  Other preferences: {', '.join(request[OTHER_PREFERENCES]) or 'none'}")
    display_message("Searching restaurants...")


def resolve_cuisine_token(token, field):
    """Return a confirmed cuisine or explicitly accepted extra preference."""
    if token in CUISINES:
        return token, None
    candidates = logic_manager.cuisine_suggestions(token)
    if len(candidates) == 1:
        confirmed = ask_yes_no(f"Did you mean {candidates[0].title()}?")
        if confirmed is not True:
            raise ValueError("No changes saved. Please clarify the cuisine.")
        return candidates[0], None
    if candidates:
        print("Possible matches: " + ", ".join(candidates))
        selected = read_input("Choose a cuisine by name, or /cancel: ")
        if selected is None or selected.lower() not in candidates:
            raise ValueError("No changes saved. Please clarify the cuisine.")
        return selected.lower(), None
    if token not in logic_manager.UNSUPPORTED_CUISINES:
        raise ValueError(
            "Unrecognized cuisine. Choose from: " + ", ".join(CUISINES))
    display_message(f"{token.title()} is outside the supported cuisine list.")
    confirmed = ask_yes_no("Include it in your other preferences instead?")
    if confirmed is not True:
        raise ValueError("Choose another cuisine, or none.")
    prefix = {"liked_cuisines": "Likes ",
              "disliked_cuisines": "Avoids "}[field]
    return None, prefix + token


def resolve_cuisines(text, field, preferences):
    """Resolve the whole answer before returning any proposed update."""
    tokens = logic_manager.cuisine_tokens(text, field)
    resolved = []
    extras = []
    for token in tokens:
        cuisine, extra = resolve_cuisine_token(token, field)
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
    """Collect a typed action; never persist or call the AI API."""
    preferences = user["preferences"]
    field = field or logic_manager.next_field(preferences)
    display_message(QUESTIONS.get(
        field, "Profile complete. Use /search, /edit, /profile, /logout, or /quit.",
    ))
    text = read_input()
    if text is None:
        return {"action": "exit"}
    command = command_action(text)
    if command is not None:
        return command
    text = clean_text(text, 1000)
    if field in CUISINE_FIELDS:
        if not config.get("ai_bypass") and (
            logic_manager.needs_cuisine_interpretation(text, field)
        ):
            return interpretation_action(preferences, field, text)
        updates = resolve_cuisines(text, field, preferences)
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
