"""Shared terminal formatting for structured recommendation and route payloads."""

from common import terminal_ui as ui


def show_results(results, announce_no_matches=True):
    """Display ranked restaurants without collecting any input."""
    matches = results["matches"]
    alternatives = results["alternatives"]
    if not matches and announce_no_matches:
        ui.message("No restaurants matched all your search choices.", "warning")
    if not matches and not alternatives:
        ui.message("No alternatives found either.", "warning")
        return
    number = 0
    for heading, items in (("Matches", matches), ("Alternatives", alternatives)):
        if not items:
            continue
        role = "match" if heading == "Matches" else "alternative"
        ui.section(f"{heading} ({len(items)})", role)
        for item in items:
            number += 1
            show_result_card(number, item, results, role)


def show_result_list(results):
    """Show a compact numbered list before optional details or routing."""
    number = 0
    for heading, items in (("Matches", results["matches"]),
                           ("Alternatives", results["alternatives"])):
        if not items:
            continue
        role = "match" if heading == "Matches" else "alternative"
        ui.section(f"{heading} ({len(items)})", role)
        for item in items:
            number += 1
            restaurant = item["restaurant"]
            mode = results["mode"]
            if results.get("limit_unit") == "minutes":
                minutes = restaurant.get(f"{mode}_minutes")
                distance = (f"{minutes:g} min by {mode}"
                            if minutes is not None else "travel time unavailable")
                if results.get("traffic_aware"):
                    distance += " (live traffic)"
            else:
                meters = restaurant.get(f"{mode}_meters")
                distance = (f"{meters / 1000:.2f} km by {mode}"
                            if meters is not None else "distance unavailable")
            rating = restaurant.get("rating")
            rating_text = (f" · Google {rating:g}/5"
                           if type(rating) in (int, float) else " · Google rating unavailable")
            ui.item(number, f"{restaurant['name']} · {distance}{rating_text}", role=role)


def show_no_matches(results):
    """Explain why the leading alternative is not a verified match."""
    ui.message("No fully verified matches for these search choices.", "warning")
    verification = results.get("halal_verification")
    if verification:
        if verification["errors"]:
            ui.message(
                "BRC could not complete official MUIS halal verification. "
                f"Google halal indications were used as an unofficial fallback "
                f"for {verification['google_fallback']} candidate(s).", "warning")
            if verification.get("database_missing"):
                ui.message(
                    "The cleaned BRC halal database is missing and its automatic "
                    "build failed. Run BRC/main.py to build it, then retry.",
                    "warning")
        elif verification["verified"] == 0 and verification["google_fallback"] == 0:
            ui.message(
                f"BRC checked {verification['checked']} candidate(s), but none "
                "matched an active official MUIS listing or had a Google halal "
                "indication.", "warning")
        elif verification["verified"]:
            ui.message(
                f"BRC verified {verification['verified']} halal candidate(s), "
                "but the remaining search requirements excluded them.",
                "warning")
    exclusions = results.get("excluded_reasons") or {}
    visible_exclusions = [
        (reason, count) for reason, count in exclusions.items()
        if reason != "MUIS halal certification not verified"
    ]
    if visible_exclusions:
        ui.line("  Excluded before results:", "warning")
        for reason, count in sorted(
                visible_exclusions, key=lambda item: item[1], reverse=True)[:3]:
            ui.line(f"    {count} — {reason[:1].upper()}{reason[1:]}", "warning")
    alternatives = results["alternatives"]
    if not alternatives:
        if not verification:
            ui.message("No alternatives found. Try changing today's search.",
                       "warning")
        return
    cautions = [reason[2:] for reason in alternatives[0]["reasons"]
                if reason.startswith("! ")]
    if cautions:
        ui.message("Why the top alternative is not a match: "
                   + "; ".join(cautions[:3]) + ".", "warning")


def show_result_card(number, item, results, role):
    """Print one restaurant card with the evidence behind its ranking."""
    restaurant = item["restaurant"]
    cuisine = ", ".join(restaurant.get("cuisines") or []) or "Unavailable"
    dietary = ", ".join(
        entry for entry in restaurant.get("dietary_requirements") or []
        if entry != "halal")
    halal = restaurant.get("halal_status")
    mode = results["mode"]
    source = restaurant.get(f"{mode}_source")
    if results.get("limit_unit") == "minutes":
        minutes = restaurant.get(f"{mode}_minutes")
        travel = (f"{minutes:g} min by {mode}"
                  if minutes is not None else "travel time unavailable")
        if results.get("traffic_aware"):
            travel += " (live traffic)"
        if source == "estimate":
            travel += " (estimate, unverified)"
    else:
        meters = restaurant.get(f"{mode}_meters")
        travel = (f"{meters / 1000:.2f} km by {mode}"
                  if meters is not None else "distance unavailable")
        if source == "estimate":
            travel += " (estimate, unverified)"
    average = restaurant.get("avg_price")
    starting = restaurant.get("price_start")
    price = (f"Average SGD {average:.2f}" if average is not None
             else f"From SGD {starting:.2f}" if starting is not None
             else "Unverified")
    ui.item(number, restaurant['name'], role=role)
    ui.line(f"     {restaurant.get('address') or 'Address unavailable'}", "muted")
    ui.field("Cuisine", cuisine, indent=5)
    ui.field("Price", price, indent=5)
    ui.field("Travel", travel, indent=5)
    rating = restaurant.get("rating")
    rating_count = restaurant.get("rating_count")
    rating_text = (f"{rating:g}/5" if type(rating) in (int, float)
                   else "Unavailable")
    if type(rating_count) is int and rating_count >= 0 and rating is not None:
        rating_text += f" ({rating_count:,} reviews)"
    ui.field("Google rating", rating_text, indent=5)
    ui.field("Hours today", restaurant.get("today_hours") or "Unavailable", indent=5)
    if dietary:
        ui.field("Dietary", dietary, indent=5)
    if halal == "official":
        ui.field("Halal", "Official MUIS certification verified",
                 indent=5, role="success")
    elif halal == "unofficial":
        ui.field("Halal", "Unofficial indication; not checked",
                 indent=5, role="warning")
    elif halal == "unverified" and "halal" in results["requested_dietary"]:
        ui.field("Halal", "Unverified", indent=5, role="warning")
    highlights = []
    checks = []
    for reason in item["reasons"]:
        if (reason == "! cuisine unavailable" and not restaurant.get("cuisines")):
            continue
        if (reason in ("! Halal (unofficial; not checked)",
                       "Halal (unofficial; not checked)") and halal == "unofficial"):
            continue
        if reason == "! halal status unverified" and halal == "unverified":
            continue
        caution = reason.startswith("! ")
        (checks if caution else highlights).append(
            reason[2:] if caution else reason)
    if highlights:
        ui.line("     Highlights:", "success")
        for reason in highlights:
            ui.line(f"       • {reason[:1].upper()}{reason[1:]}", "success")
    if checks:
        ui.line("     Things to check:", "warning")
        for reason in checks:
            ui.line(f"       • {reason[:1].upper()}{reason[1:]}", "warning")
    ui.line()


def show_route(name, route, link, mode, traffic_aware=False):
    """Print step-by-step route guidance and Maps link."""
    ui.section(f"{mode.title()} route to {name}")
    if traffic_aware:
        ui.line("Travel time uses live traffic.", "muted")
    if route is not None:
        if mode == "transit":
            ui.field("Journey", f"{route['duration_min']} min by transit")
        else:
            ui.field("Journey", f"{route['distance_m']} m · {route['duration_min']} min")
        for step in route["steps"]:
            ui.line(f"  {step}")
    else:
        ui.line("  Detailed route unavailable; use this map link:", "warning")
    ui.field("Map", link)
