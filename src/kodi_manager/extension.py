"""Optional private extension module for builds that add one.

Public builds ship no ``household.py`` and behave exactly as if this hook did
not exist. A private build may place ``household.py`` next to these files
(``resources/lib`` in the add-on). Everything it defines is optional:

``TRANSITION_COORDINATOR``
    Add-on ID that coordinates profile changes. Its master-profile
    ``addon_data`` folder holds the shared transition state read by
    ``profile_transition``. Without it, profile_transition is a no-op.
``WIDGET_PROGRESS_MODES``
    Extra plugin ``mode`` values whose cached rows are personal progress rows
    (short cache lifetime, refreshed after playback).
``WIDGET_PLAYABLE_MODES``
    ``{add-on ID: modes}``: cached leaves of that add-on whose ``mode`` is one
    of these resolve with setResolvedUrl, so they are marked playable.
``start(monitor, log)`` / ``stop()``
    Called by the service after it starts and first when it stops.
``widget_mode(mode, argv)``
    Called by the plugin for a ``mode`` the public code does not handle;
    returns True once it has answered the directory request.

The module is imported once per Python interpreter and must import nothing
heavy at module level: the plugin entry point loads it on every request.
"""
import importlib

NAME = "household"
_UNSET = object()
_loaded = _UNSET
error = None


def _import():
    global error
    package = __package__ or ""
    target = package + "." + NAME if package else NAME
    try:
        return importlib.import_module(target)
    except ImportError as exc:
        if getattr(exc, "name", None) == target:
            return None  # Not shipped: the public build.
        error = type(exc).__name__
    except Exception as exc:  # A broken private module must not break the add-on.
        error = type(exc).__name__
    return None


def module():
    """The extension module, or None (public build, or it failed to import: see ``error``)."""
    global _loaded
    if _loaded is _UNSET:
        _loaded = _import()
    return _loaded


def attr(name, default=None):
    found = module()
    return getattr(found, name, default) if found is not None else default


def reset():
    """Forget the loaded module (tests)."""
    global _loaded, error
    _loaded, error = _UNSET, None
