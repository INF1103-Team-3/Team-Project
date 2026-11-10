"""BIS compatibility façade and four-manager application bootstrap."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_manager
import data_manager
import io_manager
import logic_manager
from BIS.classes.bis_ai_manager import BISAIManager
from BIS.classes.bis_data_manager import BISDataManager
from BIS.classes.bis_io_manager import BISIOManager
from BIS.classes.bis_logic_manager import BISLogicManager
from BIS.classes.bis_search_workflow import BISSearchWorkflow
from BIS.classes.interaction_session import InteractionSession
from BIS.classes.search_preference_recorder import SearchPreferenceRecorder
from BIS.classes.search_results_controller import SearchResultsController
from BRNS import io_manager as brns_io
from BRNS import main as brns_main
from sources.profile_schema import OTHER_PREFERENCES
from support import config as settings
from support.email_verification import email_delivery
from shared import debug_log, terminal_ui


def _search_managers():
    """Create the four BIS manager objects for one search workflow."""
    return (
        BISIOManager(io_manager),
        BISAIManager(ai_manager),
        BISLogicManager(manager_module=logic_manager),
        BISDataManager(data_manager),
    )


def _search_preference_recorder(data=None):
    return SearchPreferenceRecorder(
        data or BISDataManager(data_manager),
        debug_log,
        OTHER_PREFERENCES,
    )


def _search_workflow():
    io, ai, logic, data = _search_managers()
    preferences = _search_preference_recorder(data)
    results = SearchResultsController(
        io, ai, logic, data, preferences, brns_main, brns_io,
        email_delivery, debug_log, OTHER_PREFERENCES,
    )
    return BISSearchWorkflow(
        io, ai, logic, data, preferences, results,
        debug_log, OTHER_PREFERENCES,
    )


def run_search(session, config, automatic=False):
    """Run the IO → AI → Logic → Data BIS search workflow."""
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
    return InteractionSession(
        state["user"],
        config,
        BISAIManager(ai_manager),
        BISDataManager(data_manager),
        BISIOManager(io_manager),
        BISLogicManager(manager_module=logic_manager),
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
