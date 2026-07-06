"""Plugin system for extensible platform capabilities."""

from app.plugins.base import PluginBase, PluginMetadata
from app.plugins.loader import load_plugins
from app.plugins.registry import PluginRegistry

__all__ = ["PluginBase", "PluginMetadata", "PluginRegistry", "load_plugins"]
