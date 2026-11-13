"""BRC workflow for independently verifying restaurant records."""

from BRC.classes.services.workflows.contracts.base_brc_workflow import BaseBRCWorkflow
from BRC.classes.ai.workflows.outlet_matching_workflow import OutletMatchingWorkflow


class CheckRestaurantsWorkflow(BaseBRCWorkflow):
    """Check restaurant records against authoritative MUIS outlets."""

    name = "check_restaurants"

    def __init__(self, records, single, database):
        self._records = records
        self._single = single
        self._database = database
        self._candidates = [
            database.candidates_for(record) for record in records]
        self._exact = [None] * len(records)

    def announce(self, data, logic, report):
        self._report = report
        report(
            f"IO Manager: accepted {len(self._records)} restaurant(s).")
        self._exact = logic.exact_matches(
            self._records, self._candidates)

    def ask_ai(self, ai):
        return OutletMatchingWorkflow(self._report).run(
            self._records, self._candidates, self._exact, ai)

    def apply_rules(self, logic, chosen_certificates):
        return logic.check_restaurants(
            self._records, self._database, chosen_certificates)

    def save(self, data, results, report, output):
        shaped = results[0] if self._single else results
        data.save_checked_result(shaped, self._single, output)
        report(
            "Data Manager: saved checked output to "
            f"{data.result_path(self._single, output)}.")
        report(
            f"Data Manager: updated cache at {data.checked_cache_path}.")
        return shaped
