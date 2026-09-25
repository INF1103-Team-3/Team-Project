"""Wires the four managers together. User -> io -> ai -> logic -> data."""
import config
import io_manager
import ai_manager
import logic_manager
import data_manager


def run_bitefinder():
    io_manager.print_welcome()

    problems = ai_manager.validate_chain()
    if problems:
        io_manager.print_error("MODEL_CHAIN has placeholder/broken entries: "
                               + "; ".join(problems))
        return

    catalog = data_manager.load_restaurants()
    if not catalog:
        io_manager.print_error(f"No catalog data found at {config.RESTAURANT_FILE}")
        return

    while True:
        choice = input("\n1 = new search, q = quit :> ").strip().lower()
        if choice == "q":
            print("Goodbye!")
            break
        if choice != "1":
            continue

        record = io_manager.get_user_requirements()          # 1. INPUT LAYER

        ok, req, ai_model = ai_manager.call_ai(record)       # 2. AI LAYER
        if not ok:
            io_manager.print_error(req)
            continue
        io_manager.print_parsed(req)
        io_manager.print_ai_model(ai_model)

        origin = data_manager.geocode_location(record["location"])   # 4a. DATA
        if origin is None:
            io_manager.print_error("Could not find that location — try a Singapore "
                                   "postal code or a landmark name.")
            continue

        candidates = data_manager.build_candidates(origin, req, catalog)  # 4b. DATA
        if not candidates:
            io_manager.print_error(f"No restaurants found near {origin} — try another location.")
            continue

        results = logic_manager.rank_restaurants(candidates, req)    # 3. LOGIC LAYER
        io_manager.print_results(results)

        chosen = io_manager.choose_restaurant(results)               # on-demand route
        route_link = None
        if chosen is not None:
            if chosen.get("lat") is None:
                io_manager.print_error("No coordinates stored for that restaurant "
                                       "— add lat/lng in the catalog.")
            else:
                dest = (chosen["lat"], chosen["lng"])
                route = data_manager.get_route(origin, dest, record["mode"])
                route_link = data_manager.build_maps_link(origin, dest, record["mode"])
                io_manager.print_route(chosen["name"], route, route_link, record["mode"])

        data_manager.save_history({                          # 4c. DATA: persist
            "input": record,
            "parsed": req,
            "mode": "live-google" if config.USE_LIVE_GOOGLE else "offline-catalog",
            "travel_mode": record["mode"],
            "origin": list(origin),
            "ai_model": ai_model,
            "top_matches": [m["restaurant"]["name"] for m in results["matches"]],
            "route_link": route_link,
        })


if __name__ == "__main__":
    run_bitefinder()
