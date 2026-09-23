"""Input layer — all user boundaries. Every input() and print() lives here.
Generic filters mirror Google Maps search filters (price band, rating,
open-now, distance); dietary/allergy/certification are BiteFinder's own."""

BAND_SYMBOLS = {
    "inexpensive": "$",
    "moderate": "$$",
    "expensive": "$$$",
    "very_expensive": "$$$$",
}


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


def ask_price_band(prompt):
    """Google Maps-style price filter: any / $ / $$ / $$$ / $$$$."""
    menu = {"any": None, "$": "inexpensive", "$$": "moderate",
            "$$$": "expensive", "$$$$": "very_expensive"}
    while True:
        raw = input(f"{prompt} (any / $ / $$ / $$$ / $$$$): ").strip()
        if raw in menu:
            return menu[raw]
        print("  Please type any, $, $$, $$$ or $$$$.")


def ask_rating(prompt):
    """Google Maps-style rating filter: any / 4.0 / 4.5."""
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
    return {
        "location": location,
        "max_walk_minutes": ask_int("Max walking time (minutes): "),
        "budget_band": ask_price_band("Max budget"),
        "dietary": ask_choice("Dietary (none/halal/vegetarian/vegan): ",
                              ["none", "halal", "vegetarian", "vegan"]),
        "allergies": [a.strip() for a in allergies_raw.split(",") if a.strip()],
        "food_preference": input("Food/cuisine preference: ").strip(),
        "min_rating": ask_rating("Min rating"),
        "eat_time": input("Open now or at a time (Enter = now / HH:MM): ").strip() or "now",
        "free_text": input("Anything else? (e.g. 'something spicy'): ").strip(),
    }

def print_parsed(req):
    band = BAND_SYMBOLS.get(req.get("budget_band"), "any")
    rating = req.get("min_rating")
    rating_txt = f"{rating}+" if rating else "any"
    print("\n[BiteFinder understood your request as]")
    print(f"  cuisine: {req.get('cuisine')} | dietary: {req.get('dietary')} | "
          f"budget: {band} | rating: {rating_txt} | walk: {req.get('max_walk_minutes')} min | "
          f"allergies: {req.get('allergies')} | time: {req.get('eat_time')}")


def print_ai_model(model_id):
    if model_id:
        print(f"  [interpreted by {model_id}]")


def _fmt_price(r):
    sym = BAND_SYMBOLS.get(r.get("price_band"), "")
    price = r.get("avg_price")
    if price is not None:
        return f"${price:.2f} ({sym})" if sym else f"${price:.2f}"
    return sym if sym else "price unavailable"


def _fmt_walk(r):
    w = r.get("walk_minutes")
    src = " (est.)" if r.get("walk_source") == "estimate" else ""
    return f"{w} min walk{src}" if w is not None else "walk time unavailable"


def print_results(results):
    matches, alternatives = results["matches"], results["alternatives"]
    if not matches and not alternatives:
        print("\nNo options found. Try relaxing budget, walking time, or another location.")
        return

    # Guidance when nothing in this area can be verified (no matches, all-unknowns)
    if not matches and alternatives:
        unknown_only = all(
            ("unknown" in reason) or ("unavailable" in reason)
            for item in alternatives for reason in item["reasons"]
        )
        if unknown_only:
            print("\nNo certified matches in this area yet — nearby places lack verified")
            print("dietary/price data, so nothing can be recommended as a match. Options:")
            print("  - Try a location covered by our verified catalog")
            print("  - Or search with dietary 'none' to rank by Google data (rating, price band)")

    if matches:
        print(f"\n=== {len(matches)} match(es) for you ===")
        for item in matches:
            r = item["restaurant"]
            rating = r.get("rating")
            rating_txt = f"rating: {rating}" if rating is not None else "rating: unavailable"
            print(f"\n{r['name']}  (score {item['score']})")
            print(f"  {r.get('cuisine', 'unknown')} | {_fmt_price(r)} | {_fmt_walk(r)} "
                  f"| {rating_txt} | dietary: {r.get('dietary', 'unknown')} "
                  f"| certification: {r.get('certification', 'unknown')}")
            source = r.get("source", "catalog")
            if "catalog" in source:
                print("  data: verified (catalog)")
            else:
                print("  data: unverified (google only)")
            for reason in item["reasons"]:
                print(f"  + {reason}")
    else:
        print("\nNo exact match, but here are the closest alternatives")
        print("(your dietary and allergy rules were NOT relaxed):")
    if alternatives:
        if matches:
            print("\n=== Alternatives (what would need to change) ===")
        for item in alternatives:
            r = item["restaurant"]
            print(f"\n{r['name']}  [data: {r.get('source', 'catalog')}]")
            for reason in item["reasons"]:
                print(f"  ! {reason}")


def choose_restaurant(results):
    options = results["matches"] + results["alternatives"]
    if not options:
        return None
    print("\nShow walking route: enter a number above (or Enter to skip):")
    while True:
        raw = input("> ").strip()
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
