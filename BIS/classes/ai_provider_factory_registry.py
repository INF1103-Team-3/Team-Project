"""Registry of BIS AI provider object factories."""


class AIProviderFactoryRegistry:
    """Create enabled providers without provider-specific routing branches."""

    def __init__(self):
        self.__entries = {}

    def register(self, provider_name, factory, enabled=None):
        self.__entries[provider_name] = (
            factory, enabled or (lambda _config: True))

    def create(self, provider_name, model, config):
        entry = self.__entries.get(provider_name)
        if entry is None:
            return None
        factory, enabled = entry
        return factory(model) if enabled(config) else None

    @property
    def provider_names(self):
        return tuple(self.__entries)
