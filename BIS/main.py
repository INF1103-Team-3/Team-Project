"""Coordinate the five procedural chatbot managers."""

import ai_manager
import data_manager
import io_manager
import logic_manager
from sources.profile_schema import empty_preferences
from support import config as settings
from support import debug_log


def save_update(action, session, config, from_ai):
    """Save only a fully resolved update, then advance the session."""
    user = session["user"]
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


def run_migration():
    outcome = data_manager.migrate_users()
    io_manager.display_message(
        f"Migrated {outcome['migrated']} accounts; "
        f"{outcome['reviews']} need review."
    )
    for backup in outcome["backups"]:
        io_manager.display_message("Backup: " + backup)


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
