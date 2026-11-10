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

    KEYWORDS = {
        "malay": "malay", "nasi": "malay", "chicken rice": "chinese",
        "chinese": "chinese", "indian": "indian", "biryani": "indian",
        "japanese": "japanese", "sushi": "japanese", "korean": "korean",
        "thai": "thai", "western": "western", "pizza": "italian",
    }

    def __init__(self, client):
        self._client = client
        self._report = lambda message: None

    def set_reporter(self, report):
        self._report = report
        self._client.set_reporter(report)

    def tag_cuisines(self, listings, cache, save_cache=None):
        """Return cuisine tags for every listing in the original order."""
        tags, pending = self._tags_without_ai(listings, cache)
        if len(pending) < len(listings):
            self._report(
                f"AI: reused or derived {len(listings) - len(pending)} "
                f"cached cuisine tags; {len(pending)} still need AI.")
        if save_cache:
            save_cache(cache)
        size = self._batch_size()
        for start in range(0, len(pending), size):
            batch = pending[start:start + size]
            self._report(
                "AI: tagging cuisines for restaurants "
                f"{start + 1}–{start + len(batch)} of {len(pending)} "
                f"(currently {batch[0][1].name or 'unknown'})")
            try:
                answers = self._tag_batch(batch)
            except AIResponseError as error:
                self._report(
                    "AI: skipped this batch after invalid responses "
                    f"({error}); it will be retried on the next build.")
                continue
            except AIServiceError as error:
                self._report(
                    f"AI: Gemini is unavailable ({error}); "
                    f"{len(pending) - start} restaurants were left untagged "
                    "and will be retried next build.")
                break
            for index, cuisines in answers.items():
                tags[index] = cuisines
                cache.put(listings[index], cuisines)
            if save_cache:
                save_cache(cache)
        return tags

    def _tags_without_ai(self, listings, cache):
        tags, pending = [[] for _ in listings], []
        for index, listing in enumerate(listings):
            cached = cache.get(listing)
            text = f"{listing.name or ''} {listing.category or ''}".casefold()
            keyword_tags = sorted({
                tag for word, tag in self.KEYWORDS.items() if word in text})
            if cached is not None:
                tags[index] = cached
            elif keyword_tags:
                tags[index] = keyword_tags
                cache.put(listing, keyword_tags)
            else:
                pending.append((index, listing))
        return tags, pending

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
                    self._ask_for_match(number, record, candidates))
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
        if hasattr(self._client, "request_validated"):
            return self._client.request_validated(prompt, read_answer)
        try:
            return read_answer(self._client.call_api(prompt))
        except AIResponseError:
            return read_answer(self._client.call_api(prompt))

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
