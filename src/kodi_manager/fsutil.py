"""Small filesystem helpers shared by the service and the widget plugin.

Only stdlib imports: the widget plugin imports this on every row load.
"""
import contextlib
import json
import os
import tempfile
import threading
import time

try:
    from . import tvos_storage
except ImportError:
    import tvos_storage

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def path_lock(path):
    """One re-entrant lock per absolute path, shared by every thread in this process."""
    key = os.path.normcase(os.path.realpath(path))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.RLock()
        return lock


_IPC_HELD = threading.local()


@contextlib.contextmanager
def interprocess_lock(path):
    """Exclusive lock shared with other Kodi interpreters: flock on "<realpath>.lock".

    Kodi runs each add-on script (the context menu, the service) in its own Python
    interpreter of one process, so :func:`path_lock` alone does not serialise them. flock
    locks belong to an open file description, so they also exclude each other inside one
    process (lockf/fcntl locks would not). Hold :func:`path_lock` around this as well: it
    serialises this interpreter's threads, and this lock is re-entrant per thread. Where
    fcntl is missing (Windows, tvOS builds without it) or the lock file cannot be opened,
    this is a no-op and only ``path_lock`` applies.
    """
    key = os.path.normcase(os.path.realpath(path))
    held = getattr(_IPC_HELD, "paths", None)
    if held is None:
        held = _IPC_HELD.paths = {}
    if key in held:
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    fd = None
    try:
        import fcntl
        # Use the same canonical path for identity and the on-disk lock.
        # Aliases must not acquire separate locks in other interpreters.
        directory = os.path.dirname(key)
        os.makedirs(directory, exist_ok=True)
        fd = os.open(key + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
    except (ImportError, OSError, AttributeError):
        if fd is not None:
            os.close(fd)
            fd = None
    held[key] = 1
    try:
        yield
    finally:
        del held[key]
        if fd is not None:
            os.close(fd)   # closing the description releases the flock


# Temporary siblings keep at most this many characters of the target's name: with
# the "." prefix and mkstemp's random part and suffix, the name stays far below the
# 255-byte limit even for a 255-byte name or a long name in a multi-byte script.
TEMP_NAME_CHARS = 40


def temp_prefix(path):
    """The mkstemp prefix for a temporary sibling of ``path``: "." + its name (bounded) + "."."""
    return "." + os.path.basename(path)[:TEMP_NAME_CHARS] + "."


def atomic_write_bytes(path, data, fsync=True):
    """Write ``data`` to ``path`` via a unique temporary file in the same folder.

    Readers see either the old or the new file, never a partial one. Unlike a
    ``<path>.<pid>.tmp`` name, ``mkstemp`` cannot collide between threads.
    """
    if tvos_storage.virtual_xml(path):
        with path_lock(path):
            tvos_storage.write_xml(path, data)
        return
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=temp_prefix(path), suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            if fsync:
                os.fsync(handle.fileno())
        try:
            mode = os.stat(path).st_mode & 0o777 if os.path.isfile(path) else 0o644
            os.chmod(tmp, mode)
        except OSError:
            pass
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _replace(tmp, path, attempts=20):
    """``os.replace`` serialised per path, retrying Windows sharing violations.

    On Windows replacing a file fails with PermissionError while another thread
    is replacing it or a reader has it open; the condition clears within
    milliseconds, so wait briefly instead of failing the write.
    """
    with path_lock(path):
        for attempt in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if os.name != "nt" or attempt == attempts - 1:
                    raise
                time.sleep(0.01 * (attempt + 1))


def atomic_write_text(path, text, encoding="utf-8", fsync=True):
    atomic_write_bytes(path, text.encode(encoding), fsync=fsync)


def atomic_write_json(path, data, fsync=True, **dump_kwargs):
    atomic_write_text(path, json.dumps(data, **dump_kwargs), fsync=fsync)
