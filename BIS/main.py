"""Coordinate the five procedural chatbot managers."""

import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_manager
import data_manager
import io_manager
import logic_manager
from BRNS import io_manager as brns_io
from BRNS import main as brns_main
from sources.profile_schema import OTHER_PREFERENCES, empty_preferences
from support import config as settings
from shared import debug_log, terminal_ui


def run_search(session, config, automatic=False):
    if logic_manager.next_field(session["user"]["preferences"]) is not None:
        io_manager.display_message("Complete your profile before using /search.")
        return
    user_id = session["user"]["userID"]
    trace_token = debug_log.start_trace()
    started = time.monotonic()
    debug_log.debug_log("Search started.", "INFO", "BIS.main.run_search")
    try:
        state = data_manager.get_state("search", user_id)
        if automatic and state and state.get("completed"):
            return
        if automatic:
            io_manager.display_message("Profile complete. Starting /search.")
        collected = io_manager.collect_search(session["user"], config)
        if collected is None:
            debug_log.debug_log("Collection cancelled.", "INFO", "BIS.io.collect_search")
            io_manager.display_message("Search cancelled. Your profile is saved.")
            return
        debug_log.debug_log("Search choices collected.", "INFO",
                            "BIS.io.collect_search")
        confirmed = collected["request"]
        today_request = collected["today_request"]
        if collected.get("save_cuisine"):
            remember_search_cuisine(session, collected["save_cuisine"], config)
        if config.get("ai_bypass"):
            request = logic_manager.validate_search_request(confirmed)
        else:
            while True:
                interpreted = ai_manager.interpret_search_request(
                    confirmed, today_request, config)
                debug_log.debug_log("AI interpretation returned.", "INFO",
                                    "BIS.ai.interpret_search_request")
                if interpreted is None:
                    raise RuntimeError(
                        "BIS AI could not interpret today's request. Please retry.")
                try:
                    request = logic_manager.validate_search_request(
                        confirmed, interpreted)
                    if (today_request and not confirmed[OTHER_PREFERENCES]
                            and request[OTHER_PREFERENCES]
                            == confirmed[OTHER_PREFERENCES]):
                        request = dict(request)
                        request[OTHER_PREFERENCES] = (
                            confirmed[OTHER_PREFERENCES] + [today_request])
                        request = logic_manager.validate_search_request(request)
                    debug_log.debug_log("AI proposal validated.", "INFO",
                                        "BIS.logic.validate_search_request")
                    break
                except logic_manager.SearchClarificationNeeded as error:
                    debug_log.debug_log("Clarification required.", "WARNING",
                                        "BIS.logic.validate_search_request")
                    io_manager.display_message(error)
                    today_request = io_manager.ask_search_clarification(config)
                    if today_request is None:
                        io_manager.display_message("Search cancelled. Your profile is saved.")
                        return
            if io_manager.confirm_search_request(request, config) is not True:
                debug_log.debug_log("Interpretation declined.", "INFO",
                                    "BIS.io.confirm_search_request")
                io_manager.display_message("Search cancelled. Your profile is saved.")
                return
            debug_log.debug_log("Interpretation confirmed.", "INFO",
                                "BIS.io.confirm_search_request")
        payload = data_manager.serialize_search_request(request)
        debug_log.debug_log("Validated request serialized to JSON.", "INFO",
                            "BIS.data.serialize_search_request")
        remember_search_wishes(session, today_request, config)
        if config.get("ai_bypass"):
            io_manager.display_search_summary(request)
            session["search"] = request
            data_manager.set_state("search", user_id, {"completed": True})
            io_manager.display_message(
                "Chatbot test mode: restaurant search skipped.",
                role="bypass")
            debug_log.debug_log("Chatbot test completed without BRNS.", "INFO",
                                "BIS.main.run_search")
            return
        while True:
            io_manager.display_message("Searching restaurants...")
            results = brns_main.search(payload)
            matches = results["matches"]
            alternatives = results["alternatives"]
            debug_log.debug_log(
                f"BRNS returned {len(matches)} matches and "
                f"{len(alternatives)} alternatives.", "INFO",
                "BIS.main.run_search")
            session["search"] = request
            data_manager.set_state("search", user_id, {"completed": True})
            io_manager.display_message(
                f"Found {len(matches)} match{'es' if len(matches) != 1 else ''} "
                f"and {len(alternatives)} alternative"
                f"{'s' if len(alternatives) != 1 else ''}.")
            if matches:
                io_manager.display_message(
                    f"Top match: {matches[0]['restaurant']['name']}.")
            if not matches:
                brns_io.show_no_matches(results)
            visible = bool(matches)
            if visible:
                brns_io.show_result_list(results)
            options = matches + alternatives
            while True:
                action = io_manager.choose_results_action(
                    len(options) if visible else 0,
                    alternatives_hidden=bool(alternatives) and not visible)
                if action == "done":
                    io_manager.display_message(
                        "Search finished. Use /search to try again.")
                    return
                if action == "alternatives" and alternatives and not visible:
                    brns_io.show_result_list(results)
                    visible = True
                    continue
                if action == "more" and visible:
                    brns_io.show_results(
                        results, announce_no_matches=False)
                    continue
                if action == "again":
                    refined = io_manager.refine_search_request(
                        request, session["user"]["preferences"], config)
                    if refined is None:
                        continue
                    try:
                        if config.get("ai_bypass"):
                            validated = logic_manager.validate_search_request(
                                refined)
                        else:
                            interpreted = ai_manager.interpret_search_request(
                                refined, "", config)
                            if interpreted is None:
                                io_manager.display_message(
                                    "Could not interpret that change. "
                                    "Try again.")
                                continue
                            validated = logic_manager.validate_search_request(
                                refined, interpreted)
                    except (ValueError, RuntimeError) as error:
                        io_manager.display_message(error)
                        continue
                    if not config.get("ai_bypass"):
                        if io_manager.confirm_search_request(
                                validated, config) is not True:
                            io_manager.display_message(
                                "Search change cancelled; previous "
                                "results remain.")
                            continue
                    request = validated
                    payload = data_manager.serialize_search_request(request)
                    debug_log.debug_log(
                        "Refined request serialized to JSON.", "INFO",
                        "BIS.data.serialize_search_request")
                    break
                if action == "route" and visible:
                    result_number = io_manager.choose_route_result(len(options))
                    if result_number is None:
                        continue
                    chosen = options[result_number - 1]["restaurant"]
                    if chosen.get("lat") is None or chosen.get("lng") is None:
                        io_manager.display_message(
                            "No route is available for that restaurant.")
                        continue
                    route = brns_main.route_to(chosen, request)
                    brns_io.show_route(**route)
                    continue
                io_manager.display_message("Choose one of the actions shown.")
    except (ValueError, RuntimeError, OSError) as error:
        debug_log.debug_log(
            f"Search stopped: {type(error).__name__}.", "ERROR",
            "BIS.main.run_search")
        io_manager.display_message(
            f"{error} Details: logs/bitefinder.log "
            f"(trace {debug_log.current_trace_id()}).", role="error")
    finally:
        debug_log.debug_log(
            f"Search flow finished in {time.monotonic() - started:.2f}s.",
            "INFO", "BIS.main.run_search")
        debug_log.end_trace(trace_token)


def remember_search_wishes(session, today_request, config):
    """Keep the user's confirmed wording in the profile for later searches."""
    if not today_request:
        return
    user = session["user"]
    saved = user["preferences"][OTHER_PREFERENCES] or []
    wish = today_request.lower()
    if wish in saved:
        return
    preferences = dict(user["preferences"])
    preferences[OTHER_PREFERENCES] = saved + [wish]
    session["user"] = data_manager.save_preferences(
        user["userID"], preferences, config)
    debug_log.debug_log(
        "Saved one confirmed special request for later searches.",
        "INFO", "BIS.data.save_preferences")


def remember_search_cuisine(session, cuisine, config):
    """Save an explicitly approved search cuisine to the user's likes."""
    user = session["user"]
    preferences = dict(user["preferences"])
    preferences["liked_cuisines"] = list(dict.fromkeys(
        (preferences["liked_cuisines"] or []) + [cuisine]))
    preferences["disliked_cuisines"] = [
        item for item in preferences["disliked_cuisines"] or []
        if item != cuisine]
    session["user"] = data_manager.save_preferences(
        user["userID"], preferences, config)
    debug_log.debug_log("Saved one approved liked cuisine.", "INFO",
                        "BIS.data.save_preferences")


def save_update(action, session, config, from_ai):
    """Save only a fully resolved update, then advance the session."""
    trace_token = debug_log.start_trace()
    try:
        user = session["user"]
        was_incomplete = logic_manager.next_field(user["preferences"]) is not None
        updates = io_manager.resolve_proposed_updates(
            user["preferences"], action["updates"], from_ai,
        )
        debug_log.debug_log(
            f"Resolved {len(updates)} preference fields.", "INFO",
            "BIS.io.resolve_proposed_updates")
        operation = action.get("location_action", "add")
        if session["field"] == "location":
            operation = session["location_action"]
        preferences = logic_manager.apply_updates(
            user["preferences"], updates, operation,
        )
        debug_log.debug_log("Profile update validated.", "INFO",
                            "BIS.logic.apply_updates")
        saved = data_manager.save_preferences(
            user["userID"], preferences, config)
        debug_log.debug_log("Preferences saved.", "INFO",
                            "BIS.data.save_preferences")
        session.update(user=saved, field=None, location_action="add")
        io_manager.display_message("Preferences saved.")
        if was_incomplete and logic_manager.next_field(
                saved["preferences"]) is None:
            run_search(session, config, automatic=True)
    finally:
        debug_log.end_trace(trace_token)


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
    debug_log.debug_log("Session ended.", "INFO", "BIS.session." + intent)
    return intent


def handle_action(action, session, config, from_ai=False):
    """Dispatch an action with guard clauses instead of nested branches."""
    intent = action["action"]
    debug_log.debug_log(f"Dispatching {intent}.", "DEBUG",
                        "BIS.main.handle_action")
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
    display = data_manager.get_state("display", user["userID"]) or {}
    terminal_ui.set_color_enabled(display.get("color_enabled") is not False)

    def change_color(enabled):
        data_manager.set_state("display", user["userID"],
                               None if enabled else {"color_enabled": False})
        terminal_ui.set_color_enabled(enabled)
        io_manager.display_message(
            "Colors enabled for your account." if enabled
            else "Colors disabled for your account.")

    io_manager.set_color_handler(change_color)
    try:
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
    finally:
        io_manager.set_color_handler(None)
        terminal_ui.set_color_enabled(True)


def run_accounts(config):
    data_manager.load()
    if data_manager.LAST_ERROR:
        io_manager.display_message(data_manager.LAST_ERROR, role="error")
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
                io_manager.display_message(error, role="error")
            return
        run_accounts(config)
    except (ValueError, RuntimeError, OSError) as error:
        io_manager.display_message(error)
    except (EOFError, KeyboardInterrupt):
        io_manager.display_message("Goodbye!")


if __name__ == "__main__":
    main()
