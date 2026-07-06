"""Example plugin — demonstrates the plugin interface."""

from app.plugins.base import PluginBase, PluginMetadata


class Plugin(PluginBase):
    """Example no-op plugin."""

    metadata = PluginMetadata(
        name="example",
        version="0.1.0",
        description="Example plugin skeleton",
    )

    async def on_load(self) -> None:
        pass

    async def on_unload(self) -> None:
        pass
