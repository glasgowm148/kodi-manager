import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
import re
import uuid
import threading
from functools import wraps

try:
    from . import tvos_storage
    from .kodi_api import translate
    from .fsutil import atomic_write_bytes, atomic_write_json, temp_prefix
    from .operation_records import capture_backup
except ImportError:
    import tvos_storage
    from kodi_api import translate
    from fsutil import atomic_write_bytes, atomic_write_json, temp_prefix
    from operation_records import capture_backup
try:
    import sqlite3
except ImportError:  # A Python build without SQLite: databases are copied like other files.
    sqlite3 = None


DEFAULT_RETENTION = 20


class BackupAborted(Exception):
    """A snapshot was stopped before it completed; the partial snapshot is discarded.

    ``deferred`` tells callers to retry later. ``reason`` says why: the truthy string a
    ``should_stop`` callback returned (for example "playback" or "stopping"), "stopped"
    when it returned anything else, or "busy_database" when an add-on kept one of its
    SQLite databases locked or changed its journal while it was being copied.
    """
    deferred = True

    def __init__(self, message="Snapshot stopped before it completed", reason="stopped"):
        super(BackupAborted, self).__init__(message)
        self.reason = reason


def _check_stop(should_stop):
    why = should_stop() if should_stop is not None else False
    if why:
        raise BackupAborted("Snapshot stopped before it completed", why if isinstance(why, str) else "stopped")


_retention = DEFAULT_RETENTION
SELF_ID = "service.kodi.addonadmin"
# Kodi Manager's access token and LAN/write switches are only changed in Kodi:
# restoring an old copy of its own folder keeps the live settings.xml, so a
# replaced token or a LAN switch turned off cannot come back from a backup.
SELF_KEEP = ("settings.xml", "device_identity.xml")
# Kodi Manager's own internal stores in its addon_data folder: fix undo copies,
# operation history, log history, the widget cache and metrics, and the one-time
# installer handoff (whose token and LAN switch must not come back either). They
# are not in its snapshots, and restoring one leaves the live copies alone. The
# user's cached-row list (widget_cache/rows.json) and baseline.json are restored.
SELF_STATE_DIRS = ("fix_backups", "operations", "widget_cache")
SELF_STATE_FILES = ("log-history.db", "metrics_history.json", "installer_seed.json", "installer_seed.applied",
                    "installer_result.json", "allow_lan_first_run.flag")
SELF_RESTORED = ("widget_cache/rows.json",)
# Files that only exist while something is being written: SQLite shared-memory
# indexes and the temporary siblings of atomic writes (fsutil, _copy_file,
# profile_transition). A SQLite -wal file can hold committed data not yet in the
# database, and a hot -journal is needed to roll back a half-written one, so both
# are kept.
_TRANSIENT = re.compile(r"-shm$|^\..+\.[a-z0-9_]{8}\.(?:tmp|km-tmp)$|\.[0-9a-f]{32}\.tmp$")
_SQLITE_SIDE = re.compile(r"-(?:wal|journal|shm)$")
SQLITE_HEADER = b"SQLite format 3\x00"
# How long one database may stay locked by its add-on before the snapshot gives up
# (BackupAborted "busy_database") and is retried later.
SQLITE_BUSY_SECONDS = 15.0
# One restore at a time: two restores interleaving on a live folder would mix them.
_RESTORE_LOCK = threading.RLock()
# Guards finishing (manifest + pruning), deleting and the in-use registry below.
_PRUNE_LOCK = threading.RLock()
_IN_USE = {}        # normalised snapshot folder -> number of restores using it
_HELD = threading.local()   # .keys: snapshots finished by this thread's restore, kept in use
_ROOT = threading.local()


def _with_backup_root(function):
    """Pin one profile's backup root through nested copies, pruning and rollback."""
    @wraps(function)
    def run(*args, **kwargs):
        if getattr(_ROOT, "path", None) is not None:
            return function(*args, **kwargs)
        _ROOT.path = backup_root()
        try:
            return function(*args, **kwargs)
        finally:
            del _ROOT.path
    return run


def _active_root():
    return getattr(_ROOT, "path", None) or backup_root()


@contextlib.contextmanager
def root_scope(root):
    previous = getattr(_ROOT, "path", None)
    _ROOT.path = root
    try:
        yield
    finally:
        if previous is None:
            del _ROOT.path
        else:
            _ROOT.path = previous


def set_retention(count):
    """Keep at most `count` snapshots per scope (add-on, _stack, pipeline); minimum 1."""
    global _retention
    try:
        _retention = max(1, int(count))
    except (TypeError, ValueError):
        _retention = DEFAULT_RETENTION


def retention():
    return _retention


def prune_folder(folder, prefix, keep=(), limit=None):
    """Keep the newest ``limit`` (default: the retention setting) subfolders of
    ``folder`` whose names start with ``prefix``; other folders are never touched."""
    limit = _retention if limit is None else max(1, int(limit))
    try:
        names = [n for n in os.listdir(folder) if n.startswith(prefix) and n not in keep
                 and os.path.isdir(os.path.join(folder, n)) and not os.path.islink(os.path.join(folder, n))]
    except OSError:
        return []
    names.sort(key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True)
    removed = []
    for name in names[max(0, limit - len(keep)):]:
        tvos_storage.rmtree(os.path.join(folder, name), ignore_errors=True)
        removed.append(name)
    return removed


def live_addon_data(addon_info):
    """The real folder of an add-on's addon_data. Kodi may hand out special:// URLs,
    which os.walk, shutil and open cannot use, so they are always translated."""
    aid = (addon_info or {}).get("addon_id")
    path = (addon_info or {}).get("addon_data_path") or ("special://profile/addon_data/%s" % aid if aid else "")
    return translate(path) if path else ""


def backup_root():
    root = translate("special://profile/addon_data/service.kodi.addonadmin/backups")
    os.makedirs(root, exist_ok=True)
    return root


def _backup_path(*parts):
    if any(not isinstance(p, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', p)
           or p in ('.', '..') for p in parts):
        raise ValueError('Invalid backup identifier')
    # Preserve Kodi's translated spelling for tvOS VFS keys. Resolve only the
    # confinement check; directory aliases must not change the storage backend.
    root = Path(os.path.abspath(_active_root()))
    target = root.joinpath(*parts)
    if root.resolve() not in target.resolve().parents:
        raise ValueError('Backup path leaves its directory')
    return str(target)


def _self_state(rel):
    """True for a path (relative to Kodi Manager's addon_data) of one of its internal stores."""
    rel = rel.replace(os.sep, "/")
    top = rel.split("/")[0]
    if top in SELF_STATE_DIRS:
        return rel not in SELF_RESTORED
    return "/" not in rel and any(rel == name or rel.startswith(name + "-") for name in SELF_STATE_FILES)


def _self_preserved(rel):
    return rel in SELF_KEEP or _self_state(rel)


def _source_files(src, skip_top=(), should_stop=None, exclude=None):
    """Relative paths of the regular files under src, never following symlinks.

    Files for which ``exclude(relative path)`` is true are left out."""
    files = []
    for root, dirs, names in tvos_storage.walk(src):
        _check_stop(should_stop)
        rel = os.path.relpath(root, src)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in skip_top]
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in names:
            path = os.path.join(root, name)
            if not os.path.islink(path) and tvos_storage.is_file(path):
                rel_file = os.path.relpath(path, src)
                if exclude is None or not exclude(rel_file):
                    files.append(rel_file)
    return files


def _copy_file(src, dst, should_stop=None):
    """Copy one file via a temporary sibling, so ``dst`` is never left half-written."""
    def check_stop():
        _check_stop(should_stop)

    check_stop()
    if tvos_storage.virtual_xml(src) or tvos_storage.virtual_xml(dst):
        data = tvos_storage.read_bytes(src)
        check_stop()
        atomic_write_bytes(dst, data)
        return
    tmp = _temp_sibling(dst)
    try:
        if should_stop is None:
            shutil.copy2(src, tmp, follow_symlinks=False)
        else:
            with open(src, 'rb') as source, open(tmp, 'wb') as target:
                while True:
                    check_stop()
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    target.write(block)
            check_stop()
            shutil.copystat(src, tmp, follow_symlinks=False)
        check_stop()
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _temp_sibling(dst):
    """A new empty temporary file next to ``dst``. The name keeps at most a bounded
    prefix of dst's name, so it fits the 255-byte limit however long that name is."""
    fd, tmp = tempfile.mkstemp(prefix=temp_prefix(dst), suffix=".km-tmp", dir=os.path.dirname(dst))
    os.close(fd)
    return tmp


def _is_sqlite(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(16) == SQLITE_HEADER
    except OSError:
        return False


def _sqlite_busy(error):
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _copy_sqlite(src, dst, should_stop=None):
    """Copy a live SQLite database consistently with SQLite's online backup API.

    The copy holds every committed transaction (including those still in a -wal file)
    and nothing uncommitted, so it needs none of the source's -wal/-journal/-shm files.
    Returns False, leaving ``dst`` untouched, when SQLite cannot open the database
    read-only (for example a hot journal that only a writer may roll back, or a
    database it does not recognise): the caller then copies its files as they are.
    Raises BackupAborted ("busy_database") when the database stays locked.
    """
    if sqlite3 is None or tvos_storage.virtual_xml(src) or tvos_storage.virtual_xml(dst):
        return False
    _check_stop(should_stop)
    deadline = time.monotonic() + SQLITE_BUSY_SECONDS

    def progress(status, remaining, total):
        # Called after every step, including SQLITE_BUSY retries: bounded and stoppable.
        _check_stop(should_stop)
        if time.monotonic() > deadline:
            raise BackupAborted("An add-on kept a database busy while the snapshot was taken", "busy_database")

    tmp = _temp_sibling(dst)
    copied = False
    try:
        source = target = None
        try:
            # A short busy wait per attempt: between attempts ``progress`` checks should_stop.
            source = sqlite3.connect(Path(os.path.abspath(src)).as_uri() + "?mode=ro", uri=True,
                                     timeout=1.0, isolation_level=None, check_same_thread=False)
            target = sqlite3.connect(tmp, isolation_level=None, check_same_thread=False)
            source.backup(target, pages=-1, progress=progress)
        except sqlite3.Error as error:
            if _sqlite_busy(error):
                raise BackupAborted("An add-on kept a database busy while the snapshot was taken",
                                    "busy_database") from None
            return False
        finally:
            for connection in (target, source):
                if connection is not None:
                    connection.close()
        _check_stop(should_stop)
        try:
            shutil.copystat(src, tmp, follow_symlinks=False)
        except OSError:
            pass
        os.replace(tmp, dst)
        copied = True
        return True
    finally:
        if not copied:
            for path in (tmp, tmp + "-journal", tmp + "-wal", tmp + "-shm"):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _copytree(src, dst, skip_top=(), should_stop=None, preserve_files=(), exclude=None, snapshot=False):
    """Copy the regular files under src into dst. Symlinks are skipped on both sides:
    a link in src is not followed, and a link in dst is replaced, never written through.

    Each file is replaced atomically. ``should_stop`` is asked during traversal and copying;
    when it returns true the copy raises BackupAborted. Files for which ``exclude`` is true
    are not copied. With ``snapshot`` (taking a backup of a live folder), transient files
    (SQLite -shm indexes, atomic-write temporaries) are left out, and a file removed between
    listing and copying is skipped rather than failing the whole backup, except a SQLite
    -wal or -journal, whose loss raises BackupAborted so the snapshot is retried later.

    Also with ``snapshot``, a SQLite database is copied through SQLite (_copy_sqlite), so a
    database its add-on is writing is never torn; its -wal/-journal/-shm files are then left
    out, as the copy already holds their committed contents. The returned list names exactly
    the files written to ``dst`` (manifests record its length and restores check it)."""
    files = []
    if not src or not os.path.isdir(src):
        if src and tvos_storage.userdata(src):
            raise ValueError("tvOS source directory is missing; virtual XML cannot be enumerated safely")
        return files
    os.makedirs(dst, exist_ok=True)
    listed = [rel for rel in _source_files(src, skip_top, should_stop, exclude) if rel not in preserve_files]
    consistent = set()  # databases copied through SQLite
    if snapshot:
        # A database's side files are handled after the database itself (see above).
        names = set(listed)
        sides = [rel for rel in listed if _SQLITE_SIDE.search(rel) and _SQLITE_SIDE.sub("", rel) in names]
        side_set = set(sides)
        listed = [rel for rel in listed if rel not in side_set] + sides
    for rel_file in listed:
        if snapshot and _SQLITE_SIDE.search(rel_file) and _SQLITE_SIDE.sub("", rel_file) in consistent:
            continue
        if snapshot and _TRANSIENT.search(os.path.basename(rel_file)):
            continue
        _check_stop(should_stop)
        target = dst
        for part in os.path.dirname(rel_file).split(os.sep) if os.path.dirname(rel_file) else []:
            target = os.path.join(target, part)
            if os.path.islink(target):
                os.remove(target)
            if not os.path.isdir(target):
                os.makedirs(target)
        d = os.path.join(dst, rel_file)
        if os.path.islink(d):
            os.remove(d)
        source = os.path.join(src, rel_file)
        try:
            if snapshot and _is_sqlite(source) and _copy_sqlite(source, d, should_stop):
                consistent.add(rel_file)
            elif should_stop is None:
                _copy_file(source, d)
            else:
                _copy_file(source, d, should_stop=should_stop)
        except FileNotFoundError:
            if snapshot and _SQLITE_SIDE.search(rel_file):
                # SQLite folded it into (or rolled back) its database after the database
                # was copied: that copy may be stale or torn, even if a new side file has
                # appeared since. Retry later.
                raise BackupAborted("A database changed while the snapshot was taken", "busy_database") from None
            if snapshot and not os.path.lexists(source):
                continue  # Deleted after it was listed: it is simply not in this snapshot.
            raise
        files.append(rel_file)
    return files


@contextlib.contextmanager
def discard_on_failure(dest):
    """Remove a snapshot folder whose copy did not finish.

    An unfinished snapshot has no manifest, so it is never listed, restored or
    pruned: without this it would hold its disk space forever.
    """
    try:
        yield
    except BaseException:
        tvos_storage.rmtree(dest, ignore_errors=True)
        raise


def allocate_backup(scope, protect=()):
    """Reserve a unique directory before copying; never reuse a prior snapshot.

    Allocation never prunes: only a completed snapshot may replace an older
    recovery point. Call finish_backup after all files have been copied.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_id = timestamp + "-" + uuid.uuid4().hex
    destination = _backup_path(scope, backup_id)
    os.makedirs(destination, exist_ok=False)
    return timestamp, backup_id, destination


def _in_use_key(folder):
    return os.path.normcase(os.path.abspath(folder))


def _in_use(folder):
    with _PRUNE_LOCK:
        return _IN_USE.get(_in_use_key(folder), 0) > 0


def _hold(folder):
    """Mark a snapshot folder as in use by a restore: pruning and deleting skip it."""
    key = _in_use_key(folder)
    with _PRUNE_LOCK:
        _IN_USE[key] = _IN_USE.get(key, 0) + 1
    return key


def _release(key):
    with _PRUNE_LOCK:
        count = _IN_USE.get(key, 0) - 1
        if count > 0:
            _IN_USE[key] = count
        else:
            _IN_USE.pop(key, None)


@contextlib.contextmanager
def _restoring(snapshot):
    """Serialise restores and keep ``snapshot`` and the undo snapshots this restore
    takes (see finish_backup) safe from pruning until the restore has finished."""
    with _RESTORE_LOCK:
        outer = getattr(_HELD, "keys", None)
        keys = [_hold(snapshot)]
        _HELD.keys = keys
        try:
            yield
        finally:
            if outer is None:
                del _HELD.keys
            else:
                _HELD.keys = outer
                outer.extend(keys)  # a nested restore's snapshots stay held by the outer one
                keys = []
            for key in keys:
                _release(key)


def prune(scope, keep=None):
    """Delete the oldest snapshots in a scope beyond the retention limit.

    IDs start with a sortable timestamp; modification time breaks ties within
    one second. Snapshots in ``keep`` (an id or a set of ids) and snapshots a
    restore is using are never removed.
    """
    keep = {keep} if isinstance(keep, str) else set(keep or ())
    root = _backup_path(scope)
    with _PRUNE_LOCK:
        try:
            names = [n for n in os.listdir(root) if not os.path.islink(os.path.join(root, n))
                     and _read_manifest(os.path.join(root, n)).get("backup_id") == n]
        except OSError:
            return []
        names.sort(key=lambda n: (n[:15], os.path.getmtime(os.path.join(root, n))), reverse=True)
        removed = []
        for name in names[_retention:]:
            if name in keep or _in_use(os.path.join(root, name)):
                continue
            tvos_storage.rmtree(os.path.join(root, name), ignore_errors=True)
            removed.append(name)
        return removed


def _replace_tree(src, dst, skip_top=(), expected_files=None, preserve_files=(), preserve=None):
    """Make dst match src: copy every file from src, then remove files that src lacks.

    Top-level folders in `skip_top` are left untouched on both sides, as are files
    in ``preserve_files`` or for which ``preserve(relative path)`` is true. Refuses
    (ValueError, before touching dst) when src is missing, when it holds a
    different number of files than its manifest recorded, or when it is empty
    and the manifest does not say the snapshot was empty.
    """
    if not src or not os.path.isdir(src) or os.path.islink(src):
        raise ValueError("Backup contents are missing; nothing was restored")
    count = len(_source_files(src, skip_top))
    if expected_files is not None and count != expected_files:
        raise ValueError("Backup is incomplete (%d of %d files); nothing was restored" % (count, expected_files))
    if expected_files is None and count == 0:
        raise ValueError("Backup is empty; nothing was restored")
    _drop_stale_sqlite_sides(src, dst, skip_top, preserve)
    wanted = set(_copytree(src, dst, skip_top, preserve_files=preserve_files, exclude=preserve)) | set(preserve_files)
    for root, _dirs, names in tvos_storage.walk(dst, topdown=False):
        rel = os.path.relpath(root, dst)
        if rel.split(os.sep)[0] in skip_top:
            continue
        for name in names:
            path = os.path.join(root, name)
            rel_path = os.path.relpath(path, dst)
            if rel_path not in wanted and not (preserve is not None and preserve(rel_path)):
                _remove_if_present(path)
        if (root != dst and not os.path.islink(root) and not (preserve is not None and preserve(rel))
                and not tvos_storage.listdir(root)):
            os.rmdir(root)


def _drop_stale_sqlite_sides(src, dst, skip_top=(), preserve=None):
    """Before a snapshot's database replaces a live one, remove the live database's
    -wal/-journal when the snapshot has none (snapshots copy databases through SQLite):
    SQLite would otherwise apply the old database's pages to the restored one."""
    if not os.path.isdir(dst):
        return
    for rel in _source_files(src, skip_top):
        if _SQLITE_SIDE.search(rel) or not _is_sqlite(os.path.join(src, rel)):
            continue
        for suffix in ("-wal", "-journal"):
            side = rel + suffix
            live = os.path.join(dst, side)
            if (os.path.lexists(os.path.join(src, side)) or (preserve is not None and preserve(side))
                    or os.path.islink(live) or not tvos_storage.is_file(live)):
                continue
            _remove_if_present(live)


def _remove_if_present(path):
    """Remove a live file; one its add-on removed meanwhile (a committed journal) is already gone."""
    try:
        tvos_storage.remove(path)
    except FileNotFoundError:
        pass


def _restore_folder(aid, src, dest, skip, expected):
    """Make the live folder of ``aid`` match a snapshot (see _replace_tree)."""
    # Never transiently replace the live token/identity with snapshot values:
    # concurrent authenticated reads must see the same owner throughout restore.
    # Its internal stores (operation history, fix undo copies, caches) stay as they are.
    _replace_tree(src, dest, skip, expected_files=expected,
                  preserve_files=SELF_KEEP if aid == SELF_ID else (),
                  preserve=_self_preserved if aid == SELF_ID else None)


def _write_manifest(dest, manifest):
    atomic_write_json(os.path.join(dest, "manifest.json"), manifest, indent=2)


def _read_manifest(dest, strict=False):
    try:
        with open(os.path.join(dest, "manifest.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("Expected backup metadata object")
        return data
    except FileNotFoundError:
        return {}  # Older snapshots may have no manifest.
    except (OSError, ValueError):
        if strict:
            raise ValueError("Backup metadata is unreadable or invalid; nothing was restored") from None
        return {}


def finish_backup(scope, dest, manifest, protect=()):
    """Commit the snapshot before retention can discard older recovery points.

    During a restore (an undo snapshot), the new snapshot stays in use until the
    restore has finished, so a concurrent prune cannot remove it."""
    with _PRUNE_LOCK:
        _write_manifest(dest, manifest)
        held = getattr(_HELD, "keys", None)
        if held is not None:
            held.append(_hold(dest))
        capture_backup(manifest["backup_id"])
        prune(scope, keep=set(protect) | {manifest["backup_id"]})


@_with_backup_root
def create_backup(addon_info, kodi_version="", adapter="", protect=(), should_stop=None):
    """Snapshot one add-on's addon_data. ``should_stop`` (optional) aborts and discards it."""
    aid = addon_info["addon_id"]
    ts, backup_id, dest = allocate_backup(aid, protect)
    src = live_addon_data(addon_info)
    with discard_on_failure(dest):
        files = _copytree(src, os.path.join(dest, "addon_data"), skip_top=("backups",) if aid == SELF_ID else (),
                          should_stop=should_stop,
                          exclude=_self_state if aid == SELF_ID else None, snapshot=True)
        manifest = {
            "backup_id": backup_id,
            "addon_id": aid,
            "addon_name": addon_info.get("name", ""),
            "addon_version": addon_info.get("version", ""),
            "timestamp": ts,
            "files_copied": len(files),
            "Kodi version": kodi_version,
            "adapter": adapter or addon_info.get("adapter_name", ""),
        }
        os.makedirs(os.path.join(dest, "addon_data"), exist_ok=True)
        finish_backup(aid, dest, manifest, protect)
    return manifest


@_with_backup_root
def create_file_backup(scope, files, kodi_version="", note=""):
    """Snapshot only the given files: {relative name: absolute path}. Missing files are recorded."""
    ts, backup_id, dest = allocate_backup(scope)
    copied, missing = [], []
    with discard_on_failure(dest):
        for rel, path in sorted(files.items()):
            target = _backup_path(scope, backup_id, *rel.split("/"))
            if path and tvos_storage.is_file(path) and not os.path.islink(path):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                _copy_file(path, target)
                copied.append(rel)
            else:
                missing.append(rel)
        manifest = {"backup_id": backup_id, "timestamp": ts, "included_files": copied, "missing_files": missing,
                    "included_components": sorted({rel.split("/")[0] for rel in copied}),
                    "skipped_components": [], "Kodi version": kodi_version, "note": note}
        finish_backup(scope, dest, manifest)
    return manifest


def list_backups(addon_id=None, stack=False):
    root = _backup_path("_stack" if stack else addon_id) if stack or addon_id else _active_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        folder = os.path.join(root, name)
        manifest = _read_manifest(folder) if not os.path.islink(folder) else {}
        if manifest.get("backup_id") == name:
            out.append(manifest)
    return out


@_with_backup_root
def restore_backup(addon_info, backup_id, should_stop=None):
    """Make an add-on's addon_data match one of its snapshots, after taking an undo snapshot.

    ``should_stop`` (optional) can stop the undo snapshot (BackupAborted), before the
    live folder is touched; once replacing has begun the restore runs to completion.
    """
    aid = addon_info["addon_id"]
    snapshot = _backup_path(aid, backup_id)
    with _restoring(snapshot):
        src = os.path.join(snapshot, "addon_data")
        if not os.path.isdir(src):
            raise ValueError("Backup not found")
        manifest = _read_manifest(snapshot, strict=True)
        expected = manifest.get("files_copied") if isinstance(manifest.get("files_copied"), int) else None
        skip = ("backups",) if aid == SELF_ID else ()
        # Check before taking the undo snapshot, whose prune must not remove this one.
        count = len(_source_files(src, skip))
        if (expected is not None and count != expected) or (expected is None and count == 0):
            raise ValueError("Backup is incomplete or empty; nothing was restored")
        dest = live_addon_data(addon_info)
        undo = create_backup(addon_info, adapter=addon_info.get("adapter_name", ""), protect=(backup_id,),
                             should_stop=should_stop)
        _check_stop(should_stop)
        try:
            _restore_folder(aid, src, dest, skip, expected)
        except BaseException as exc:
            _roll_back([(aid, dest, skip, undo)], exc)
            raise
    return {"restored": True, "backup_id": backup_id,
            "undo_backup_id": undo["backup_id"], "restart_required": True}


def _roll_back(done, error):
    """Put back the live folders a failed restore already touched, newest first.

    ``done`` holds (addon_id, live folder, skip_top, undo manifest). If a
    rollback itself fails, the error names the undo snapshot to restore by hand.
    """
    failed = []
    for aid, dest, skip, undo in reversed(done):
        undo_src = os.path.join(_backup_path(aid, undo["backup_id"]), "addon_data")
        try:
            _restore_folder(aid, undo_src, dest, skip, undo.get("files_copied"))
        except Exception:
            failed.append("%s (undo backup %s)" % (aid, undo["backup_id"]))
    if failed:
        raise RuntimeError("Restore failed (%s) and could not be rolled back for %s; restore those undo "
                           "backups" % (type(error).__name__, ", ".join(failed))) from error


@_with_backup_root
def create_stack_backup(addons, kodi_version="", note="", should_stop=None):
    """Snapshot several add-ons' addon_data. ``should_stop`` (optional) aborts and discards it."""
    ts, backup_id, root = allocate_backup("_stack")
    included, skipped, counts, total_bytes = [], [], {}, 0
    with discard_on_failure(root):
        for addon in addons:
            if not addon or not addon.get("addon_id"):
                continue
            src = translate(addon.get("addon_data_path") or "")
            if src and os.path.isdir(src):
                files = _copytree(src, os.path.join(root, addon["addon_id"]),
                                  skip_top=("backups",) if addon["addon_id"] == SELF_ID else (),
                                  should_stop=should_stop,
                                  exclude=_self_state if addon["addon_id"] == SELF_ID else None, snapshot=True)
                os.makedirs(os.path.join(root, addon["addon_id"]), exist_ok=True)
                counts[addon["addon_id"]] = len(files)
                for rel in files:
                    try:
                        total_bytes += tvos_storage.size(os.path.join(root, addon["addon_id"], rel))
                    except OSError:
                        pass
                included.append(addon["addon_id"])
            else:
                skipped.append(addon["addon_id"])
        manifest = {"backup_id": backup_id, "timestamp": ts, "included_folders": included, "skipped_folders": skipped,
                    "file_counts": counts, "total_bytes": total_bytes, "Kodi version": kodi_version, "note": note}
        finish_backup("_stack", root, manifest)
    return manifest


def delete_stack_backup(backup_id):
    """Delete one stack snapshot; False if it is missing or a restore is using it."""
    root = _backup_path("_stack", backup_id)
    with _PRUNE_LOCK:
        if os.path.isdir(root) and not os.path.islink(root) and not _in_use(root):
            tvos_storage.rmtree(root)
            return True
        return False


@_with_backup_root
def restore_stack_backup(index, backup_id, should_stop=None):
    """Restore every component of a stack snapshot, after taking an undo snapshot of each.

    ``should_stop`` (optional) can stop the undo snapshots (BackupAborted), which are all
    taken before the first live folder is touched; replacing then runs to completion.
    """
    root = _backup_path("_stack", backup_id)
    with _restoring(root):
        return _restore_stack(index, backup_id, root, should_stop)


def _restore_stack(index, backup_id, root, should_stop):
    if not os.path.isdir(root):
        raise ValueError("Stack backup not found")
    manifest = _read_manifest(root, strict=True)
    counts = manifest.get("file_counts") or {}
    if not isinstance(counts, dict):
        raise ValueError("Stack backup metadata is invalid; nothing was restored")
    folders = os.listdir(root)
    if "included_folders" in manifest:
        folders = manifest["included_folders"]
        if (not isinstance(folders, list) or any(not isinstance(aid, str) for aid in folders)
                or len(folders) != len(set(folders))):
            raise ValueError("Stack backup metadata is invalid; nothing was restored")
        for aid in folders:
            src = _backup_path("_stack", backup_id, aid)
            if not os.path.isdir(src) or os.path.islink(src):
                raise ValueError("Stack backup is incomplete; nothing was restored")
    restored, skipped, undo_backups = [], [], {}
    plan = []
    for aid in sorted(folders):
        src = os.path.join(root, aid)
        if aid == "manifest.json" or not os.path.isdir(src) or os.path.islink(src):
            continue
        addon = index.get(aid)
        dest = live_addon_data(addon) if addon else ""
        if not (addon and dest):
            skipped.append(aid)
            continue
        skip = ("backups",) if aid == SELF_ID else ()
        expected = counts.get(aid) if isinstance(counts.get(aid), int) else None
        count = len(_source_files(src, skip))
        if expected is not None and count != expected:
            raise ValueError("Stack backup is incomplete for %s; nothing was restored" % aid)
        if expected is None and count == 0:
            # Older snapshots did not record file counts: never empty a live folder from one.
            skipped.append(aid)
            continue
        plan.append((aid, addon, src, dest, skip, expected))
    # Every component is checked, and its undo snapshot taken, before the first one
    # is replaced: a busy database or a stop request then leaves everything as it was.
    # A failure part way through replacing puts every component already touched back.
    undos = []
    for aid, addon, _src, _dest, _skip, _expected in plan:
        undo = create_backup(addon, adapter=addon.get("adapter_name", ""), should_stop=should_stop)
        undo_backups[aid] = undo["backup_id"]
        undos.append(undo)
    _check_stop(should_stop)
    done = []
    try:
        for (aid, _addon, src, dest, skip, expected), undo in zip(plan, undos):
            done.append((aid, dest, skip, undo))
            _restore_folder(aid, src, dest, skip, expected)
            restored.append(aid)
    except BaseException as exc:
        _roll_back(done, exc)
        raise
    return {"restored": restored, "skipped": skipped, "undo_backups": undo_backups, "restart_required": True}
