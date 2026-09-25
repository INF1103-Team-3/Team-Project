"""Input layer — all user boundaries. Every input() and print() lives here.
Generic filters mirror Google Maps search filters; dietary/allergy/certification
are BiteFinder's own. Travel is dual-mode (walk + drive)."""
from datetime import datetime, timedelta

BAND_SYMBOLS = {
    "inexpensive": "$",
    "moderate": "$$",
    "expensive": "$$$",
    "very_expensive": "$$$$",
}

BAND_MENU = {"$": "inexpensive", "$$": "moderate",
             "$$$": "expensive", "$$$$": "very_expensive"}

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_ABBR = {"mon": "monday", "tue": "tuesday", "tues": "tuesday", "wed": "wednesday",
            "thu": "thursday", "thur": "thursday", "thurs": "thursday",
            "fri": "friday", "sat": "saturday", "sun": "sunday"}


def print_welcome():
    print("=" * 55)
    print("  BiteFinder — food that fits your rules")
    print("=" * 55)


def ask_int(prompt):
    """Reject and re-prompt on bad data."""
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  Please enter a positive whole number (e.g. 15).")


def ask_float(prompt):
    """Reject and re-prompt on bad data."""
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return None
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print("  Please enter a positive number (e.g. 5 or 2.5).")


def ask_budget(prompt):
    """Budget as band, a max (12), or a range (5-15). Returns (band, min, max)."""
    while True:
        raw = input(f"{prompt} (any / $ / $$ / $$$ / $$$$ / e.g. 5-15 or 12): ").strip()
        if raw in ("", "any"):
            return None, None, None
        if raw in BAND_MENU:
            return BAND_MENU[raw], None, None
        cleaned = raw.replace("$", "").replace(" ", "")
        if "-" in cleaned:
            parts = cleaned.split("-")
            if len(parts) == 2:
                try:
                    lo, hi = float(parts[0]), float(parts[1])
                    if 0 <= lo <= hi:
                        return None, lo, hi
                except ValueError:
                    pass
        else:
            try:
                value = float(cleaned)
                if value > 0:
                    return None, None, value
            except ValueError:
                pass
        print("  Enter any, a band ($/$$/$$$/$$$$), a max (12), or a range (5-15).")


def ask_rating(prompt):
    """Rating filter: any / 4.0 / 4.5."""
    while True:
        raw = input(f"{prompt} (any / 4.0 / 4.5): ").strip().lower()
        if raw in ("", "any"):
            return None
        try:
            value = float(raw)
            if 1.0 <= value <= 5.0:
                return value
        except ValueError:
            pass
        print("  Enter 'any' or a rating between 1.0 and 5.0.")


def ask_travel_mode():
    """Walking vs driving, then distance in the matching unit (required)."""
    while True:
        raw = input("Travel by walking or driving? (walk / drive): ").strip().lower()
        if raw in ("walk", "w"):
            minutes = None
            while minutes is None:
                minutes = ask_int("Max walking time (minutes): ")
                if minutes is None:
                    print("  Walking time is required (this is your search radius).")
            return {"mode": "walk", "max_walk_minutes": minutes, "max_drive_km": None}
        if raw in ("drive", "d", "car"):
            km = None
            while km is None:
                km = ask_float("Max driving distance (km): ")
                if km is None:
                    print("  Driving distance is required (this is your search radius).")
            return {"mode": "drive", "max_walk_minutes": None, "max_drive_km": km}
        print("  Please type walk or drive.")


def ask_choice(prompt, options):
    while True:
        raw = input(prompt).strip().lower()
        if raw in options:
            return raw
        print(f"  Please type one of: {', '.join(options)}")


def ask_eat_time(prompt):
    """Eat time as: Enter/'now' (today now), 'HH:MM' (today), or '<day> HH:MM'
    (e.g. 'sat 19:30', 'sunday 1300'). Returns {"eat_time": str, "eat_day": str}.
    eat_day: 'today' or a weekday name."""
    while True:
        raw = input(prompt).strip().lower()
        if raw in ("", "now"):
            return {"eat_time": "now", "eat_day": "today"}
        # day + time?
        parts = raw.split()
        if len(parts) == 2:
            day_word, time_word = parts
            day = DAY_ABBR.get(day_word, day_word if day_word in DAYS else None)
            if day:
                hhmm = time_word.replace(":", "").zfill(4)
                if hhmm.isdigit() and len(hhmm) == 4:
                    h, m = int(hhmm[:2]), int(hhmm[2:])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        return {"eat_time": f"{h:02d}:{m:02d}", "eat_day": day}
        # time only?
        hhmm = raw.replace(":", "").zfill(4)
        if hhmm.isdigit() and len(hhmm) == 4:
            h, m = int(hhmm[:2]), int(hhmm[2:])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return {"eat_time": f"{h:02d}:{m:02d}", "eat_day": "today"}
        print("  Enter 'now', a time (19:30), or a day + time (sat 19:30).")


def get_user_requirements():
    print("\n--- Your request (Enter = skip optional) ---")
    location = ""
    while not location:
        location = input("Location (SG postal code / address / landmark): ").strip()
    allergies_raw = input("Allergies to avoid (comma separated): ").strip()
    travel = ask_travel_mode()
    band, bmin, bmax = ask_budget("Budget")
    eat = ask_eat_time("Eat time (Enter=now / 19:30 / sat 19:30): ")
    return {
        "location": location,
        "mode": travel["mode"],
        "max_walk_minutes": travel["max_walk_minutes"],
        "max_drive_km": travel["max_drive_km"],
        "budget_band": band,
        "budget_min": bmin,
        "budget_max": bmax,
        "dietary": ask_choice("Dietary (none/halal/vegetarian/vegan): ",
                              ["none", "halal", "vegetarian", "vegan"]),
        "allergies": [a.strip() for a in allergies_raw.split(",") if a.strip()],
        "food_preference": input("Food/cuisine preference: ").strip(),
        "min_rating": ask_rating("Min rating"),
        "eat_time": eat["eat_time"],
        "eat_day": eat["eat_day"],
        "free_text": input("Anything else? (e.g. 'something spicy'): ").strip(),
    }


def print_parsed(req):
    bmin, bmax = req.get("budget_min"), req.get("budget_max")
    if bmax is not None:
        budget_txt = (f"${bmin:.0f}-{bmax:.0f}" if bmin is not None
                      else f"up to ${bmax:.0f}")
    else:
        budget_txt = BAND_SYMBOLS.get(req.get("budget_band"), "any")
    rating = req.get("min_rating")
    rating_txt = f"{rating}+" if rating else "any"
    if req.get("mode") == "drive":
        travel_txt = f"drive up to {req.get('max_drive_km')} km"
    else:
        travel_txt = f"walk up to {req.get('max_walk_minutes')} min"
    day_txt = "today" if req.get("eat_day", "today") == "today" else req.get("eat_day")
    print("\n[BiteFinder understood your request as]")
    print(f"  cuisine: {req.get('cuisine')} | dietary: {req.get('dietary')} | "
          f"budget: {budget_txt} | rating: {rating_txt} | {travel_txt} | "
          f"allergies: {req.get('allergies')} | time: {day_txt} {req.get('eat_time')}")


def print_ai_model(model_id):
    if model_id:
        print(f"  [interpreted by {model_id}]")


def _fmt_price(r):
    price = r.get("avg_price")
    if price is not None:
        return f"${price:.2f}"
    pr = r.get("price_range")
    if pr:
        return pr
    sym = BAND_SYMBOLS.get(r.get("price_band"), "")
    return sym if sym else "price unavailable"


def _fmt_travel(r, mode):
    """Dual-mode display: chosen mode first (marked), other mode as context."""
    parts = []
    w, w_m = r.get("walk_minutes"), r.get("walk_meters")
    d, d_m = r.get("drive_minutes"), r.get("drive_meters")
    walk_txt = f"{w} min walk" if w is not None else None
    drive_txt = (f"{d} min drive ({(d_m or 0) / 1000:.1f} km)"
                 if d is not None else None)
    if mode == "drive":
        first, second = drive_txt, walk_txt
    else:
        first, second = walk_txt, drive_txt
    if first:
        parts.append(f"> {first}")
    if second:
        parts.append(second)
    return " | ".join(parts) if parts else "travel time unavailable"


def _fmt_address(r):
    if r.get("address"):
        return r["address"]
    if r.get("lat") is not None and r.get("lng") is not None:
        return f"approx. location: {r['lat']:.4f}, {r['lng']:.4f} (map link after selecting)"
    return "address unavailable"


def _fmt_hours(r, eat_day, eat_time):
    """Show the operating hours relevant to the user's requested day."""
    if eat_time == "now" and (eat_day or "today") == "today":
        # today+now is the default case: just show the day's window
        hours = r.get("open_hours")
        return f"hours today: {hours}" if hours else None
    hours = r.get("open_hours")
    if not hours:
        return None
    return f"hours on {eat_day}: {hours}"


def print_results(results):
    matches, alternatives = results["matches"], results["alternatives"]
    mode = results.get("mode", "walk")
    eat_day = results.get("eat_day", "today")
    eat_time = results.get("eat_time", "now")

    if not matches and not alternatives:
        if results.get("hidden"):
            print(f"\n({results['hidden']} place(s) hidden by your hard filters: "
                  f"dietary, allergies, minimum rating)")
        print("\nNo options found. Try lowering your minimum rating, or relaxing "
              "budget and travel distance, or another location.")
        return

    if results.get("hidden"):
        print(f"\n({results['hidden']} place(s) hidden by your hard filters: "
              f"dietary, allergies, minimum rating)")

    number = 1
    if matches:
        print(f"\n=== {len(matches)} match(es) for you ===")
        for item in matches:
            r = item["restaurant"]
            rating = r.get("rating")
            rating_txt = f"rating: {rating}" if rating is not None else "rating: unavailable"
            print(f"\n{number}. {r['name']}  (score {item['score']})")
            print(f"  {_fmt_address(r)}")
            print(f"  {r.get('cuisine', 'unknown')} | {_fmt_price(r)} | "
                  f"{_fmt_travel(r, mode)} | {rating_txt} "
                  f"| dietary: {r.get('dietary', 'unknown')} "
                  f"| certification: {r.get('certification', 'unknown')}")
            hours_txt = _fmt_hours(r, eat_day, eat_time)
            if hours_txt:
                print(f"  {hours_txt}")
            source = r.get("source", "catalog")
            if "catalog" in source:
                print("  data: verified (catalog)")
            else:
                print("  data: unverified (google only)")
            for reason in item["reasons"]:
                print(f"  {reason}")
            number += 1
    else:
        print("\nNo exact match, but here are the closest alternatives")
        print("(your dietary and allergy rules were NOT relaxed):")

    if alternatives:
        if matches:
            print("\n=== Alternatives (what would need to change) ===")
        for item in alternatives:
            r = item["restaurant"]
            rating = r.get("rating")
            rating_txt = f"rating: {rating}" if rating is not None else "rating: unavailable"
            print(f"\n{number}. {r['name']}  [data: {r.get('source', 'catalog')}]")
            print(f"  {_fmt_address(r)}")
            print(f"  {r.get('cuisine', 'unknown')} | {_fmt_price(r)} | "
                  f"{_fmt_travel(r, mode)} | {rating_txt} "
                  f"| dietary: {r.get('dietary', 'unknown')} "
                  f"| certification: {r.get('certification', 'unknown')}")
            hours_txt = _fmt_hours(r, eat_day, eat_time)
            if hours_txt:
                print(f"  {hours_txt}")
            for reason in item["reasons"]:
                print(f"  {reason}")
            number += 1


def choose_restaurant(results):
    """User types the number shown next to a restaurant above. None to skip."""
    options = results["matches"] + results["alternatives"]
    if not options:
        return None
    print("\nShow route: enter the number of a restaurant above "
          f"(1-{len(options)}), or Enter to skip:")
    while True:
        raw = input("> ").strip()
        if raw == "" or raw.lower() in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]["restaurant"]
        print(f"  Please enter a number 1-{len(options)} (or Enter to skip).")


def print_route(name, route, link, mode):
    label = "Walking route" if mode == "walk" else "Driving route"
    print(f"\n--- {label} to {name} ---")
    if route is None:
        print("  Detailed route unavailable right now — open this map link instead:")
    else:
        km = route["distance_m"] / 1000
        dist_txt = f"{km:.1f} km" if mode == "drive" else f"{route['distance_m']} m"
        print(f"  {route['duration_min']} min | {dist_txt}")
        for i, step in enumerate(route["steps"], start=1):
            print(f"  {i}. {step}")
        print("  Visual map:")
    print(f"  {link}")


def print_error(message):
    print(f"\n[ERROR] {message}")
