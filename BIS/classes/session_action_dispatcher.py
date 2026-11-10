"""Extensible registry for BIS session action handlers."""


class SessionActionDispatcher:
    """Dispatch action names to registered handlers without type branching."""

    def __init__(self, fallback):
        self.__handlers = {}
        self._fallback = fallback

    def register(self, action_names, handler):
        """Associate one handler with independently extensible action names."""
        for action_name in action_names:
            self.__handlers[action_name] = handler

    def dispatch(self, action, from_ai=False):
        handler = self.__handlers.get(action["action"], self._fallback)
        return handler(action, from_ai)

    @property
    def action_names(self):
        return tuple(self.__handlers)
