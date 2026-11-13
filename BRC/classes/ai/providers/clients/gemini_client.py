"""Gemini implementation of the BRC AI client capability."""

import os
import re
import time

from BRC.classes.ai.providers.contracts.ai_client_interface import AIClientInterface
from BRC.classes.ai.errors.ai_response_error import AIResponseError
from BRC.classes.ai.errors.ai_service_error import AIServiceError


class GeminiClient(AIClientInterface):
    """Call Gemini with BRC's existing pacing and retry policy."""

    MAX_ATTEMPTS = 5
    RETRYABLE_CODES = {429, 500, 502, 503, 504}

    def __init__(self, api_key, model, sleep=time.sleep, sdk_client=None):
        if not api_key:
            raise ValueError("Set GEMINI_API_KEY before running BRC.")
        self._api_key = api_key
        self._model = model
        self._sleep = sleep
        self._client = sdk_client
        self._interval = self._seconds(
            "BRC_AI_REQUEST_INTERVAL_SECONDS", 4.2, 0, 60)
        self._timeout = self._seconds(
            "BRC_AI_TIMEOUT_SECONDS", 20, 1, 120)
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
            except Exception as error:
                if (attempt == self.MAX_ATTEMPTS - 1
                        or not self._is_temporary(error)):
                    raise AIServiceError(
                        f"Gemini request failed: {error}") from error
                self._wait_before_retry(error, attempt)
                continue
            if not response.text:
                raise AIResponseError("Gemini returned an empty response.")
            return response.text
        raise AIServiceError("Gemini retries were exhausted.")

    def _generate(self, prompt):
        from google.genai import types

        if self._client is None:
            from google import genai
            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=int(self._timeout * 1000)))
        return self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0, response_mime_type="application/json"))

    def _is_temporary(self, error):
        code = getattr(error, "code", None)
        return code is None or code in self.RETRYABLE_CODES

    def _wait_before_retry(self, error, attempt):
        match = re.search(
            r"(?:retry in|retryDelay[^0-9]*)\s*(\d+(?:\.\d+)?)\s*s",
            str(error), re.IGNORECASE)
        suggested = float(match.group(1)) if match else 0.0
        delay = max(suggested, 4.2 * (attempt + 1))
        if self._report:
            reason = (
                "rate limit reached"
                if getattr(error, "code", None) == 429
                else "request failed")
            self._report(
                f"AI: Gemini {reason}; retrying in {delay:g} seconds...")
        self._sleep(delay)

    def _wait_for_turn(self):
        if self._last_request is None:
            return
        remaining = self._interval - (
            time.monotonic() - self._last_request)
        if remaining > 0:
            self._sleep(remaining)

    @staticmethod
    def _seconds(name, default, low, high):
        try:
            value = float(os.getenv(name, str(default)))
        except ValueError:
            value = default
        return min(max(value, low), high)
