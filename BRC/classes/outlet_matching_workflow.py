"""Coordinate outlet AI requests while preserving exact matches and failures."""

from BRC.classes.ai_response_error import AIResponseError
from BRC.classes.ai_service_error import AIServiceError


class OutletMatchingWorkflow:
    """Keep short-circuit and partial-job policy outside the AI Manager."""

    def __init__(self, report):
        self._report = report

    def run(self, records, candidate_groups, exact_matches, ai):
        """Return the selected certificate for each restaurant, or None."""
        chosen = []
        ai_available = True
        for number, (record, candidates, exact) in enumerate(
                zip(records, candidate_groups, exact_matches), 1):
            self._report(
                f"AI: checking restaurant {number} of {len(records)} "
                f"({record.to_dict().get('name', 'unknown')})")
            if not candidates or exact is not None or not ai_available:
                chosen.append(exact)
                continue
            try:
                chosen.append(
                    ai.propose_match(number, record, candidates))
            except AIResponseError as error:
                self._report(
                    f"AI: no valid answer for restaurant {number} "
                    f"({error}); it is marked not verified.")
                chosen.append(None)
            except AIServiceError as error:
                self._report(
                    f"AI: Gemini is unavailable ({error}); the remaining "
                    "restaurants are marked not verified.")
                chosen.append(None)
                ai_available = False
        return chosen
