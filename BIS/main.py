"""Coordinate the five procedural chatbot managers."""

import ai_manager
import data_manager
import io_manager
import logic_manager
from BRNS import io_manager as brns_io
from BRNS import main as brns_main
from sources.profile_schema import empty_preferences
from support import config as settings
from support import debug_log


def run_search(session, config, automatic=False):
    if logic_manager.next_field(session["user"]["preferences"]) is not None:
        io_manager.display_message("Complete your profile before using /search.")
        return
    user_id = session["user"]["userID"]
    try:
        state = data_manager.get_state("search", user_id)
        if automatic and state and state.get("completed"):
            return
        if automatic:
            io_manager.display_message("Profile complete. Starting /search.")
        request = io_manager.collect_search(session["user"], config)
        if request is None:
            io_manager.display_message("Search cancelled. Your profile is saved.")
            return
        io_manager.display_search_summary(request)
        if config.get("ai_bypass"):
            session["search"] = request
            data_manager.set_state("search", user_id, {"completed": True})
            io_manager.display_message(
                "Chatbot test mode: restaurant search skipped.")
            return
        results = brns_main.search(request)
        session["search"] = request
        data_manager.set_state("search", user_id, {"completed": True})
        brns_io.show_results(results)
        options = results["matches"] + results["alternatives"]
        if not any(item["restaurant"].get("lat") is not None
                   and item["restaurant"].get("lng") is not None
                   for item in options):
            return
        while True:
            answer = io_manager.read_input(
                "Show a route? Enter a result number, or Enter to skip: ")
            if answer is None or not answer or answer.lower() == "/cancel":
                return
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                chosen = options[int(answer) - 1]["restaurant"]
                if chosen.get("lat") is None or chosen.get("lng") is None:
                    io_manager.display_message(
                        "No route is available for that restaurant.")
                    continue
                route = brns_main.route_to(chosen, request)
                brns_io.show_route(**route)
                return
            io_manager.display_message(
                f"Choose a result number from 1 to {len(options)}, or Enter.")
    except (ValueError, RuntimeError, OSError) as error:
        io_manager.display_message(error)


def save_update(action, session, config, from_ai):
    """Save only a fully resolved update, then advance the session."""
    user = session["user"]
    was_incomplete = logic_manager.next_field(user["preferences"]) is not None
    updates = io_manager.resolve_proposed_updates(
        user["preferences"], action["updates"], from_ai,
    )
    operation = action.get("location_action", "add")
    if session["field"] == "location":
        operation = session["location_action"]
    preferences = logic_manager.apply_updates(
        user["preferences"], updates, operation,
    )
    saved = data_manager.save_preferences(user["userID"], preferences, config)
    session.update(user=saved, field=None, location_action="add")
    io_manager.display_message("Preferences saved.")
    if was_incomplete and logic_manager.next_field(saved["preferences"]) is None:
        run_search(session, config, automatic=True)


def rename_user(session):
    username = io_manager.prompt_username()
    if username is None:
        return
    updated = dict(session["user"], username=username)
    session["user"] = data_manager.save(updated)
    io_manager.display_message("Username saved.")


def reset_preferences(session, config):
    saved = data_manager.save_preferences(
        session["user"]["userID"], empty_preferences(), config,
    )
    session.update(user=saved, field=None, location_action="add")
    io_manager.display_message("Preferences reset; account details retained.")


def end_session(intent, session, config):
    user = session["user"]
    data_manager.save_preferences(user["userID"], user["preferences"], config)
    message = {"logout": "Logged out.", "exit": "Goodbye!"}[intent]
    io_manager.display_message("Profile saved. " + message)
    debug_log.debug_log("Session ended.", "INFO", "session." + intent)
    return intent


def handle_action(action, session, config, from_ai=False):
    """Dispatch an action with guard clauses instead of nested branches."""
    intent = action["action"]
    if intent in {"exit", "logout"}:
        return end_session(intent, session, config)
    if intent == "show_profile":
        io_manager.display_profile(session["user"])
        return None
    if intent == "search":
        run_search(session, config)
        return None
    if intent == "help":
        io_manager.display_help(action.get("topic"))
        return None
    if intent == "edit":
        session.update(field=action["field"],
                       location_action=action["location_action"])
        return None
    if intent == "rename":
        rename_user(session)
        return None
    if intent == "reset_profile":
        reset_preferences(session, config)
        return None
    if intent == "profile_update" and action.get("updates"):
        save_update(action, session, config, from_ai)
        return None
    io_manager.display_message(
        "Please clarify your preferences; nothing was changed."
    )
    return None


def run_session(user, config):
    """Retain the saved state if collection, confirmation, or saving fails."""
    io_manager.display_welcome(user)
    session = {"user": user, "field": None, "location_action": "add"}
    if logic_manager.next_field(user["preferences"]) is None:
        run_search(session, config, automatic=True)
    while True:
        action = {}
        try:
            action = io_manager.collect_action(
                session["user"], config, session["field"],
                session["location_action"],
            )
            from_ai = action["action"] == "interpret"
            if from_ai:
                action = ai_manager.process(action["record"], config)
            result = handle_action(action, session, config, from_ai)
            if result is not None:
                return result
        except (ValueError, RuntimeError, OSError) as error:
            io_manager.display_message(error)
            io_manager.display_message(
                "No preference update was applied. Please retry."
            )
            if action.get("action") in {"exit", "logout"}:
                return "exit"


def run_accounts(config):
    data_manager.load()
    if data_manager.LAST_ERROR:
        io_manager.display_message(data_manager.LAST_ERROR)
    while True:
        user = io_manager.select_user(config)
        if user is None:
            io_manager.display_message("Goodbye!")
            return
        if run_session(user, config) != "logout":
            return


def main():
    """Start the interactive chatbot using environment configuration."""
    debug_log.configure()
    try:
        config = settings.load_config()
        if config.get("debug"):
            debug_log.configure(io_manager.display_debug)
        errors = settings.validate_config(config)
        if errors:
            for error in errors:
                io_manager.display_message(error)
            return
        run_accounts(config)
    except (ValueError, RuntimeError, OSError) as error:
        io_manager.display_message(error)
    except (EOFError, KeyboardInterrupt):
        io_manager.display_message("Goodbye!")


if __name__ == "__main__":
    main()
