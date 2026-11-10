"""Polymorphic BRNS AI fallback routing and response validation."""


class AIProviderRouter:
    """Try configured provider objects in order until one validates."""

    def __init__(
            self, providers, parser, validator, failure_sanitizer,
            event_logger, delay):
        self.__providers = tuple(providers)
        self._parser = parser
        self._validator = validator
        self._failure_sanitizer = failure_sanitizer
        self._event_logger = event_logger
        self._delay = delay

    @property
    def providers(self):
        """Return the immutable configured fallback order."""
        return self.__providers

    def route(self, system_prompt, user_text):
        """Return the first valid result using the legacy BRNS tuple shape."""
        errors = []
        for provider in self.__providers:
            ok, content = provider.request(system_prompt, user_text)
            if ok:
                try:
                    parsed = self._parser(content)
                except ValueError:
                    errors.append(f"{provider.label}: unparseable")
                    self._event_logger(
                        "fallback", f"{provider.label}: invalid JSON")
                    continue
                is_valid, result = self._validator(parsed)
                if is_valid:
                    return True, result, provider.label
                errors.append(
                    f"{provider.label}: schema invalid ({result})")
                self._event_logger(
                    "fallback", f"{provider.label} schema: {result}")
                continue
            safe_failure = self._failure_sanitizer(content)
            errors.append(f"{provider.label}: {safe_failure}")
            self._event_logger(
                "fallback", f"{provider.label}: {safe_failure}")
            self._delay(1)
        return False, "; ".join(errors), None
