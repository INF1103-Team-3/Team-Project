"""BRC workflow for building the cleaned MUIS database."""

from BRC.classes.services.workflows.contracts.base_brc_workflow import BaseBRCWorkflow
from BRC.classes.ai.workflows.cuisine_tagging_workflow import CuisineTaggingWorkflow


class BuildDatabaseWorkflow(BaseBRCWorkflow):
    """Convert a raw MUIS snapshot into the cleaned restaurant database."""

    name = "build_database"

    def __init__(self, snapshot, use_ai=True):
        self._snapshot = snapshot
        self._use_ai = use_ai
        self._cache = None
        self._save_cache = None

    def announce(self, data, logic, report):
        report(
            f"IO Manager: loaded {len(self._snapshot.listings)} "
            "complete MUIS restaurant listings.")
        self._cache = data.load_cuisine_cache()
        recovered = data.bootstrap_cuisine_cache(
            self._snapshot, self._cache)
        if recovered:
            data.save_cuisine_cache(self._cache)
            report(
                f"Data Manager: recovered {recovered} cuisine tags "
                "from the existing cleaned database.")
        self._save_cache = data.save_cuisine_cache
        self._logic = logic
        self._report = report

    def ask_ai(self, ai):
        if not self._use_ai:
            tags, _pending = self._logic.prepare_cuisine_tags(
                self._snapshot.listings, self._cache)
            if self._save_cache:
                self._save_cache(self._cache)
            return tags
        return CuisineTaggingWorkflow(self._report).run(
            self._snapshot.listings, self._cache, ai, self._logic,
            self._save_cache)

    def apply_rules(self, logic, cuisines):
        return logic.build_database(self._snapshot, cuisines)

    def save(self, data, database, report, output):
        data.save_clean_database(database)
        report(
            f"Data Manager: saved {len(database)} restaurants to "
            f"{data.clean_path}.")
        return database.to_list()
