from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from shared import debug_log

import data_manager
import io_manager
import logic_manager
import places_client
from ai_manager import AIManager

log = logging.getLogger("restaurant_finder")


def configure_logging() -> None:
    debug_log.configure_python_logging()


def run_search(ai: AIManager, maps_key: str) -> bool:
    """One search from input to saved results. Returns True if records were saved."""
    request = io_manager.collect_search_request()
    io_manager.show_message(
        f"\nFinding {request.food_type} restaurants near {request.location}..."
    )

    try:
        _, candidates = places_client.fetch_candidates(request, maps_key)
    except places_client.PlacesError as exc:
        log.error("Places lookup failed: %s", exc)
        io_manager.show_error(str(exc))
        return False

    if not candidates:
        io_manager.show_error("No restaurants found. Try a different location.")
        return False

    # Every record passes through the AI Manager, then the Logic Manager decides.
    enriched = ai.enrich(candidates)
    ai_failed = sum(1 for r in enriched if r.get("ai_status") != "ok")
    directory = (
        data_manager.load_halal_directory() if request.food_type == "halal" else []
    )
    processed = logic_manager.process(
        enriched, request, logic_manager.build_directory_index(directory)
    )

    saved = data_manager.save_records(processed)
    io_manager.show_results(
        shown=logic_manager.select_for_display(processed),
        request=request,
        rejected_count=logic_manager.count_rejected(processed),
        matching_count=logic_manager.count_matching(processed),
        ai_failed=ai_failed,
        saved=saved,
        directory_count=len(directory),
        directory_updated=data_manager.halal_directory_updated() if directory else None,
    )
    return saved


def main() -> int:
    configure_logging()
    load_dotenv()

    gemini_key = os.getenv("GEMINI_API_KEY")
    maps_key = os.getenv("GOOGLE_MAPS_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    missing = [
        name
        for name, value in (("GEMINI_API_KEY", gemini_key), ("GOOGLE_MAPS_API_KEY", maps_key))
        if not value
    ]
    if missing:
        io_manager.show_error(
            f"Missing {', '.join(missing)}. Add to a .env file next to this script."
        )
        return 1

    history = data_manager.load_records()  # load everything saved on startup
    directory = data_manager.load_halal_directory()
    io_manager.show_welcome(
        len(history),
        len(directory),
        data_manager.halal_directory_updated() if directory else None,
    )

    ai = AIManager(api_key=gemini_key, model=model)

    try:
        while True:
            choice = io_manager.ask_menu()
            if choice == "quit":
                break
            try:
                run_search(ai, maps_key)
            except Exception:  # keep the menu alive whatever goes wrong
                log.exception("Unexpected error during %s", choice)
                io_manager.show_error(
                    "Something went wrong. Details are in logs/bitefinder.log."
                )
    except (KeyboardInterrupt, EOFError):
        io_manager.show_message("")

    io_manager.show_message("Goodbye!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
