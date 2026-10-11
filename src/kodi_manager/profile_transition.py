"""Cancel stale work across profile changes driven by a coordinator add-on.

Some setups switch profiles through a coordinator add-on that announces the
switch before Kodi takes its GUI/profile locks: it writes a transition record
(process, generation, outgoing profile) to its master-profile ``addon_data``
folder, waits for registered plugin invocations to finish and for services to
acknowledge that they drained. This module is Kodi Manager's side of that
protocol.

The coordinator is named by the optional private extension
(``TRANSITION_COORDINATOR``, see extension.py). Without one, as in public
builds, everything here is a no-op: no files are read or written, threads are
not tagged, ``Monitor`` behaves as ``xbmc.Monitor`` and ``drained`` returns at
once.

Only generation, process, profile paths and add-on IDs are stored. No media
URLs, account identifiers or credentials. File checks need no Kodi GUI lock.
"""
import json
import os
import re
import threading
import time
import uuid
from typing import Any

try:
    import xbmc
    import xbmcvfs
except ImportError:  # Outside Kodi (library use, tests).
    xbmc = xbmcvfs = None

try:
    from . import extension
except ImportError:
    import extension


def _coordinator():
    value = extension.attr("TRANSITION_COORDINATOR")
    if xbmcvfs is None or not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        return None
    return value


COORDINATOR = _coordinator()
ENABLED = COORDINATOR is not None
if ENABLED and xbmcvfs is not None:
    ROOT = xbmcvfs.translatePath('special://masterprofile/addon_data/' + COORDINATOR)
    PROFILE = xbmcvfs.translatePath('special://profile/').rstrip('/\\')
    STATE = os.path.join(ROOT, 'transition.json')
else:
    ROOT = PROFILE = STATE = ''

# Tag workers when they are created. Inspecting process-wide Python frame
# objects can cross Kodi sub-interpreter boundaries during service teardown.
_OWNER_KEY = '_kodi_profile_worker_owner'


def _install_thread_ownership():
    original = threading.Thread.start
    if getattr(original, '_kodi_profile_tracking', False):
        return
    current_thread = threading.current_thread

    def start(thread, *args, **kwargs):
        owner = current_thread().__dict__.get('_kodi_profile_worker_owner')
        if owner:
            thread.__dict__['_kodi_profile_worker_owner'] = owner
        return original(thread, *args, **kwargs)
    # Patching a stdlib class at runtime: neither the function attribute nor the
    # replaced method is part of their declared types.
    tracked: Any = start
    tracked._kodi_profile_tracking = True
    thread_class: Any = threading.Thread
    thread_class.start = start


if ENABLED:
    threading.current_thread().__dict__[_OWNER_KEY] = uuid.uuid4().hex
    _install_thread_ownership()


def read_state():
    if not ENABLED:
        return {}
    try:
        with open(STATE, encoding='utf-8') as stream:
            value = json.load(stream)
        return value if value.get('pid') == os.getpid() else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + '.' + uuid.uuid4().hex + '.tmp'
    with open(temp, 'w', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush()
    os.replace(temp, path)


class Lease:
    def __init__(self):
        self.profile = PROFILE
        self.generation = read_state().get('generation', '')

    def cancelled(self):
        if not ENABLED:
            return False
        state = read_state()
        return (state.get('generation', '') != self.generation or
                bool(state.get('switching') and state.get('outgoing') == self.profile))


# xbmc.Monitor inside Kodi, a plain object elsewhere: the base class depends on where this runs.
_BaseMonitor: Any = getattr(xbmc, "Monitor", object)


class Monitor(_BaseMonitor):
    """xbmc.Monitor that also reports abort once a profile switch cancels this generation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lease = Lease()

    def abortRequested(self):
        return self.lease.cancelled() or super().abortRequested()

    def waitForAbort(self, timeout=-1):
        if not ENABLED:
            return super().waitForAbort(timeout)
        deadline = time.monotonic() + timeout if timeout > 0 else float("inf")
        while not self.abortRequested():
            left = deadline - time.monotonic()
            if left <= 0:
                return False
            if super().waitForAbort(min(.2, left)):
                return True
        return True


class Invocation(Lease):
    """Registers a plugin invocation so a coordinator can wait for it; a context manager."""

    def __init__(self, addon):
        super().__init__()
        self.path = os.path.join(ROOT, 'jobs', str(os.getpid()), uuid.uuid4().hex + '.json') if ENABLED else ''
        self.addon = addon

    def __enter__(self):
        if not ENABLED:
            return self
        self.thread = threading.current_thread()
        self.previous_owner = self.thread.__dict__.get(_OWNER_KEY)
        self.thread.__dict__[_OWNER_KEY] = self.path
        _write(self.path, {'profile': self.profile, 'addon': self.addon})
        return self

    def __exit__(self, *_):
        if not ENABLED:
            return
        # The switch has its own bounded timeout and cancels safely. Keep this
        # invocation alive until its children finish so native interpreter
        # cleanup cannot join them under a GUI lock, or leave a stale ticket.
        while _owned_workers(self.addon):
            time.sleep(.05)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        finally:
            if self.previous_owner:
                self.thread.__dict__[_OWNER_KEY] = self.previous_owner
            else:
                self.thread.__dict__.pop(_OWNER_KEY, None)


def _ack_path(addon):
    return os.path.join(ROOT, 'drained', read_state().get('generation', 'none'), addon + '.json')


def _owned_workers(addon):
    current = threading.current_thread()
    owner = current.__dict__.get(_OWNER_KEY)
    return [thread for thread in threading.enumerate()
            if thread is not current and thread.is_alive() and owner
            and thread.__dict__.get(_OWNER_KEY) == owner]


def drained(addon, timeout=10):
    """Wait (bounded) for this script's worker threads, then acknowledge to the coordinator."""
    if not ENABLED:
        return True
    _write(os.path.join(ROOT, 'drain-start-' + addon + '.json'), {'started': True})
    deadline = time.monotonic() + timeout
    while True:
        children = _owned_workers(addon)
        if not children:
            _write(_ack_path(addon), {'complete': True})
            return True
        if time.monotonic() >= deadline:
            _write(os.path.join(ROOT, 'drain-diagnostic.json'), {'addon': addon,
                   'workers': [t.name for t in children]})
            return False
        time.sleep(.05)
