"""Polymorphic BIS AI fallback routing and response validation."""


class AIProviderRouter:
    """Try configured provider objects in order until one validates."""

    def __init__(self, providers, parser, logger):
        self.__providers = tuple(providers)
        self._parser = parser
        self._logger = logger

    @property
    def providers(self):
        """Return the immutable configured fallback order."""
        return self.__providers

    def route(self, payload, config, validator=None):
        errors = []
        for provider in self.__providers:
            try:
                content = provider.request(payload, config)
            except RuntimeError as error:
                errors.append(
                    type(error).__name__ if provider.primary
                    else provider.label
                )
                self._logger(
                    "Primary BIS model failed; trying model chain."
                    if provider.primary
                    else f"Fallback model {provider.label} failed.",
                    "WARNING", "BIS.ai.fallback",
                )
                continue
            try:
                parsed = self._parser(content)
                parsed = validator(parsed) if validator else parsed
            except (RuntimeError, ValueError, TypeError, AttributeError):
                errors.append(f"{provider.label} invalid response")
                if provider.primary:
                    self._logger(
                        "Primary BIS model failed; trying model chain.",
                        "WARNING", "BIS.ai.fallback",
                    )
                continue
            if not provider.primary:
                self._logger(
                    f"Fallback model {provider.label} responded.",
                    "INFO", "BIS.ai.fallback",
                )
            return parsed
        raise RuntimeError(
            "BIS AI models are unavailable. Please retry."
            if errors else "Configure a BIS AI model before continuing."
        )
