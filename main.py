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
    halal_list = data_manager.load_halal_certified()
    print(f"[startup] catalog: {len(catalog)} rows · "
          f"halal-certified: {len(halal_list)} rows")

    while True:
        choice = input("\n1 = new search, q = quit :> ").strip().lower()
        if choice == "q":
            print("Goodbye!")
            break
        if choice != "1":
            continue

        record = io_manager.get_user_requirements()

        # --- AI layer: skip if the input is simple enough to parse directly ---
        if ai_manager.needs_ai(record):
            ok, req, ai_model = ai_manager.call_ai(record)
            if not ok:
                io_manager.print_error(req)
                print("  [fallback] AI unavailable — using rule-based parsing.")
                req = ai_manager.build_req_without_ai(record)
                ai_model = "rule-based (AI unavailable)"
        else:
            req = ai_manager.build_req_without_ai(record)
            ai_model = "rule-based (no AI needed)"

        io_manager.print_parsed(req)
        io_manager.print_ai_model(ai_model)

        origin = data_manager.geocode_location(record["location"])
        if origin is None:
            io_manager.print_error("Could not find that location — try a Singapore "
                                   "postal code or a landmark name.")
            continue

        candidates = data_manager.build_candidates(origin, req, catalog,
                                                   halal_list=halal_list)
        if not candidates:
            io_manager.print_error("No restaurants found near that location. Try another.")
            continue

        results = logic_manager.rank_restaurants(candidates, req)
        io_manager.print_results(results)

        chosen = io_manager.choose_restaurant(results)
        route_link = None
        if chosen is not None:
            if chosen.get("lat") is None:
                io_manager.print_error("No coordinates stored for that restaurant "
                                       "— add lat/lng in the catalog.")
            else:
                dest = (chosen["lat"], chosen["lng"])
                route = data_manager.get_walking_route(origin, dest)
                route_link = data_manager.build_maps_link(origin, dest)
                io_manager.print_route(chosen["name"], route, route_link)

        data_manager.save_history({
            "ai_model": ai_model,
            "input": record,
            "parsed": req,
            "mode": "live-google" if config.USE_LIVE_GOOGLE else "offline-catalog",
            "origin": list(origin),
            "top_matches": [m["restaurant"]["name"] for m in results["matches"]],
            "route_link": route_link,
        })


if __name__ == "__main__":
    run_bitefinder()