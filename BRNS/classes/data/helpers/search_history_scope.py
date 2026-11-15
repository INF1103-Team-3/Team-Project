"""Request-local user identity for persisted search history; no schema changes."""
from contextlib import contextmanager
from contextvars import ContextVar


class SearchHistoryScope:
    def __init__(self):
        self._identity = ContextVar("bitefinder_history_user", default=None)

    def get(self):
        return self._identity.get()

    @contextmanager
    def for_user(self, user_id):
        token = self._identity.set(user_id)
        try:
            yield
        finally:
            self._identity.reset(token)
