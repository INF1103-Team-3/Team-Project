"""Fallback routing for BRC's configured AI providers."""

import json
import re
import time

from shared import debug_log


class AIProviderRouter:
    """Try configured providers until one returns valid structured data."""

    def __init__(
            self, gemini_call, chat_completions_call,
            clock=time.monotonic, cooldown_seconds=0):
        self._gemini_call = gemini_call
        self._chat_completions_call = chat_completions_call
        self._clock = clock
        self._cooldown_seconds = float(cooldown_seconds or 0)
        self._cooldowns = {}

    def request(self, prompt, settings, validator=None):
        if settings is None:
            raise ValueError("BRC AI manager state is required.")
        deadline = self._clock() + settings["chain_timeout_seconds"]
        failures = []
        entries = list(settings["providers"])
        if self._cooldown_seconds > 0 and len(entries) > 1:
            now = self._clock()
            active = [
                entry for entry in entries
                if self._cooldowns.get((entry["provider"], entry["model"]), 0) <= now
            ]
            if active:
                entries = active
        for entry in entries:
            remaining = deadline - self._clock()
            if remaining <= 0:
                failures.append("provider chain deadline reached")
                break
            provider, model = entry["provider"], entry["model"]
            debug_log.debug_log(
                f"BRC trying {provider}/{model}.",
                "INFO", "BRC.ai_manager.fallback")
            try:
                if provider == "gemini":
                    raw = self._gemini_call(prompt, settings, model)
                elif provider in {"openrouter", "groq"}:
                    raw = self._chat_completions_call(
                        prompt, settings, provider, model,
                        min(settings["timeout_seconds"], remaining))
                else:
                    continue
            except Exception as error:
                if self._cooldown_seconds > 0:
                    self._cooldowns[(provider, model)] = (
                        self._clock() + self._cooldown_seconds)
                failures.append(
                    f"{provider}/{model}: {type(error).__name__}")
                debug_log.debug_log(
                    f"BRC {provider}/{model} failed with "
                    f"{type(error).__name__}; trying the next provider.",
                    "WARNING", "BRC.ai_manager.fallback")
                continue
            if not self._valid_json(raw) or validator and not validator(raw):
                failures.append(f"{provider}/{model}: invalid response")
                debug_log.debug_log(
                    f"BRC {provider}/{model} returned invalid structured "
                    "data; trying the next provider.",
                    "WARNING", "BRC.ai_manager.fallback")
                continue
            self._cooldowns.pop((provider, model), None)
            debug_log.debug_log(
                f"BRC accepted {provider}/{model} response.",
                "INFO", "BRC.ai_manager.fallback")
            return raw
        raise RuntimeError(
            "BRC AI providers are unavailable or returned invalid data: "
            + "; ".join(failures))

    @staticmethod
    def _valid_json(raw):
        try:
            value = json.loads(
                re.sub(r"```(?:json)?", "", raw).strip())
        except (TypeError, json.JSONDecodeError):
            return False
        return isinstance(value, (dict, list))
