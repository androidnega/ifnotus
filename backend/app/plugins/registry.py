"""Plugin registry."""

from app.core.logging import get_logger
from app.plugins.base import PluginBase

logger = get_logger(__name__)


class PluginRegistry:
    """Manages loaded plugins and their resources."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}

    @property
    def plugins(self) -> dict[str, PluginBase]:
        return dict(self._plugins)

    def register(self, plugin: PluginBase) -> None:
        name = plugin.metadata.name
        if name in self._plugins:
            raise ValueError(f"Plugin '{name}' is already registered.")
        self._plugins[name] = plugin
        logger.info("plugin_registered", name=name, version=plugin.metadata.version)

    async def unload_all(self) -> None:
        for plugin in self._plugins.values():
            await plugin.on_unload()
        self._plugins.clear()

    def get_routers(self) -> list:
        routers = []
        for plugin in self._plugins.values():
            routers.extend(plugin.get_routers())
        return routers

    def get(self, name: str) -> PluginBase | None:
        return self._plugins.get(name)
