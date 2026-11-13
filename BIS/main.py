"""BIS compatibility façade and four-manager application bootstrap."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_INITIALIZED = False


def _initialize_cli():
    global _INITIALIZED
    global ai_manager, data_manager, io_manager, logic_manager
    global BISSearchWorkflow, InteractionSession, SearchPreferenceRecorder
    global SearchResultsController, build_cli_brns_service, OTHER_PREFERENCES
    global settings, email_delivery, debug_log, terminal_ui
    if _INITIALIZED:
        return
    from BIS import ai_manager, data_manager, io_manager, logic_manager
    from BIS.classes.services.cli.bis_search_workflow import BISSearchWorkflow
    from BIS.classes.services.cli.interaction_session import InteractionSession
    from BIS.classes.data.search_preference_recorder import SearchPreferenceRecorder
    from BIS.classes.services.cli.search_results_controller import SearchResultsController
    from BRNS.runtime import build_cli_brns_service
    from sources.profile_schema import OTHER_PREFERENCES
    from support import config as settings
    from support.email_verification import email_delivery
    from common import debug_log, terminal_ui
    _INITIALIZED = True


def _search_managers():
    """Create the four BIS manager objects for one search workflow."""
    _initialize_cli()
    return (
        io_manager.manager(),
        ai_manager.manager(),
        logic_manager.manager(),
        data_manager.manager(),
    )


def _search_preference_recorder(data=None):
    _initialize_cli()
    return SearchPreferenceRecorder(
        data or data_manager.manager(),
        debug_log,
        OTHER_PREFERENCES,
    )


def _search_workflow():
    io, ai, logic, data = _search_managers()
    preferences = _search_preference_recorder(data)
    results = SearchResultsController(
        io, ai, logic, data, preferences, build_cli_brns_service(),
        email_delivery, debug_log, OTHER_PREFERENCES,
    )
    return BISSearchWorkflow(
        io, ai, logic, data, preferences, results,
        debug_log, OTHER_PREFERENCES,
    )


def run_search(session, config, automatic=False):
    """Run the IO → AI → Logic → Data BIS search workflow."""
    _initialize_cli()
    return _search_workflow().run(session, config, automatic)


def remember_search_wishes(session, today_request, config):
    """Keep confirmed wording in the profile for later searches."""
    return _search_preference_recorder().remember_wishes(
        session, today_request, config)


def remember_search_cuisine(session, cuisine, config):
    """Save an explicitly approved search cuisine to the user's likes."""
    return _search_preference_recorder().remember_cuisine(
        session, cuisine, config)


def _interaction_session(state, config):
    """Build the session object used by legacy-compatible entry points."""
    _initialize_cli()
    return InteractionSession(
        state["user"],
        config,
        ai_manager.manager(),
        data_manager.manager(),
        io_manager.manager(),
        logic_manager.manager(),
        terminal_ui,
        debug_log,
        run_search,
        state=state,
    )


def save_update(action, session, config, from_ai):
    """Save only a fully resolved update, then advance the session."""
    return _interaction_session(session, config).save_update(action, from_ai)


def rename_user(session):
    return _interaction_session(session, {}).rename_user()


def reset_preferences(session, config):
    return _interaction_session(session, config).reset_preferences()


def end_session(intent, session, config):
    return _interaction_session(session, config).end(intent)


def handle_action(action, session, config, from_ai=False):
    """Dispatch an action with guard clauses instead of nested branches."""
    return _interaction_session(session, config).handle_action(
        action, from_ai)


def run_session(user, config):
    """Retain the saved state if collection, confirmation, or saving fails."""
    return _interaction_session(
        {"user": user, "field": None, "location_action": "add"},
        config,
    ).run()


def run_accounts(config):
    _initialize_cli()
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


def run_cli():
    """Start the existing CLI using environment configuration."""
    os.environ.setdefault("BITEFINDER_STORAGE", "mongo")
    _initialize_cli()
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


def main(argv=None):
    """Choose CLI or web; importing the module never launches either mode."""
    import argparse
    from BIS.classes.services.launcher.bis_launcher import BISLauncher
    from BIS.classes.io.cli.helpers.launcher_io import LauncherIO
    from BIS.classes.services.launcher.web_interface_launcher import WebInterfaceLauncher
    parser = argparse.ArgumentParser(description="BiteFinder CLI and web launcher")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--cli", action="store_true")
    modes.add_argument("--web", action="store_true")
    args = parser.parse_args(argv)
    mode = "cli" if args.cli else "web" if args.web else None
    try:
        return BISLauncher(LauncherIO(), run_cli, WebInterfaceLauncher()).run(mode)
    except (EOFError, KeyboardInterrupt):
        LauncherIO().display_message("Goodbye!")


if __name__ == "__main__":
    main()
