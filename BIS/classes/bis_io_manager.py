"""Object boundary for BIS terminal interaction behavior."""

from BIS.classes.bis_search_io_interface import BISSearchIOInterface
from BIS.classes.bis_session_io_interface import BISSessionIOInterface


class BISIOManager(BISSessionIOInterface, BISSearchIOInterface):
    """Expose only the terminal operations used by an interaction session."""

    def __init__(self, manager_module):
        self._manager = manager_module

    def resolve_proposed_updates(self, *args, **kwargs):
        return self._manager.resolve_proposed_updates(*args, **kwargs)

    def display_message(self, *args, **kwargs):
        return self._manager.display_message(*args, **kwargs)

    def prompt_username(self):
        return self._manager.prompt_username()

    def display_profile(self, user):
        return self._manager.display_profile(user)

    def display_help(self, topic=None):
        return self._manager.display_help(topic)

    def apply_color_setting(self, enabled):
        return self._manager.apply_color_setting(enabled)

    def choose_profile_edit(self):
        return self._manager.choose_profile_edit()

    def set_color_handler(self, handler):
        return self._manager.set_color_handler(handler)

    def display_welcome(self, user):
        return self._manager.display_welcome(user)

    def collect_action(self, *args, **kwargs):
        return self._manager.collect_action(*args, **kwargs)

    def collect_search(self, user, config):
        return self._manager.collect_search(user, config)

    def ask_search_clarification(self, config):
        return self._manager.ask_search_clarification(config)

    def confirm_search_request(self, request, config=None):
        return self._manager.confirm_search_request(request, config)

    def display_search_summary(self, request):
        return self._manager.display_search_summary(request)

    def choose_results_action(self, *args, **kwargs):
        return self._manager.choose_results_action(*args, **kwargs)

    def choose_result_sort(self):
        return self._manager.choose_result_sort()

    def refine_search_request(self, request, profile, config):
        return self._manager.refine_search_request(request, profile, config)

    def choose_route_result(self, result_count):
        return self._manager.choose_route_result(result_count)
