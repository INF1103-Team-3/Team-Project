"""Registry of BRNS AI provider object factories."""


class AIProviderFactoryRegistry:
    """Create registered providers without routing type conditionals."""

    def __init__(self):
        self.__factories = {}

    def register(self, provider_name, factory, enabled=None):
        self.__factories[provider_name] = (factory, enabled)

    def is_configured(self, provider_name, config):
        entry = self.__factories.get(provider_name)
        return bool(entry and (entry[1] is None or entry[1](config)))

    def create(self, provider_name, model):
        entry = self.__factories.get(provider_name)
        return entry[0](model) if entry else None

    @property
    def provider_names(self):
        return tuple(self.__factories)
