"""Compatibility façade for BRC's object-oriented Logic Manager."""

from BRC.classes.logic_manager import LogicManager
from BRC.classes.outlet_matcher import OutletMatcher
from BRC.models import HalalDatabase, HalalOutlet, RestaurantRecord


_default_manager = LogicManager()


def build_database(snapshot, cuisines):
    """Preserve the public database-building function."""
    return _default_manager.build_database(snapshot, cuisines)


def exact_matches(records, candidate_groups):
    """Preserve the public exact-match function."""
    return _default_manager.exact_matches(records, candidate_groups)


def check_restaurants(records, database, chosen_certificates):
    """Accept object or legacy-dictionary inputs through one rule engine."""
    object_records = [
        item if isinstance(item, RestaurantRecord) else RestaurantRecord(item)
        for item in records
    ]
    object_database = database
    if not isinstance(database, HalalDatabase):
        object_database = HalalDatabase([
            item if isinstance(item, HalalOutlet)
            else HalalOutlet.from_dict(item)
            for item in database
        ])
    return _default_manager.check_restaurants(
        object_records, object_database, chosen_certificates)


def evaluate(record):
    """Evaluate the legacy workflow envelope."""
    if not isinstance(record, dict) or set(record) != {"context", "ai_output"}:
        raise ValueError("BRC evaluation needs context and AI output.")
    context, output = record["context"], record["ai_output"]
    if context["scenario"] == "build_database":
        return build_database(context["raw_snapshot"], output["cuisines"])
    return check_restaurants(
        context["records"], context["database"], output["matches"])


def score(record):
    return _default_manager.score(record)


def route(record):
    return _default_manager.route(record)


__all__ = [
    "LogicManager",
    "OutletMatcher",
    "build_database",
    "check_restaurants",
    "evaluate",
    "exact_matches",
    "route",
    "score",
]
