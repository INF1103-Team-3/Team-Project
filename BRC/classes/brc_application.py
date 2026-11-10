"""Composition root for the BRC four-manager application flow."""

import os

from BRC.classes.ai_manager import AIManager
from BRC.classes.build_database_workflow import BuildDatabaseWorkflow
from BRC.classes.check_restaurants_workflow import CheckRestaurantsWorkflow
from BRC.classes.data_manager import (
    CLEAN_DATABASE_PATH,
    RAW_MUIS_PATH,
    DataManager,
)
from BRC.classes.data_unavailable_error import DataUnavailableError
from BRC.classes.fallback_ai_client import FallbackAIClient
from BRC.classes.io_manager import NO_INPUT, IOManager
from BRC.classes.logic_manager import LogicManager
from BRC.models import RestaurantRecord
from shared import debug_log


class BRCApplication:
    """Coordinate BRC managers without absorbing their responsibilities."""

    _shared_ai = None
    _shared_settings = None

    def __init__(self, ai=None, io=None, logic=None, data=None,
                 verbose=False, scrape_progress=None):
        self._ai = ai
        self._io = io or IOManager()
        self._logic = logic or LogicManager()
        self._data = data or DataManager()
        self._verbose = verbose
        self._scrape_progress = scrape_progress

    def report(self, message):
        if self._verbose:
            self._io.display_status(message, error=True)

    def run(self, value=NO_INPUT, output=None):
        self.report("IO Manager: validating input and loading BRC data...")
        workflow = self._choose_workflow(value)
        debug_log.debug_log(
            f"BRC IO selected {workflow.name}.",
            "INFO", "BRC.io_manager.prepare_workflow")
        ai = self._ai or self.default_ai()
        ai.set_reporter(self.report)
        result = workflow.run(
            ai, self._logic, self._data, self.report, output)
        debug_log.debug_log(
            "BRC workflow saved its validated result.",
            "INFO", "BRC.data_manager")
        return result

    def _choose_workflow(self, value):
        if value is NO_INPUT:
            return BuildDatabaseWorkflow(
                self._load_or_download_snapshot())
        records, single = self._io.validate_restaurants(value)
        database = self._load_or_build_database()
        return CheckRestaurantsWorkflow(
            [RestaurantRecord(record) for record in records],
            single, database)

    def _load_or_download_snapshot(self):
        try:
            return self._data.load_raw_snapshot()
        except (DataUnavailableError, OSError):
            from BRC.scraper import MuisScraper
            return MuisScraper(
                self._data, progress=self._scrape_progress).scrape_all()

    def _load_or_build_database(self):
        try:
            return self._data.load_clean_database()
        except (DataUnavailableError, OSError):
            self.report(
                "IO Manager: cleaned halal database is missing; "
                "building it first.")
            self.run()
            return self._data.load_clean_database()

    @classmethod
    def default_ai(cls):
        from BRC import ai_manager as ai_facade

        settings = ai_facade.create_manager(
            os.getenv("GEMINI_API_KEY"),
            os.getenv("BRC_GEMINI_MODEL", "gemini-3.5-flash-lite"))
        fingerprint = (
            tuple((item["provider"], item["model"])
                  for item in settings["providers"]),
            settings["api_key"], settings["openrouter_api_key"],
            settings["groq_api_key"], settings["timeout_seconds"],
            settings["chain_timeout_seconds"],
        )
        if cls._shared_ai is None or fingerprint != cls._shared_settings:
            client = FallbackAIClient(
                settings,
                ai_facade._call_gemini,
                ai_facade._call_chat_completions)
            cls._shared_ai = AIManager(client)
            cls._shared_settings = fingerprint
        return cls._shared_ai

    @classmethod
    def run_once(cls, value=NO_INPUT, ai=None, output=None,
                 raw_path=RAW_MUIS_PATH, clean_path=CLEAN_DATABASE_PATH,
                 cuisine_cache_path=None, verbose=False,
                 scrape_progress=None):
        data = DataManager(
            raw_path=raw_path,
            clean_path=clean_path,
            cuisine_cache_path=cuisine_cache_path)
        return cls(
            ai, data=data, verbose=verbose,
            scrape_progress=scrape_progress).run(value, output)
