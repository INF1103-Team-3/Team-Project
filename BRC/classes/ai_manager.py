"""BRC AI Manager: prompt, response, and AI-failure ownership."""

import json
import os
import re

from BRC.classes.ai_response_error import AIResponseError
from BRC.classes.ai_service_error import AIServiceError


CUISINES = (
    "chinese", "malay", "indian", "peranakan", "indonesian", "thai",
    "vietnamese", "filipino", "japanese", "korean", "western", "italian",
    "french", "american", "mexican", "turkish", "middle eastern",
    "mediterranean", "fusion", "lebanese",
)

CUISINE_PROMPT = (
    "Tag every restaurant with zero or more allowed cuisines. Generic "
    "words such as restaurant are not cuisines. Return only a JSON "
    "array of {index,cuisines}. Allowed: " + ", ".join(CUISINES) + "\n")

MATCH_PROMPT = (
    "Select the exact same outlet or null. Branch and unit must agree. "
    "Return only {\"certificate_number\": string|null}.\n")


class AIManager:
    """Build BRC prompts, call an injected client, and validate replies."""

    def __init__(self, client):
        self._client = client
        self._report = lambda message: None

    def set_reporter(self, report):
        self._report = report
        self._client.set_reporter(report)

    def tag_cuisines(self, listings, cache, save_cache=None):
        """Legacy entry point; production jobs use CuisineTaggingWorkflow."""
        from BRC.classes.cuisine_tagging_workflow import CuisineTaggingWorkflow
        from BRC.classes.logic_manager import LogicManager
        return CuisineTaggingWorkflow(self._report).run(
            listings, cache, self, LogicManager(), save_cache)

    def tag_batch(self, batch):
        """Return validated cuisine proposals for one indexed batch."""
        return self._tag_batch(batch)

    def batch_size(self):
        return self._batch_size()

    def _tag_batch(self, batch):
        rows = [{
            "index": index,
            "name": listing.name,
            "category": listing.category,
        } for index, listing in batch]
        expected = {index for index, _ in batch}
        return self._ask(
            CUISINE_PROMPT + json.dumps(rows),
            lambda raw: self._read_cuisines(raw, expected))

    def _read_cuisines(self, raw, expected):
        rows = self.parse_response(raw)
        if not self.validate_response(rows, expected_ids=expected):
            raise AIResponseError(
                "BRC AI omitted or duplicated cuisine rows.")
        answers = {}
        for row in rows:
            if (not isinstance(row, dict)
                    or set(row) != {"index", "cuisines"}
                    or row["index"] not in expected
                    or not isinstance(row["cuisines"], list)):
                raise AIResponseError(
                    "BRC AI returned invalid cuisine tags.")
            allowed = []
            for tag in row["cuisines"]:
                normalized = (
                    re.sub(r"\s+", " ", tag.strip().casefold())
                    if isinstance(tag, str) else "")
                if normalized in CUISINES and normalized not in allowed:
                    allowed.append(normalized)
            answers[row["index"]] = allowed
        return answers

    def match_outlets(self, records, candidate_groups, exact_matches):
        """Legacy entry point; delegate whole-job orchestration."""
        from BRC.classes.outlet_matching_workflow import OutletMatchingWorkflow
        return OutletMatchingWorkflow(self._report).run(
            records, candidate_groups, exact_matches, self)

    def propose_match(self, number, record, candidates):
        """Return one schema-validated outlet proposal."""
        return self._ask_for_match(number, record, candidates)

    def _ask_for_match(self, number, record, candidates):
        payload = {
            "restaurant": record.to_dict(),
            "candidates": [outlet.to_dict() for outlet in candidates],
        }
        allowed = {outlet.certificate.number for outlet in candidates}
        return self._ask(
            MATCH_PROMPT + json.dumps(payload),
            lambda raw: self._read_match(raw, number, allowed))

    def _read_match(self, raw, number, allowed):
        answer = self.parse_response(raw, object_ok=True)
        if not self.validate_response(
                answer, object_keys={"certificate_number"}):
            raise AIResponseError(
                f"BRC AI returned an invalid match for restaurant {number}.")
        certificate = answer["certificate_number"]
        if certificate is not None and certificate not in allowed:
            raise AIResponseError(
                f"BRC AI invented a match for restaurant {number}.")
        return certificate

    def _ask(self, prompt, read_answer):
        return self._client.request_validated(prompt, read_answer)

    @staticmethod
    def parse_response(raw, object_ok=False):
        try:
            value = json.loads(
                re.sub(r"```(?:json)?", "", raw).strip())
        except (TypeError, json.JSONDecodeError) as error:
            raise AIResponseError(
                "BRC AI response is not valid JSON.") from error
        if object_ok and isinstance(value, dict):
            return value
        if not isinstance(value, list):
            raise AIResponseError("BRC AI response has the wrong shape.")
        return value

    @staticmethod
    def validate_response(data, expected_ids=None, object_keys=None):
        if object_keys is not None:
            return isinstance(data, dict) and set(data) == set(object_keys)
        if not isinstance(data, list):
            return False
        if expected_ids is None:
            return True
        indexes = [
            row.get("index") for row in data if isinstance(row, dict)]
        return (
            len(data) == len(expected_ids)
            and set(indexes) == set(expected_ids))

    @staticmethod
    def _batch_size():
        try:
            size = int(os.getenv("BRC_AI_BATCH_SIZE", "100"))
        except ValueError:
            size = 100
        return min(max(size, 1), 200)
