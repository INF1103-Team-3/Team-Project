"""Run the BRC database builder or restaurant checker.

    python -m BRC.main                      interactive menu
    python -m BRC.main --input file.json    check restaurants from a file
    python -m BRC.main --stdin --stdout     check JSON from stdin, print JSON
    python -m BRC.main --stdout             build the database, print it
"""

import argparse
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from BRC.ai_manager import AIManager, GeminiClient
from BRC.data_manager import (CLEAN_DATABASE_PATH, RAW_MUIS_PATH, DataManager,
                              DataUnavailableError, JsonFile)
from BRC.io_manager import NO_INPUT, ConsoleProgress, IOManager
from BRC.logic_manager import LogicManager
from BRC.models import RestaurantRecord
from shared import debug_log


class Workflow(ABC):
    """One BRC job. run() is the same for every job (IO -> AI -> Logic -> Data);
    each subclass fills in what its AI, rules and save steps do."""

    name = ""

    def run(self, ai, logic, data, report, output=None):
        self.announce(data, logic, report)
        report("AI Manager: normalizing restaurant information...")
        proposals = self.ask_ai(ai)
        report("Logic Manager: validating AI output against MUIS evidence...")
        result = self.apply_rules(logic, proposals)
        report("Data Manager: saving the validated result...")
        return self.save(data, result, report, output)

    @abstractmethod
    def announce(self, data, logic, report):
        """Say what was loaded and prepare anything the AI step needs."""

    @abstractmethod
    def ask_ai(self, ai):
        """Get proposals from the AI Manager."""

    @abstractmethod
    def apply_rules(self, logic, proposals):
        """Let the Logic Manager accept or reject the proposals."""

    @abstractmethod
    def save(self, data, result, report, output):
        """Save the result and return what the caller receives."""


class BuildDatabaseWorkflow(Workflow):
    """MUIS download -> AI cuisine tags -> current outlets only -> cleaned database."""

    name = "build_database"

    def __init__(self, snapshot):
        self._snapshot = snapshot
        self._cache = None
        self._save_cache = None

    def announce(self, data, logic, report):
        report(f"IO Manager: loaded {len(self._snapshot.listings)} "
               "complete MUIS restaurant listings.")
        self._cache = data.load_cuisine_cache()
        recovered = data.bootstrap_cuisine_cache(self._snapshot, self._cache)
        if recovered:
            data.save_cuisine_cache(self._cache)
            report(f"Data Manager: recovered {recovered} cuisine tags "
                   "from the existing cleaned database.")
        self._save_cache = data.save_cuisine_cache

    def ask_ai(self, ai):
        return ai.tag_cuisines(self._snapshot.listings, self._cache, self._save_cache)

    def apply_rules(self, logic, cuisines):
        return logic.build_database(self._snapshot, cuisines)

    def save(self, data, database, report, output):
        data.save_clean_database(database)
        report(f"Data Manager: saved {len(database)} restaurants to {data.clean_path}.")
        return database.to_list()


class CheckRestaurantsWorkflow(Workflow):
    """Restaurants -> candidate outlets -> AI choice -> MUIS evidence check -> results.

    Aggregation: it uses a HalalDatabase that was loaded elsewhere.
    """

    name = "check_restaurants"

    def __init__(self, records, single, database):
        self._records = records
        self._single = single                    # one object in, one object out
        self._database = database
        self._candidates = [database.candidates_for(record) for record in records]
        self._exact = [None] * len(records)

    def announce(self, data, logic, report):
        report(f"IO Manager: accepted {len(self._records)} restaurant(s).")
        self._exact = logic.exact_matches(self._records, self._candidates)

    def ask_ai(self, ai):
        return ai.match_outlets(self._records, self._candidates, self._exact)

    def apply_rules(self, logic, chosen_certificates):
        return logic.check_restaurants(self._records, self._database, chosen_certificates)

    def save(self, data, results, report, output):
        shaped = results[0] if self._single else results
        data.save_checked_result(shaped, self._single, output)
        report(f"Data Manager: saved checked output to "
               f"{data.result_path(self._single, output)}.")
        report(f"Data Manager: updated cache at {data.checked_cache_path}.")
        return shaped


class BRCApplication:
    """Picks the workflow for the input and runs it.

    Composition: it creates and owns its LogicManager.
    Aggregation: the IO, Data and AI managers can be passed in (the tests pass
    a temporary data folder and a fake AI); otherwise defaults are created.
    """

    _shared_ai = None          # reused so Gemini request spacing carries over
    _shared_settings = None

    def __init__(self, ai=None, io=None, data=None, verbose=False, scrape_progress=None):
        self._ai = ai
        self._io = io or IOManager()
        self._data = data or DataManager()
        self._logic = LogicManager()
        self._verbose = verbose
        self._scrape_progress = scrape_progress

    def report(self, message):
        """Status messages are only shown in interactive mode."""
        if self._verbose:
            self._io.display_status(message, error=True)

    def run(self, value=NO_INPUT, output=None):
        """Build the database (value=NO_INPUT) or check restaurant JSON."""
        self.report("IO Manager: validating input and loading BRC data...")
        workflow = self._choose_workflow(value)
        debug_log.debug_log(f"BRC IO selected {workflow.name}.", "INFO",
                            "BRC.io_manager.prepare_workflow")
        ai = self._ai or self.default_ai()
        ai.set_reporter(self.report)
        result = workflow.run(ai, self._logic, self._data, self.report, output)
        debug_log.debug_log("BRC workflow saved its validated result.", "INFO",
                            "BRC.data_manager")
        return result

    def _choose_workflow(self, value):
        if value is NO_INPUT:
            return BuildDatabaseWorkflow(self._load_or_download_snapshot())
        records, single = self._io.validate_restaurants(value)
        database = self._load_or_build_database()
        return CheckRestaurantsWorkflow([RestaurantRecord(r) for r in records], single, database)

    def _load_or_download_snapshot(self):
        """Use the saved MUIS download if it is valid and fresh, otherwise scrape again."""
        try:
            return self._data.load_raw_snapshot()
        except (DataUnavailableError, OSError):
            from BRC.scraper import MuisScraper
            return MuisScraper(self._data, progress=self._scrape_progress).scrape_all()

    def _load_or_build_database(self):
        """Checking needs the cleaned database, so build it first if it is missing."""
        try:
            return self._data.load_clean_database()
        except (DataUnavailableError, OSError):
            self.report("IO Manager: cleaned halal database is missing; building it first.")
            self.run()
            return self._data.load_clean_database()

    @classmethod
    def default_ai(cls):
        """A Gemini-backed AI manager, reused until the API key or model changes."""
        settings = (os.getenv("GEMINI_API_KEY"),
                    os.getenv("BRC_GEMINI_MODEL", "gemini-3.5-flash-lite"))
        if cls._shared_ai is None or settings != cls._shared_settings:
            cls._shared_ai = AIManager(GeminiClient(*settings))
            cls._shared_settings = settings
        return cls._shared_ai

    @classmethod
    def run_once(cls, value=NO_INPUT, ai=None, output=None, raw_path=RAW_MUIS_PATH,
                 clean_path=CLEAN_DATABASE_PATH, cuisine_cache_path=None,
                 verbose=False, scrape_progress=None):
        """Same parameters as the Phase 1 run() function."""
        data = DataManager(raw_path=raw_path, clean_path=clean_path,
                           cuisine_cache_path=cuisine_cache_path)
        return cls(ai, data=data, verbose=verbose,
                   scrape_progress=scrape_progress).run(value, output)


class CommandLine:
    """Reads command-line options, runs BRC, and returns an exit code."""

    def __init__(self, io=None):
        self._io = io or IOManager()

    def run(self, argv=None):
        arguments = list(sys.argv[1:] if argv is None else argv)
        if arguments[:1] == ["check"]:          # optional word used by the team launcher
            arguments = arguments[1:]
        interactive = not arguments            # no options: show the menu
        parser = argparse.ArgumentParser(description="Build or use the BRC halal database.")
        inputs = parser.add_mutually_exclusive_group()
        inputs.add_argument("--input", type=Path)
        inputs.add_argument("--stdin", action="store_true")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--stdout", action="store_true")
        args = parser.parse_args(arguments)

        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        debug_log.configure_python_logging()
        token = debug_log.start_trace()
        progress = ConsoleProgress() if interactive else None
        try:
            if interactive:
                value = self._io.collect_interactive_input()
                self._io.display_status("", error=True)
            elif args.input or args.stdin:
                value = self._io.read_json_input(args.input)
            else:
                value = NO_INPUT
            app = BRCApplication(io=self._io, verbose=interactive, scrape_progress=progress)
            result = app.run(value, args.output)
            if args.stdout:
                self._io.write_raw(JsonFile.format_json(result, compact_hours=True))
            elif value is NO_INPUT:
                self._io.display_status(f"Built {len(result)} verified halal restaurant records.")
            else:
                self._io.display_result(result)
            return 0
        except Exception as exc:               # show a message, not a traceback
            debug_log.debug_log(f"BRC failed: {type(exc).__name__}: {exc}", "ERROR", "BRC.main")
            self._io.display_status(f"BRC failed: {exc}", error=True)
            return 1
        finally:
            if progress:
                progress.finish()
            debug_log.end_trace(token)

    @classmethod
    def main(cls, argv=None):
        return cls().run(argv)


# Phase 1 names, so the team's root main.py can still call BRC.main.run(...)
# and BRC.main.main(...). Both point to class methods.
run = BRCApplication.run_once
main = CommandLine.main

if __name__ == "__main__":
    raise SystemExit(CommandLine.main())
