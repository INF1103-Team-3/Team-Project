"""Persist user-approved wishes and cuisines from a BIS search."""


class SearchPreferenceRecorder:
    """Own profile updates derived from explicitly confirmed search input."""

    def __init__(self, data_manager, logger, other_preferences_field):
        self._data = data_manager
        self._log = logger
        self._other_preferences = other_preferences_field

    def remember_wishes(self, session, today_request, config):
        if not today_request:
            return
        user = session["user"]
        saved = user["preferences"][self._other_preferences] or []
        wish = today_request.lower()
        if wish in saved:
            return
        preferences = dict(user["preferences"])
        preferences[self._other_preferences] = saved + [wish]
        session["user"] = self._data.save_preferences(
            user["userID"], preferences, config)
        self._log.debug_log(
            "Saved one confirmed special request for later searches.",
            "INFO", "BIS.data.save_preferences")

    def remember_cuisine(self, session, cuisine, config):
        user = session["user"]
        preferences = dict(user["preferences"])
        preferences["liked_cuisines"] = list(dict.fromkeys(
            (preferences["liked_cuisines"] or []) + [cuisine]))
        preferences["disliked_cuisines"] = [
            item for item in preferences["disliked_cuisines"] or []
            if item != cuisine]
        session["user"] = self._data.save_preferences(
            user["userID"], preferences, config)
        self._log.debug_log(
            "Saved one approved liked cuisine.", "INFO",
            "BIS.data.save_preferences")
