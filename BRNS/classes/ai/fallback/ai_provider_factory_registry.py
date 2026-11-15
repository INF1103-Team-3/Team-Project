"""Registry of BRNS AI provider object factories."""


class AIProviderFactoryRegistry:
    """Create registered providers without routing type conditionals."""

    def __init__(self):
        self.__factories = {}

    def register(self, provider_name, factory):
        self.__factories[provider_name] = factory

    def create(self, provider_name, model):
        factory = self.__factories.get(provider_name)
        return factory(model) if factory else None

    @property
    def provider_names(self):
        return tuple(self.__factories)
