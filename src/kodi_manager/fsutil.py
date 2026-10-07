"""Small filesystem helpers shared by the service and the widget plugin.

Only stdlib imports: the widget plugin imports this on every row load.
"""
import json
import os
import tempfile
import threading
import time

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def path_lock(path):
    """One re-entrant lock per absolute path, shared by every thread in this process."""
    key = os.path.abspath(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = _LOCKS[key] = threading.RLock()
        return lock


def atomic_write_bytes(path, data, fsync=True):
    """Write ``data`` to ``path`` via a unique temporary file in the same folder.

    Readers see either the old or the new file, never a partial one. Unlike a
    ``<path>.<pid>.tmp`` name, ``mkstemp`` cannot collide between threads.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=directory)
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
