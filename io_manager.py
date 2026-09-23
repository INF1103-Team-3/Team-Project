"""CLI input, orchestration and display; all normal user-facing output lives here."""

import json
from datetime import datetime, timezone

from ai_manager import interpret_request
from data_manager import (
    append_interaction, load_profile, load_restaurants, query_restaurants,
    save_profile,
)
from debug import debug_log
from logic_manager import prepare_request, recommend, record_selection
from schemas import empty_request, is_number, is_text_list, valid_coordinates


def ask_choice(prompt, choices):
    while True:
        value = input(prompt).strip().casefold()
        if value in choices:
            return value
        print("Choose one of: " + ", ".join(choices))


def ask_number(prompt):
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        try:
            value = float(raw)
            if is_number(value):
                return value
        except ValueError:
            pass
        print("Enter a non-negative finite number, or leave blank for no limit.")


def ask_tags(prompt):
    while True:
        raw = input(prompt)
        values = sorted({part.strip().casefold() for part in raw.split(",") if part.strip()})
        if is_text_list(values):
            return values
        print("Enter up to 30 short values separated by commas.")


def ask_location():
    while True:
        raw = input("Latitude, longitude (blank if not using walking routes): ").strip()
        if not raw:
            return None
        try:
            location = [float(value.strip()) for value in raw.split(",")]
            if valid_coordinates(location):
                return location
        except ValueError:
            pass
        print("Enter latitude -90..90, longitude -180..180. Address lookup is not supported yet.")


def collect_manual_request():
    request = empty_request()
    request["location"] = ask_location()
    request["budget_max"] = ask_number("Maximum meal price in SGD (blank for none): ")
    request["walking_time_max"] = ask_number("Maximum walking minutes (blank for none): ")
    request["dietary_requirements"] = ask_tags("Mandatory diets, comma-separated: ")
    request["allergies"] = ask_tags("Allergies, comma-separated: ")
    request["cuisines"] = ask_tags("Preferred cuisines, comma-separated: ")
    request["foods"] = ask_tags("Preferred foods, comma-separated: ")
    request["restaurant_name"] = input("Restaurant name contains (optional): ").strip()
    request["open_now"] = ask_choice("Must be open now? y/n: ", ("y", "n")) == "y"
    if not request["open_now"]:
        raw = input("Open at ISO date/time with offset (optional): ").strip()
        request["requested_time"] = raw or None
    return request


def collect_request(config, profile):
    mode = ask_choice("Search: [m]anual, [a]i, [q]uit: ", ("m", "a", "q"))
    if mode == "q":
        return None, True
    if mode == "a":
        request, error = interpret_request(input("Describe your food request: "), config)
        if error:
            print(error)
            return None, False
    else:
        request = collect_manual_request()
    request, error = prepare_request(request, profile)
    if error:
        print(error)
        debug_log("validation_failed", "error")
        return None, False
    print("Please review all interpreted requirements (including saved safety preferences):")
    print(json.dumps(request, indent=2, ensure_ascii=True))
    if ask_choice("Are all requirements correct? y/n: ", ("y", "n")) != "y":
        print("Search cancelled. Enter your corrected requirements in a new search.")
        return None, False
    debug_log("input_validated")
    return request, False


def display_recommendations(results, exclusions):
    print("Excluded candidates: " + json.dumps(exclusions))
    if not results:
        print("No restaurant meets every requirement with the available evidence. "
              "No requirements were relaxed.")
    for index, result in enumerate(results, 1):
        restaurant, item = result["restaurant"], result["item"]
        print(f"\n{index}. {restaurant['name']} — {restaurant['address']}")
        price = item.get("price")
        print(f"   {item['name']} — " + (f"SGD {price:.2f}" if price is not None else "Price unavailable"))
        walking = result["walking_minutes"]
        print("   Walking: " + (f"{walking:.1f} min" if walking is not None else "unavailable"))
        status = {True: "open", False: "closed", None: "unknown"}[result["open"]]
        print("   Opening status: " + status)
        print("   Ranking contributions: " + json.dumps(result["scores"]))
        print("   Dietary evidence: " + json.dumps(item.get("dietary", {})))
        print("   Allergy evidence: " + json.dumps(item.get("allergen_free", {})))
        print("   Sources: " + ", ".join(sorted(set(restaurant["source_ids"] + item["source_ids"]))))
    if results:
        print("Empty evidence means unverified. Confirm allergy and cross-contact details "
              "with the restaurant. Prices are for the listed item only.")
    debug_log("results_displayed", count=len(results))


def save_search(config, name, request, results, exclusions):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "action": "search",
        "profile": name, "request": request,
        "recommendations": [r["restaurant"]["restaurant_id"] for r in results],
        "exclusions": exclusions,
    }
    error = append_interaction(config["data_dir"], event)
    if error:
        print(error)


def choose_result(config, name, profile, results):
    if not results:
        return profile
    choices = tuple(str(i) for i in range(1, len(results) + 1)) + ("r", "s")
    choice = ask_choice("Select a number, [r]eject all, or [s]kip: ", choices)
    if choice == "s":
        return profile
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), "profile": name,
             "action": "rejected" if choice == "r" else "selected"}
    if choice != "r":
        restaurant = results[int(choice) - 1]["restaurant"]
        event["restaurant_id"] = restaurant["restaurant_id"]
        profile = record_selection(profile, restaurant)
        error = save_profile(config["data_dir"], name, profile)
        if error:
            print(error)
    error = append_interaction(config["data_dir"], event)
    print(error or "Choice saved.")
    return profile


def run_session(config):
    print("BiteFinder CLI — prices in SGD; menu evidence only, no safety guarantees.")
    name = input("Local profile name (blank for default): ").strip() or "default"
    profile, error = load_profile(config["data_dir"], name)
    if error:
        print(error)
        return
    while True:
        request, quit_requested = collect_request(config, profile)
        if quit_requested:
            return
        if request is None:
            continue
        restaurants, warning = load_restaurants(config["data_dir"])
        if warning:
            print(warning)
        restaurants = query_restaurants(restaurants, request["restaurant_name"])
        results, exclusions, error = recommend(restaurants, request, profile)
        if error:
            print(error)
            continue
        display_recommendations(results, exclusions)
        save_search(config, name, request, results, exclusions)
        for field in ("allergies", "dietary_requirements"):
            profile[field] = request[field]
        error = save_profile(config["data_dir"], name, profile)
        if error:
            print(error)
        profile = choose_result(config, name, profile, results)


def run_cli(config):
    try:
        run_session(config)
    except (EOFError, KeyboardInterrupt):
        print("\nBiteFinder closed.")
