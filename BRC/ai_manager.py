from __future__ import annotations

import json
import logging
import math
import re
import time

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

AI_FIELDS_DEFAULT = {
    "cuisine": None,
    "ai_avg_price": None,
    "allergens": [],
    "spicy_options": None,
}


class AIManager:
    def __init__(self, api_key: str, model: str, max_retries: int = 2):
        self._api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self._client = None

    # ------------------------------------------------------------ public API

    def enrich(self, records: list[dict]) -> list[dict]:
        """Return every input record with AI fields and an ai_status added."""
        results: dict[int, dict] = {}
        pending = list(range(len(records)))

        for attempt in range(1, self.max_retries + 2):  # first try + retries
            if not pending:
                break
            try:
                text = self._call_api(self._build_prompt(records, pending))
                items = self._parse_response(text)
            except Exception as exc:  # API failure or unparseable output
                log.warning("AI attempt %d/%d failed: %s", attempt, self.max_retries + 1, exc)
                if getattr(exc, "code", None) == 429:
                    log.error("Gemini quota exceeded (429); not retrying.")
                    break
                self._pause(attempt)
                continue

            for item in items:
                try:
                    index, fields = self._validate_item(item)
                except ValueError as exc:
                    log.warning("Rejected malformed AI item %r: %s", item, exc)
                    continue
                if index in pending and index not in results:
                    results[index] = fields

            pending = [i for i in pending if i not in results]
            if pending:
                log.warning("%d record(s) still missing valid AI output", len(pending))
                self._pause(attempt)

        enriched = []
        for i, record in enumerate(records):
            out = dict(record)
            if i in results:
                out.update(results[i])
                out["ai_status"] = "ok"
            else:
                out.update({k: (list(v) if isinstance(v, list) else v) for k, v in AI_FIELDS_DEFAULT.items()})
                out["ai_status"] = "failed"
                log.error("AI enrichment failed for record %r", record.get("name"))
            enriched.append(out)
        return enriched

    # ------------------------------------------------------------- internals

    def _build_prompt(self, records: list[dict], indexes: list[int]) -> str:
        items = [
            {
                "index": i,
                "name": records[i].get("name", ""),
                "address": records[i].get("address", ""),
                "type": records[i].get("primary_type", ""),
            }
            for i in indexes
        ]
        return f"""
For each restaurant below, use general knowledge of the restaurant and its type to fill in:
  "index": the same index given
  "cuisine": string, lowercase (e.g. "chinese")
  "avg_price": number, typical spend per person in the local currency of the address, no symbol (null if you cannot estimate)
  "allergens": array of common allergens likely present (e.g. "soy", "peanuts", "gluten", "shellfish", "dairy"); empty array if unknown
  "spicy_options": boolean, true if spicy dishes or spice-level options are likely offered, null if unknown

Return ONLY a JSON array with exactly one object per restaurant. No markdown, no commentary.
These are estimates; do not claim certainty.

Restaurants:
{json.dumps(items, ensure_ascii=False, indent=2)}
""".strip()

    def _call_api(self, prompt: str) -> str:
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
            ),
        )
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
        return response.text

    @staticmethod
    def _parse_response(text: str) -> list:
        cleaned = re.sub(r"```(?:json)?", "", text).strip()
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("No JSON array found in model response.")
        data = json.loads(cleaned[start : end + 1])
        if not isinstance(data, list):
            raise ValueError("Model response is not a JSON array.")
        return data

    @staticmethod
    def _validate_item(item) -> tuple[int, dict]:
        """Check one response item against the expected schema."""
        if not isinstance(item, dict):
            raise ValueError("item is not an object")

        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("index must be an integer")

        cuisine = item.get("cuisine")
        if not isinstance(cuisine, str) or not cuisine.strip():
            raise ValueError("cuisine must be a non-empty string")

        price = item.get("avg_price")
        if price is not None:
            if (
                isinstance(price, bool)
                or not isinstance(price, (int, float))
                or not math.isfinite(price)
                or price < 0
            ):
                raise ValueError("avg_price must be a non-negative number or null")
            price = float(price)

        allergens = item.get("allergens")
        if not isinstance(allergens, list) or not all(isinstance(a, str) for a in allergens):
            raise ValueError("allergens must be a list of strings")

        spicy = item.get("spicy_options")
        if spicy is not None and not isinstance(spicy, bool):
            raise ValueError("spicy_options must be true, false or null")

        return index, {
            "cuisine": cuisine.strip().lower(),
            "ai_avg_price": price,
            "allergens": [a.strip().lower() for a in allergens if a.strip()],
            "spicy_options": spicy,
        }

    def _pause(self, attempt: int) -> None:
        if attempt <= self.max_retries:
            time.sleep(min(2 ** attempt, 8))
