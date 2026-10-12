"""Run the BRC database builder or restaurant checker."""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from BRC import ai_manager, data_manager, io_manager, logic_manager, scraper
from shared import debug_log

_DEFAULT_AI = None
_DEFAULT_AI_SETTINGS = None


def default_ai_manager():
    """Reuse one paced Gemini client across database and outlet checks."""
    global _DEFAULT_AI, _DEFAULT_AI_SETTINGS
    settings = (
        os.getenv("GEMINI_API_KEY"),
        os.getenv("BRC_GEMINI_MODEL", "gemini-3.5-flash-lite"),
    )
    if _DEFAULT_AI is None or settings != _DEFAULT_AI_SETTINGS:
        _DEFAULT_AI = ai_manager.AIManager(*settings)
        _DEFAULT_AI_SETTINGS = settings
    return _DEFAULT_AI

def run(value=io_manager.NO_INPUT, *, ai=None, output=None,
        raw_path=data_manager.RAW_MUIS_PATH,
        clean_path=data_manager.CLEAN_DATABASE_PATH,
        cuisine_cache_path=None,
        verbose=False, scrape_progress=None):
    """Execute IO -> AI -> Logic -> Data and return the resulting value."""
    def report(message):
        if verbose:
            print(message, file=sys.stderr)

    report("IO Manager: validating input and loading BRC data...")
    try:
        context = io_manager.prepare_workflow(
            value, raw_path=raw_path, clean_path=clean_path,
            scrape_progress=scrape_progress)
    except io_manager.CleanDatabaseRequired:
        report("IO Manager: cleaned halal database is missing; building it first.")
        run(ai=ai, raw_path=raw_path, clean_path=clean_path, verbose=verbose,
            cuisine_cache_path=cuisine_cache_path,
            scrape_progress=scrape_progress)
        context = io_manager.prepare_workflow(
            value, raw_path=raw_path, clean_path=clean_path,
            scrape_progress=scrape_progress)
    context["report"] = report
    debug_log.debug_log(
        f"BRC IO selected {context['scenario']}.", "INFO",
        "BRC.io_manager.prepare_workflow")
    if context["scenario"] == "build_database":
        count = len(context["raw_snapshot"]["listings"])
        report(f"IO Manager: loaded {count} complete MUIS restaurant listings.")
        cache_path = (Path(cuisine_cache_path) if cuisine_cache_path else
                      data_manager.CUISINE_CACHE_PATH
                      if Path(raw_path) == data_manager.RAW_MUIS_PATH else
                      Path(clean_path).with_name("cuisine_tags_cache.json"))
        cuisine_cache = data_manager.load_cuisine_cache(cache_path)
        bootstrapped = data_manager.bootstrap_cuisine_cache(
            context["raw_snapshot"], Path(clean_path), cuisine_cache)
        if bootstrapped:
            data_manager.save_cuisine_cache(cuisine_cache, cache_path)
            report(f"Data Manager: recovered {bootstrapped} cuisine tags "
                   "from the existing cleaned database.")
        context["cuisine_cache"] = cuisine_cache
        context["save_cuisine_cache"] = (
            lambda tags: data_manager.save_cuisine_cache(tags, cache_path))
    else:
        report(f"IO Manager: accepted {len(context['records'])} restaurant(s).")

    if ai is None:
        ai = default_ai_manager()
    report("AI Manager: normalizing restaurant information...")
    proposals = ai.process(context)

    report("Logic Manager: validating AI output against MUIS evidence...")
    result = logic_manager.process(context, proposals)

    report("Data Manager: saving the validated result...")
    if context["scenario"] == "build_database":
        data_manager.save_clean_database(
            result, context["raw_snapshot"], Path(clean_path))
        report(f"Data Manager: saved {len(result)} restaurants to {clean_path}.")
    else:
        shaped = result[0] if context["single"] else result
        data_manager.save_checked_result(
            shaped, single=context["single"], output=output)
        result = shaped
        destination = (Path(output) if output else
                       data_manager.SINGLE_RESULT_PATH if context["single"]
                       else data_manager.BATCH_RESULT_PATH)
        report(f"Data Manager: saved checked output to {destination}.")
        report(f"Data Manager: updated cache at {data_manager.CHECK_CACHE_PATH}.")
    debug_log.debug_log(
        "BRC workflow saved its validated result.", "INFO", "BRC.data_manager")
    return result

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build or use the BRC halal database.")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path)
    inputs.add_argument("--stdin", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stdout", action="store_true")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["check"]:
        arguments = arguments[1:]
    interactive = not arguments
    args = parser.parse_args(arguments)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    debug_log.configure_python_logging()
    token = debug_log.start_trace()
    display = scraper._ConsoleProgress() if interactive else None
    try:
        if interactive:
            value = io_manager.collect_interactive_input()
            print("", file=sys.stderr)
        else:
            value = (io_manager.read_json_input(args.input)
                     if args.input or args.stdin else io_manager.NO_INPUT)
        result = run(
            value, output=args.output, verbose=interactive,
            scrape_progress=display)
        if args.stdout:
            sys.stdout.write(data_manager.format_json(
                result, compact_hours=True))
        elif value is io_manager.NO_INPUT:
            print(f"Built {len(result)} verified halal restaurant records.")
        else:
            print(f"Checked {1 if isinstance(result, dict) else len(result)} "
                  "restaurant(s).")
        return 0
    except Exception as exc:
        debug_log.debug_log(
            f"BRC failed: {type(exc).__name__}: {exc}", "ERROR", "BRC.main")
        print(f"BRC failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if display:
            display.finish()
        debug_log.end_trace(token)

if __name__ == "__main__":
    raise SystemExit(main())
