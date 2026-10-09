from __future__ import annotations

import math
from datetime import datetime

from models import SearchRequest

DEFAULT_MAX_WALK_MIN = 15
LINE = "-" * 46
OUTCOME_LABEL = {"accept": "ACCEPTED", "flag": "FLAGGED", "reject": "REJECTED"}


# ---------------------------------------------------------------- plain output


def show_message(text: str = "") -> None:
    print(text)


def show_error(text: str) -> None:
    print(f"Error: {text}")


def show_warning(text: str) -> None:
    print(f"Note: {text}")


def _directory_status(count: int, updated: datetime | None) -> str:
    if not count:
        return "Halal certification data: not downloaded yet (run: python halal_data_scrape.py)."
    text = f"Halal certification data: {count} certified establishments"
    if updated:
        days = (datetime.now() - updated).days
        text += f", updated {updated:%Y-%m-%d}"
        if days > 7:
            text += f" ({days} days ago; consider re-running python halal_data_scrape.py)"
    return text + "."


def show_welcome(
    saved_count: int,
    directory_count: int = 0,
    directory_updated: datetime | None = None,
) -> None:
    print("=== Restaurant Finder ===")
    if saved_count:
        print(f"{saved_count} saved restaurant record(s) loaded.")
    print(_directory_status(directory_count, directory_updated))
    print()


# ---------------------------------------------------------- validated prompting


def _prompt(label: str, parse):
    """Ask until parse() accepts the answer. parse raises ValueError(message) on bad data."""
    while True:
        raw = input(label).strip()
        try:
            return parse(raw)
        except ValueError as exc:
            print(f"  {exc}")


def _choice_parser(options: list[str], blank: str | None = None):
    def parse(raw: str) -> str:
        value = raw.lower().replace(" ", "-").replace("_", "-")
        if not value and blank is not None:
            return blank
        if value in options:
            return value
        raise ValueError(f"Please type one of: {', '.join(options)}.")

    return parse


def _parse_menu(raw: str) -> str:
    mapping = {
        "1": "search", "search": "search", "s": "search",
        "2": "quit", "quit": "quit", "q": "quit", "exit": "quit",
    }
    value = raw.lower()
    if value in mapping:
        return mapping[value]
    raise ValueError("Please enter 1 or 2.")


def _parse_location(raw: str) -> str:
    if not raw:
        raise ValueError("Location can't be empty.")
    if len(raw) > 200:
        raise ValueError("Location is too long (200 characters max).")
    if not any(ch.isalnum() for ch in raw):
        raise ValueError("Location must contain letters or numbers.")
    return raw


def _parse_minutes(raw: str) -> int:
    if not raw:
        return DEFAULT_MAX_WALK_MIN
    if not raw.isdigit() or not 1 <= int(raw) <= 120:
        raise ValueError("Enter a whole number of minutes between 1 and 120.")
    return int(raw)


def _parse_rating(raw: str) -> float:
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not 0 <= value <= 5:  # NaN also fails this check
        raise ValueError("Enter a rating between 0 and 5 (e.g. 4.0), or press Enter for any.")
    return value


def _parse_budget(raw: str):
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Enter a positive number (local currency), or press Enter for no limit.")
    return value


# ----------------------------------------------------------------- input views


def ask_menu() -> str:
    print("What would you like to do?")
    print("  1) Search for restaurants")
    print("  2) Quit the program")
    return _prompt("Choose 1 or 2: ", _parse_menu)


def collect_search_request() -> SearchRequest:
    print()
    location = _prompt("Location / general area: ", _parse_location)
    food_type = _prompt(
        "Food type (halal / non-halal / vegetarian, Enter for non-halal): ",
        _choice_parser(["halal", "non-halal", "vegetarian"], blank="non-halal"),
    )
    max_walk = _prompt(
        f"Max walking time in minutes (Enter for {DEFAULT_MAX_WALK_MIN}): ", _parse_minutes
    )
    min_rating = _prompt("Minimum rating 0-5 (Enter for any): ", _parse_rating)
    max_budget = _prompt(
        "Max average spend per person, in local currency (Enter for no limit): ",
        _parse_budget,
    )
    return SearchRequest(
        location=location,
        food_type=food_type,
        max_walk_min=max_walk,
        min_rating=min_rating,
        max_budget=max_budget,
    )


def collect_history_filters() -> dict:
    """Ask how to filter saved records. Returns kwargs for data_manager.filter_records."""
    print()
    outcome = _prompt(
        "Show which outcome? (accept / flag / reject / any, Enter for any): ",
        _choice_parser(["accept", "flag", "reject", "any"], blank="any"),
    )
    food_type = _prompt(
        "Food type? (halal / non-halal / vegetarian / any, Enter for any): ",
        _choice_parser(["halal", "non-halal", "vegetarian", "any"], blank="any"),
    )
    min_rating = _prompt("Minimum rating 0-5 (Enter for any): ", _parse_rating)
    return {
        "outcome": None if outcome == "any" else outcome,
        "food_type": None if food_type == "any" else food_type,
        "min_rating": min_rating if min_rating > 0 else None,
    }


# ----------------------------------------------------------- record formatting


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _format_rating(record: dict) -> str:
    rating = _num(record.get("rating"))
    if rating is None:
        return "no rating yet"
    count = _num(record.get("rating_count"))
    if count:
        return f"{rating:.1f} / 5 ({int(count):,} reviews)"
    return f"{rating:.1f} / 5"


def _format_price(record: dict) -> str:
    price = _num(record.get("avg_price"))
    if price is None:
        return "unknown"
    source = {"google": "Google", "ai": "AI estimate"}.get(record.get("price_source"), "")
    return f"{price:.2f}" + (f" ({source})" if source else "")


_DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _hours_lines(record: dict) -> list[str]:
    """Opening hours, one line per day: mon: 0900 - 2100 ... sun: closed."""
    hours = record.get("open_hours")
    if isinstance(hours, dict):
        lines = ["   Opening hours:"]
        for day in _DAY_ORDER:
            lines.append(f"       {day}: {hours.get(day, 'unknown')}")
        return lines
    if isinstance(hours, str) and hours:
        # Saved by an earlier version, which stored today's hours as one string.
        return [f"   Open today:     {hours}"]
    return ["   Opening hours:  unknown"]


def _format_certification(record: dict) -> str:
    status = record.get("certification", "unknown")
    if status == "halal-certified":
        kind = record.get("certificate_type")
        return "Certified" + (f" ({kind})" if kind else "") + ", listed on HalalFreak"
    if status == "not-listed":
        return "Not found in the certified list"
    return str(status)


def _certification_lines(record: dict) -> list[str]:
    lines = [f"   Certification:  {_format_certification(record)}"]
    if record.get("certificate_url"):
        if record.get("certificate_name"):
            lines.append(f"   Listed as:      {record['certificate_name']}")
        lines.append(f"   Certificate:    {record['certificate_url']}")
    return lines


def format_record(index: int, record: dict) -> str:
    """One restaurant as a readable block."""
    outcome = OUTCOME_LABEL.get(record.get("outcome"), "UNKNOWN")
    score = _num(record.get("score"))
    score_text = f"   match score {score:.1f}" if score is not None else ""
    allergens = record.get("allergens") or []
    spicy = {True: "Yes", False: "No"}.get(record.get("spicy_options"), "unknown")
    walk = record.get("walk_minutes")

    lines = [
        LINE,
        f"{index}. {record.get('name', 'Unknown')}  [{outcome}]{score_text}",
        LINE,
        f"   Cuisine:        {str(record.get('cuisine') or 'unknown').title()}",
        f"   Dietary:        {str(record.get('dietary') or 'unknown').title()}",
        *_certification_lines(record),
        f"   Rating:         {_format_rating(record)}",
        f"   Avg price:      {_format_price(record)}",
        f"   Allergens:      {', '.join(allergens) if allergens else 'none listed'}",
        f"   Walking time:   {f'{walk} min' if walk is not None else 'unknown'}",
        *_hours_lines(record),
        f"   Spicy options:  {spicy}",
    ]
    if record.get("address"):
        lines.append(f"   Address:        {record['address']}")
    for reason in record.get("reasons") or []:
        lines.append(f"   Note:           {reason}")
    if record.get("directions_url"):
        lines.append(f"   Directions:     {record['directions_url']}")
    return "\n".join(lines)


def format_record_list(records: list[dict]) -> str:
    return "\n\n".join(format_record(i, r) for i, r in enumerate(records, start=1))


def _criteria_text(request: SearchRequest) -> str:
    parts = []
    if request.min_rating > 0:
        parts.append(f"rated {request.min_rating:.1f}+")
    if request.max_budget is not None:
        parts.append(f"averaging {request.max_budget:g} or less")
    parts.append(f"within a {request.max_walk_min}-minute walk")
    return ", ".join(parts)


# ----------------------------------------------------------------- output views


def show_results(
    shown: list[dict],
    request: SearchRequest,
    rejected_count: int,
    ai_failed: int,
    saved: bool,
    directory_count: int = 0,
    directory_updated: datetime | None = None,
    matching_count: int | None = None,
) -> None:
    print()
    if not shown:
        print("No restaurants matched your criteria.")
        print(
            f"{rejected_count} candidate(s) were rejected. "
            "Try a longer walk, a lower minimum rating or a higher budget."
        )
    else:
        if matching_count and matching_count > len(shown):
            print(
                f"Showing the top {len(shown)} of {matching_count} matching restaurant(s) "
                f"{_criteria_text(request)}, best match first."
            )
        else:
            print(f"Showing {len(shown)} restaurant(s) {_criteria_text(request)}, best match first.")
        print()
        print(format_record_list(shown))
        print()
        if any(r.get("outcome") == "flag" for r in shown):
            print("FLAGGED restaurants have something worth double-checking (see their notes).")
        note = (
            "Names, ratings, hours and walking times come from Google Maps. Cuisine, allergens, "
            "spice and some prices are AI estimates."
        )
        if request.food_type == "halal":
            if directory_count:
                when = f", last updated {directory_updated:%Y-%m-%d}" if directory_updated else ""
                note += (
                    " Halal certification is matched by postal code and name against "
                    f"HalalFreak's list of certified establishments{when}. "
                    "Certificates can lapse, so please confirm before you go."
                )
            else:
                note += (
                    " Halal certification could not be checked because the certification "
                    "data has not been downloaded (run python halal_data_scrape.py), so halal "
                    "status is NOT verified."
                )
        elif request.food_type == "vegetarian":
            note += (
                " Vegetarian status is NOT verified, so please confirm vegetarian "
                "options with the restaurant."
            )
        print(note)
    if ai_failed:
        print(f"Note: AI details were unavailable for {ai_failed} restaurant(s).")
    if rejected_count and shown:
        print(f"{rejected_count} other candidate(s) were rejected by your filters.")
    if not saved:
        print("Note: results could not be saved to history (see logs/bitefinder.log).")
    print()


def show_summary(summary: dict) -> None:
    print()
    print(LINE)
    print("Saved restaurants summary")
    print(LINE)
    print(f"   Total records:   {summary['total']}")
    outcomes = summary.get("by_outcome", {})
    print(
        "   By outcome:      "
        + ", ".join(f"{OUTCOME_LABEL.get(k, k).title()} {v}" for k, v in sorted(outcomes.items()))
    )
    food = summary.get("by_food_type", {})
    print("   By food type:    " + ", ".join(f"{k} {v}" for k, v in sorted(food.items())))
    avg_rating = summary.get("avg_rating")
    avg_price = summary.get("avg_price")
    print(f"   Average rating:  {f'{avg_rating:.2f} / 5' if avg_rating is not None else 'n/a'}")
    print(f"   Average price:   {f'{avg_price:.2f}' if avg_price is not None else 'n/a'}")
    top = summary.get("top_cuisines") or []
    print("   Top cuisines:    " + (", ".join(f"{c.title()} ({n})" for c, n in top) if top else "n/a"))
    print()


def show_history(matches: list[dict], total: int) -> None:
    print()
    if not matches:
        print(f"No saved restaurants match those filters (out of {total}).")
    else:
        print(f"{len(matches)} of {total} saved restaurant(s), newest first.")
        print()
        print(format_record_list(matches))
    print()
