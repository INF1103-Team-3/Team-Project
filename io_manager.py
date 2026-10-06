"""Input layer — all user boundaries. Every input() and print() lives here."""

BAND_SYMBOLS = {
    "inexpensive": "$",
    "moderate": "$$",
    "expensive": "$$$",
    "very_expensive": "$$$$",
}

BAND_MENU = {"$": "inexpensive", "$$": "moderate",
             "$$$": "expensive", "$$$$": "very_expensive"}


def print_welcome():
    print("=" * 55)
    print("  BiteFinder — food that fits your rules")
    print("=" * 55)


def pause(prompt="\nPress Enter to return to the main menu..."):
    """Wait for the user to acknowledge before continuing.
    Never crashes on Ctrl+C or EOF."""
    try:
        input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()


def ask_int(prompt):
    while True:
        raw = input(prompt).strip()
        if raw == "":
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  Please enter a positive whole number (e.g. 15).")


def ask_budget(prompt):
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


def ask_choice(prompt, options):
    while True:
        raw = input(prompt).strip().lower()
        if raw in options:
            return raw
        print(f"  Please type one of: {', '.join(options)}")


def get_user_requirements():
    print("\n--- Your request (Enter = skip optional) ---")
    location = ""
    while not location:
        location = input("Location (SG postal code / address / landmark): ").strip()
    allergies_raw = input("Allergies to avoid (comma separated): ").strip()
    band, bmin, bmax = ask_budget("Budget")
    return {
        "location": location,
        "max_walk_minutes": ask_int("Max walking time (minutes): "),
        "budget_band": band,
        "budget_min": bmin,
        "budget_max": bmax,
        "dietary": ask_choice("Dietary (none/halal/vegetarian/vegan): ",
                              ["none", "halal", "vegetarian", "vegan"]),
        "allergies": [a.strip() for a in allergies_raw.split(",") if a.strip()],
        "food_preference": input("Food/cuisine preference: ").strip(),
        "min_rating": ask_rating("Min rating"),
        "eat_time": input("Open now or at a time (Enter = now / HH:MM): ").strip() or "now",
        "free_text": input("Anything else? (e.g. 'something spicy'): ").strip(),
    }


def print_parsed(req):
    bmin, bmax = req.get("budget_min"), req.get("budget_max")
    if bmax is not None:
        budget_txt = (f"${bmin:.0f}–{bmax:.0f}" if bmin is not None
                      else f"up to ${bmax:.0f}")
    else:
        budget_txt = BAND_SYMBOLS.get(req.get("budget_band"), "any")
    rating = req.get("min_rating")
    rating_txt = f"{rating}+" if rating else "any"
    print("\n[BiteFinder understood your request as]")
    print(f"  cuisine: {req.get('cuisine')} | dietary: {req.get('dietary')} | "
          f"budget: {budget_txt} | rating: {rating_txt} | "
          f"walk: {req.get('max_walk_minutes')} min | "
          f"allergies: {req.get('allergies')} | time: {req.get('eat_time')}")


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


def _fmt_walk(r):
    w = r.get("walk_minutes")
    src = " (est.)" if r.get("walk_source") == "estimate" else ""
    return f"{w} min walk{src}" if w is not None else "walk time unavailable"


def _fmt_rating(r):
    rating = r.get("rating")
    if rating is None:
        return "rating unavailable"
    filled = max(0, min(5, round(rating)))
    return f"{'★' * filled}{'☆' * (5 - filled)} ({rating:.1f})"


def _fmt_address(r):
    if r.get("address"):
        return r["address"]
    if r.get("lat") is not None and r.get("lng") is not None:
        return f"approx. location: {r['lat']:.4f}, {r['lng']:.4f} (map link after selecting)"
    return "address unavailable"


def _fmt_cuisines(r):
    lst = r.get("cuisines")
    if isinstance(lst, list) and lst:
        return ", ".join(lst)
    return r.get("cuisine") or "unknown"


def _fmt_hours(r):
    """One-line summary of today's hours based on weekday_hours.

    Examples:
      "Open now · until 23:00"
      "Closed · opens 11:00"
      "Closed since 22:00"
      "Open 24 hours"
      "closed today"
      "hours unknown"
      "hours unavailable"
    """
    from datetime import datetime

    wh = r.get("weekday_hours")
    if not wh:
        return "hours unavailable"

    now = datetime.now()
    weekday = now.strftime("%A").lower()
    day_hours = wh.get(weekday)

    if day_hours is None:
        return "hours unknown"
    if not day_hours:
        return "closed today"

    try:
        open_t = day_hours[0]
        close_t = day_hours[1]
    except (IndexError, TypeError):
        return "hours unknown"

    # 24-hour case
    if open_t == "0000" and close_t == "2359":
        return "Open 24 hours"

    current = now.hour * 60 + now.minute
    open_m = int(open_t[:2]) * 60 + int(open_t[2:])
    close_m = int(close_t[:2]) * 60 + int(close_t[2:])
    open_str = f"{open_t[:2]}:{open_t[2:]}"
    close_str = f"{close_t[:2]}:{close_t[2:]}"

    # Overnight (closes next day)
    if close_m < open_m:
        if current >= open_m or current <= close_m:
            return f"Open now · until {close_str}"
        return f"Closed · opens {open_str}"

    if open_m <= current <= close_m:
        return f"Open now · until {close_str}"
    if current < open_m:
        return f"Closed · opens {open_str}"
    return f"Closed since {close_str}"


def print_results(results):
    matches, alternatives = results["matches"], results["alternatives"]

    if not matches and not alternatives:
        if results.get("hidden"):
            print(f"\n({results['hidden']} place(s) hidden by your hard filters: "
                  f"dietary, allergies, minimum rating)")
        print("\nNo options found. Try lowering your minimum rating, or relaxing "
              "budget and walking time, or another location.")
        return

    if results.get("hidden"):
        print(f"\n({results['hidden']} place(s) hidden by your hard filters: "
              f"dietary, allergies, minimum rating)")

    number = 1
    if matches:
        print(f"\n=== {len(matches)} match(es) for you ===")
        for item in matches:
            r = item["restaurant"]
            badge = " [HALAL]" if r.get("halal_certified") else ""
            print(f"\n{number}. {r['name']}{badge}  (score {item['score']})")
            print(f"  {_fmt_address(r)}")
            halal_txt = ""
            if r.get("halal_certified"):
                conf = r.get("halal_confidence") or 0
                halal_txt = f" | halal: MUIS certified ({conf:.0%})"
            print(f"  {_fmt_cuisines(r)} | {_fmt_price(r)} | {_fmt_walk(r)} "
                f"| {_fmt_rating(r)} | dietary: {r.get('dietary', 'unknown')} "
                  f"| certification: {r.get('certification', 'unknown')}{halal_txt}")
            print(f"  hours: {_fmt_hours(r)}")
            source = r.get("source", "catalog")
            if "catalog" in source:
                print("  data: verified (catalog)")
            else:
                print("  data: unverified (google only)")
            for reason in item["reasons"]:
                print(f"  + {reason}")
            number += 1
    else:
        print("\nNo exact match, but here are the closest alternatives")
        print("(your dietary and allergy rules were NOT relaxed):")

    if alternatives:
        if matches:
            print("\n=== Alternatives (what would need to change) ===")
        for item in alternatives:
            r = item["restaurant"]
            badge = " [HALAL]" if r.get("halal_certified") else ""
            print(f"\n{number}. {r['name']}{badge}  [data: {r.get('source', 'catalog')}]")
            print(f"  {_fmt_address(r)}")
            print(f"  {_fmt_cuisines(r)} | {_fmt_price(r)} | "
                  f"{_fmt_rating(r)} | dietary: {r.get('dietary', 'unknown')}")
            print(f"  hours: {_fmt_hours(r)}")
            for reason in item["reasons"]:
                print(f"  ! {reason}")
            number += 1


def choose_restaurant(results):
    """Let the user pick a restaurant for walking-route details.
    Always gives the user a chance to read the output first, even
    when there are no matches or alternatives."""
    options = results["matches"] + results["alternatives"]

    if not options:
        pause()
        return None

    print("\nView walking route: enter the number of a restaurant above "
          f"(1-{len(options)}), or Enter to skip:")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if raw == "":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]["restaurant"]
        print(f"  Please enter a number 1-{len(options)} (or Enter to skip).")


def print_route(name, route, link):
    print(f"\n--- Walking route to {name} ---")
    if route is None:
        print("  Detailed route unavailable right now — open this map link instead:")
    else:
        print(f"  {route['duration_min']} min | {route['distance_m']} m")
        for i, step in enumerate(route["steps"], start=1):
            print(f"  {i}. {step}")
        print("  Visual map:")
    print(f"  {link}")


def print_error(message):
    print(f"\n[ERROR] {message}")