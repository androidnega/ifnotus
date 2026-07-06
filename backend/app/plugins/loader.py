"""Plugin discovery and loading."""

import importlib
import pkgutil
from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.plugins.base import PluginBase
from app.plugins.registry import PluginRegistry

logger = get_logger(__name__)


async def load_plugins(registry: PluginRegistry, settings: Settings) -> None:
    """Discover and load plugins from the plugins package."""
    plugins_path = Path(settings.plugins_dir)
    if not plugins_path.exists():
        logger.info("plugins_dir_not_found", path=str(plugins_path))
        return

    # Load built-in plugin package modules
    import app.plugins as plugins_package

    for _, module_name, _ in pkgutil.iter_modules(plugins_package.__path__):
        if module_name.startswith("_") or module_name in ("base", "registry", "loader"):
            continue
        try:
            module = importlib.import_module(f"app.plugins.{module_name}")
            plugin_cls = getattr(module, "Plugin", None)
            if plugin_cls and issubclass(plugin_cls, PluginBase):
                plugin = plugin_cls()
                await plugin.on_load()
                registry.register(plugin)
        except Exception:
            logger.exception("plugin_load_failed", module=module_name)


async def unload_plugins(registry: PluginRegistry) -> None:
    """Unload all registered plugins."""
    await registry.unload_all()
