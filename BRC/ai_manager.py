"""AI Manager: sends prompts to Gemini and checks its answers.

Two jobs:
  tag_cuisines  - which cuisines each MUIS outlet serves (database build)
  match_outlets - which MUIS outlet, if any, a restaurant is (restaurant check)
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod

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


class AIResponseError(ValueError):
    """Gemini answered, but the answer is not valid JSON or has the wrong shape."""


class AIServiceError(RuntimeError):
    """Gemini could not be reached (network, timeout, server or API-key problem)."""


class AIClient(ABC):
    """Interface for anything that sends a prompt and returns the model's text.

    GeminiClient is used by the app; the tests use a fake client.
    """

    @abstractmethod
    def call_api(self, prompt):
        """Return the response text, or raise AIServiceError / AIResponseError."""

    def set_reporter(self, report):
        """Optional: receive a function for status messages."""


class GeminiClient(AIClient):
    """Calls Gemini, keeping requests spaced out and retrying temporary failures."""

    MAX_ATTEMPTS = 5
    RETRYABLE_CODES = {429, 500, 502, 503, 504}   # rate limit and server errors

    def __init__(self, api_key, model, sleep=time.sleep, sdk_client=None):
        if not api_key:
            raise ValueError("Set GEMINI_API_KEY before running BRC.")
        self._api_key = api_key
        self._model = model
        self._sleep = sleep
        self._client = sdk_client          # created on first use unless supplied
        self._interval = self._seconds("BRC_AI_REQUEST_INTERVAL_SECONDS", 4.2, 0, 60)
        self._timeout = self._seconds("BRC_AI_TIMEOUT_SECONDS", 20, 1, 120)
        self._last_request = None
        self._report = None

    def set_reporter(self, report):
        self._report = report

    def call_api(self, prompt):
        for attempt in range(self.MAX_ATTEMPTS):
            self._wait_for_turn()
            self._last_request = time.monotonic()
            try:
                response = self._generate(prompt)
            except Exception as error:     # the SDK and network raise many error types
                if attempt == self.MAX_ATTEMPTS - 1 or not self._is_temporary(error):
                    raise AIServiceError(f"Gemini request failed: {error}") from error
                self._wait_before_retry(error, attempt)
                continue
            if not response.text:
                raise AIResponseError("Gemini returned an empty response.")
            return response.text

    def _generate(self, prompt):
        from google.genai import types     # imported here so tests do not need the SDK
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(timeout=int(self._timeout * 1000)))
        return self._client.models.generate_content(
            model=self._model, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0, response_mime_type="application/json"))

    def _is_temporary(self, error):
        code = getattr(error, "code", None)
        return code is None or code in self.RETRYABLE_CODES  # no code = timeout/connection

    def _wait_before_retry(self, error, attempt):
        # Gemini sometimes says how long to wait, e.g. "Please retry in 7s".
        match = re.search(r"(?:retry in|retryDelay[^0-9]*)\s*(\d+(?:\.\d+)?)\s*s",
                          str(error), re.IGNORECASE)
        suggested = float(match.group(1)) if match else 0.0
        delay = max(suggested, 4.2 * (attempt + 1))
        if self._report:
            reason = "rate limit reached" if getattr(error, "code", None) == 429 \
                else "request failed"
            self._report(f"AI: Gemini {reason}; retrying in {delay:g} seconds...")
        self._sleep(delay)

    def _wait_for_turn(self):
        """Keep requests at least `interval` seconds apart (free-tier limits)."""
        if self._last_request is None:
            return
        remaining = self._interval - (time.monotonic() - self._last_request)
        if remaining > 0:
            self._sleep(remaining)

    @staticmethod
    def _seconds(name, default, low, high):
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return min(max(value, low), high)


class AIManager:
    """Builds prompts, calls the AI client and validates every answer.

    Aggregation: the client is created outside and passed in, so a fake client
    or another model can be used without changing this class.

    If the AI misbehaves the run still finishes: an invalid answer is retried
    once and then skipped; if Gemini is unreachable the remaining items are
    skipped; finished work is kept.
    """

    KEYWORDS = {   # obvious names are tagged without asking the AI
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

    # Cuisine tagging

    def tag_cuisines(self, listings, cache, save_cache=None):
        """Cuisine tags for every listing, in the same order as `listings`."""
        tags, pending = self._tags_without_ai(listings, cache)
        if len(pending) < len(listings):
            self._report(f"AI: reused or derived {len(listings) - len(pending)} cached "
                         f"cuisine tags; {len(pending)} still need AI.")
        if save_cache:
            save_cache(cache)
        size = self._batch_size()
        for start in range(0, len(pending), size):
            batch = pending[start:start + size]
            self._report(f"AI: tagging cuisines for restaurants "
                         f"{start + 1}–{start + len(batch)} of {len(pending)} "
                         f"(currently {batch[0][1].name or 'unknown'})")
            try:
                answers = self._tag_batch(batch)
            except AIResponseError as error:
                self._report(f"AI: skipped this batch after invalid responses ({error}); "
                             "it will be retried on the next build.")
                continue
            except AIServiceError as error:
                self._report(f"AI: Gemini is unavailable ({error}); {len(pending) - start} "
                             "restaurants were left untagged and will be retried next build.")
                break
            for index, cuisines in answers.items():
                tags[index] = cuisines
                cache.put(listings[index], cuisines)
            if save_cache:
                save_cache(cache)   # checkpoint after every successful batch
        return tags

    def _tags_without_ai(self, listings, cache):
        """Fill in tags from the cache or keywords; return what still needs the AI."""
        tags, pending = [[] for _ in listings], []
        for index, listing in enumerate(listings):
            cached = cache.get(listing)
            text = f"{listing.name or ''} {listing.category or ''}".casefold()
            keyword_tags = sorted({tag for word, tag in self.KEYWORDS.items() if word in text})
            if cached is not None:
                tags[index] = cached
            elif keyword_tags:
                tags[index] = keyword_tags
                cache.put(listing, keyword_tags)
            else:
                pending.append((index, listing))
        return tags, pending

    def _tag_batch(self, batch):
        rows = [{"index": index, "name": listing.name, "category": listing.category}
                for index, listing in batch]
        expected = {index for index, _ in batch}
        return self._ask(CUISINE_PROMPT + json.dumps(rows),
                         lambda raw: self._read_cuisines(raw, expected))

    def _read_cuisines(self, raw, expected):
        rows = self.parse_response(raw)
        if not self.validate_response(rows, expected_ids=expected):
            raise AIResponseError("BRC AI omitted or duplicated cuisine rows.")
        answers = {}
        for row in rows:
            if (not isinstance(row, dict) or set(row) != {"index", "cuisines"}
                    or row["index"] not in expected or not isinstance(row["cuisines"], list)):
                raise AIResponseError("BRC AI returned invalid cuisine tags.")
            allowed = []
            for tag in row["cuisines"]:
                tag = re.sub(r"\s+", " ", tag.strip().casefold()) if isinstance(tag, str) else ""
                if tag in CUISINES and tag not in allowed:
                    allowed.append(tag)
            answers[row["index"]] = allowed
        return answers

    # Outlet matching

    def match_outlets(self, records, candidate_groups, exact_matches):
        """The certificate number chosen for each restaurant, or None.

        exact_matches comes from the Logic Manager; the AI is only asked about
        restaurants that have candidates but no exact match.
        """
        chosen = []
        ai_available = True
        for number, (record, candidates, exact) in enumerate(
                zip(records, candidate_groups, exact_matches), 1):
            self._report(f"AI: checking restaurant {number} of {len(records)} "
                         f"({record.to_dict().get('name', 'unknown')})")
            if not candidates or exact is not None or not ai_available:
                chosen.append(exact)
                continue
            try:
                chosen.append(self._ask_for_match(number, record, candidates))
            except AIResponseError as error:
                self._report(f"AI: no valid answer for restaurant {number} ({error}); "
                             "it is marked not verified.")
                chosen.append(None)
            except AIServiceError as error:
                self._report(f"AI: Gemini is unavailable ({error}); the remaining "
                             "restaurants are marked not verified.")
                chosen.append(None)
                ai_available = False
        return chosen

    def _ask_for_match(self, number, record, candidates):
        payload = {"restaurant": record.to_dict(),
                   "candidates": [outlet.to_dict() for outlet in candidates]}
        allowed = {outlet.certificate.number for outlet in candidates}
        return self._ask(MATCH_PROMPT + json.dumps(payload),
                         lambda raw: self._read_match(raw, number, allowed))

    def _read_match(self, raw, number, allowed):
        answer = self.parse_response(raw, object_ok=True)
        if not self.validate_response(answer, object_keys={"certificate_number"}):
            raise AIResponseError(f"BRC AI returned an invalid match for restaurant {number}.")
        certificate = answer["certificate_number"]
        if certificate is not None and certificate not in allowed:
            raise AIResponseError(f"BRC AI invented a match for restaurant {number}.")
        return certificate

    # Shared helpers

    def _ask(self, prompt, read_answer):
        """Send a prompt and read the answer, retrying once if the answer is invalid."""
        try:
            return read_answer(self._client.call_api(prompt))
        except AIResponseError:
            return read_answer(self._client.call_api(prompt))

    @staticmethod
    def parse_response(raw, object_ok=False):
        """Decode the JSON answer, ignoring ```json fences. Lists are always
        accepted; a single object only when object_ok=True."""
        try:
            value = json.loads(re.sub(r"```(?:json)?", "", raw).strip())
        except (TypeError, json.JSONDecodeError) as exc:
            raise AIResponseError("BRC AI response is not valid JSON.") from exc
        if object_ok and isinstance(value, dict):
            return value
        if not isinstance(value, list):
            raise AIResponseError("BRC AI response has the wrong shape.")
        return value

    @staticmethod
    def validate_response(data, expected_ids=None, object_keys=None):
        """True if the answer has the expected keys, or one row per expected index."""
        if object_keys is not None:
            return isinstance(data, dict) and set(data) == set(object_keys)
        if not isinstance(data, list):
            return False
        if expected_ids is None:
            return True
        indexes = [row.get("index") for row in data if isinstance(row, dict)]
        return len(data) == len(expected_ids) and set(indexes) == set(expected_ids)

    @staticmethod
    def _batch_size():
        try:
            size = int(os.getenv("BRC_AI_BATCH_SIZE", "100"))
        except ValueError:
            size = 100
        return min(max(size, 1), 200)
