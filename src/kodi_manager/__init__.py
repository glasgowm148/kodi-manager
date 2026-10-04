"""Kodi Manager's stable desktop API. Kodi runtime modules are available separately."""
from .client import ManagerClient, ManagerError
from .settings_schema import flatten_settings, parse_schema
from .version import VERSION as __version__

__all__ = ["ManagerClient", "ManagerError", "parse_schema", "flatten_settings", "__version__"]
