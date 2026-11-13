"""One encapsulated BIS account session and its action dispatch."""

from sources.profile_schema import empty_preferences
from BIS.classes.session_action_dispatcher import SessionActionDispatcher


class InteractionSession:
    """Own one user's mutable session state and manager collaborations."""

    def __init__(
            self, user, config, ai_manager, data_manager, io_manager,
            logic_manager, terminal_ui, debug_log, search_handler,
            state=None, action_dispatcher=None):
        self._config = config
        self._ai = ai_manager
        self._data = data_manager
        self._io = io_manager
        self._logic = logic_manager
        self._terminal_ui = terminal_ui
        self._debug_log = debug_log
        self._search_handler = search_handler
        self.__state = state or {
            "user": user, "field": None, "location_action": "add",
        }
        self.__actions = action_dispatcher or self._create_action_dispatcher()

    def _create_action_dispatcher(self):
        dispatcher = SessionActionDispatcher(self._handle_unknown)
        dispatcher.register(("exit", "logout"), self._handle_end)
        dispatcher.register(("show_profile",), self._handle_show_profile)
        dispatcher.register(("search",), self._handle_search)
        dispatcher.register(("help",), self._handle_help)
        dispatcher.register(("color",), self._handle_color)
        dispatcher.register(("edit_menu",), self._handle_edit_menu)
        dispatcher.register(("edit",), self._handle_edit)
        dispatcher.register(("rename",), self._handle_rename)
        dispatcher.register(("change_password",), self._handle_change_password)
        dispatcher.register(("reset_profile",), self._handle_reset)
        dispatcher.register(("profile_update",), self._handle_profile_update)
        return dispatcher

    @property
    def state(self):
        """Return the compatibility session dictionary."""
        return self.__state

    def save_update(self, action, from_ai):
        trace_token = self._debug_log.start_trace()
        try:
            user = self.__state["user"]
            was_incomplete = (
                self._logic.next_field(user["preferences"]) is not None)
            operation = action.get("location_action", "add")
            if self.__state["field"] == "location":
                operation = self.__state["location_action"]
            updates = self._io.resolve_proposed_updates(
                user["preferences"], action["updates"], from_ai,
                location_action=operation,
            )
            self._debug_log.debug_log(
                f"Resolved {len(updates)} preference fields.", "INFO",
                "BIS.io.resolve_proposed_updates",
            )
            preferences = self._logic.apply_updates(
                user["preferences"], updates, operation)
            self._debug_log.debug_log(
                "Profile update validated.", "INFO",
                "BIS.logic.apply_updates",
            )
            saved = self._data.save_preferences(
                user["userID"], preferences, self._config)
            self._debug_log.debug_log(
                "Preferences saved.", "INFO",
                "BIS.data.save_preferences",
            )
            self.__state.update(
                user=saved, field=None, location_action="add")
            self._io.display_message("Preferences saved.")
            if (was_incomplete and self._logic.next_field(
                    saved["preferences"]) is None):
                self._search_handler(
                    self.__state, self._config, automatic=True)
        finally:
            self._debug_log.end_trace(trace_token)

    def rename_user(self):
        username = self._io.prompt_username()
        if username is None:
            return
        updated = dict(self.__state["user"], username=username)
        self.__state["user"] = self._data.save(updated)
        self._io.display_message("Username saved.")

    def change_password(self):
        user_id = self.__state["user"]["userID"]
        verified = self._io.verify_user_password(user_id, cancel_raises=False)
        if not verified:
            self._io.display_message("Password unchanged.")
            return
        credential = self._io.prompt_new_password(confirm=True)
        if credential is None:
            self._io.display_message("Password unchanged.")
            return
        self._data.save_credentials(user_id, credential)
        self._io.display_message("Password updated.")

    def reset_preferences(self):
        saved = self._data.save_preferences(
            self.__state["user"]["userID"], empty_preferences(),
            self._config,
        )
        self.__state.update(
            user=saved, field=None, location_action="add")
        self._io.display_message(
            "Preferences reset; account details retained.")

    def end(self, intent):
        user = self.__state["user"]
        self._data.save_preferences(
            user["userID"], user["preferences"], self._config)
        message = {"logout": "Logged out.", "exit": "Goodbye!"}[intent]
        if (intent == "exit"
                and self._logic.next_field(user["preferences"]) is not None):
            message = "Profile saved. " + message
        self._io.display_message(message)
        self._debug_log.debug_log(
            "Session ended.", "INFO", "BIS.session." + intent)
        return intent

    def handle_action(self, action, from_ai=False):
        intent = action["action"]
        self._debug_log.debug_log(
            f"Dispatching {intent}.", "DEBUG", "BIS.main.handle_action")
        return self.__actions.dispatch(action, from_ai)

    def _handle_end(self, action, _from_ai):
        return self.end(action["action"])

    def _handle_show_profile(self, _action, _from_ai):
        self._io.display_profile(self.__state["user"])

    def _handle_search(self, _action, _from_ai):
        self._search_handler(self.__state, self._config)

    def _handle_help(self, action, _from_ai):
        self._io.display_help(action.get("topic"))

    def _handle_color(self, action, _from_ai):
        self._io.apply_color_setting(action["enabled"])

    def _handle_edit_menu(self, _action, _from_ai):
        selected = self._io.choose_profile_edit()
        if selected is None:
            return
        if selected["action"] == "rename":
            self.rename_user()
            return
        if selected["action"] == "change_password":
            self.change_password()
            return
        self.__state.update(
            field=selected["field"],
            location_action=selected["location_action"],
        )

    def _handle_edit(self, action, _from_ai):
        self.__state.update(
            field=action["field"],
            location_action=action["location_action"],
        )

    def _handle_rename(self, _action, _from_ai):
        self.rename_user()

    def _handle_change_password(self, _action, _from_ai):
        self.change_password()

    def _handle_reset(self, _action, _from_ai):
        self.reset_preferences()

    def _handle_profile_update(self, action, from_ai):
        if action.get("updates"):
            self.save_update(action, from_ai)
            return
        self._handle_unknown(action, from_ai)

    def _handle_unknown(self, _action, _from_ai):
        self._io.display_message(
            "Please clarify your preferences; nothing was changed.")

    def run(self):
        user = self.__state["user"]
        display = self._data.get_state("display", user["userID"]) or {}
        self._terminal_ui.set_color_enabled(
            display.get("color_enabled") is not False)

        def change_color(enabled):
            self._data.set_state(
                "display", user["userID"],
                None if enabled else {"color_enabled": False},
            )
            self._terminal_ui.set_color_enabled(enabled)
            self._io.display_message(
                "Colors enabled for your account." if enabled
                else "Colors disabled for your account."
            )

        self._io.set_color_handler(change_color)
        try:
            self._io.display_welcome(user)
            if self._logic.next_field(user["preferences"]) is None:
                self._search_handler(
                    self.__state, self._config, automatic=True)
            while True:
                action = {}
                try:
                    action = self._io.collect_action(
                        self.__state["user"], self._config,
                        self.__state["field"],
                        self.__state["location_action"],
                    )
                    from_ai = action["action"] == "interpret"
                    if from_ai:
                        action = self._ai.process(
                            action["record"], self._config)
                    result = self.handle_action(action, from_ai)
                    if result is not None:
                        return result
                except (ValueError, RuntimeError, OSError) as error:
                    self._io.display_message(error)
                    self._io.display_message(
                        "No preference update was applied. Please retry.")
                    if action.get("action") in {"exit", "logout"}:
                        return "exit"
        finally:
            self._io.set_color_handler(None)
            self._terminal_ui.set_color_enabled(True)
