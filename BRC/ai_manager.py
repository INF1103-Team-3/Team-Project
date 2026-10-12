"""Use Gemini to propose MUIS outlet matches for logic to verify."""

from __future__ import annotations

import json
import re

from google import genai
from google.genai import types


class AIManager:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self.model = model
        self._client = None

    def propose_muis_matches(self, records: list[dict], snapshot: dict) -> list[str | None]:
        """Ask AI to select a candidate listing for each outlet, never certify it."""
        from BRC import logic_manager

        by_postal: dict[str, list[dict]] = {}
        for listing in snapshot["listings"]:
            by_postal.setdefault(listing["postal_code"], []).append(listing)
        proposals: list[str | None] = [None] * len(records)
        pending = []
        for index, record in enumerate(records):
            postal = logic_manager.muis_postal(record)
            candidates = by_postal.get(postal, []) if postal else []
            if candidates:
                pending.append((index, record, candidates))
        for start in range(0, len(pending), 10):
            batch = pending[start:start + 10]
            allowed = {
                index: {candidate["certificate_number"] for candidate in candidates}
                for index, _, candidates in batch
            }
            items = [{
                "index": index,
                "restaurant": {"name": record["name"],
                               "address": record["address"],
                               "postal_code": logic_manager.muis_postal(record)},
                "muis_candidates": [
                    {"certificate_number": item["certificate_number"],
                     "name": item["name"], "address": item["address"],
                     "postal_code": item["postal_code"]}
                    for item in candidates],
            } for index, record, candidates in batch]
            prompt = (
                "Compare each restaurant with its MUIS candidate listings. "
                "Select the exact same outlet or null. Normalize spelling, "
                "branch names and addresses, but never assume all branches "
                "of one brand are certified. Return only a JSON array with "
                "exactly one object per restaurant: "
                "{\"index\": integer, \"certificate_number\": string or null}. "
                "Copy certificate numbers exactly from the provided candidates. "
                "A separate logic layer will verify every proposal.\n"
                + json.dumps(items, ensure_ascii=False, separators=(",", ":"))
            )
            response = self._parse_response(self._call_api(prompt))
            if (len(response) != len(batch)
                    or any(not isinstance(item, dict)
                           or set(item) != {"index", "certificate_number"}
                           or type(item["index"]) is not int
                           or item["index"] not in allowed
                           or item["certificate_number"] not in (
                               *allowed[item["index"]], None)
                           for item in response)
                    or {item["index"] for item in response} != set(allowed)):
                raise ValueError("BRC AI returned invalid MUIS match proposals.")
            for item in response:
                proposals[item["index"]] = item["certificate_number"]
        return proposals

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
