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
    from .fsutil import atomic_write_bytes, atomic_write_json
    from .operation_records import capture_backup
except ImportError:
    import tvos_storage
    from kodi_api import translate
    from fsutil import atomic_write_bytes, atomic_write_json
    from operation_records import capture_backup


DEFAULT_RETENTION = 20


class BackupAborted(Exception):
    """A snapshot was stopped on request (for example because playback started).

    The partial snapshot is discarded; ``deferred`` tells callers to retry later.
    """
    deferred = True
_retention = DEFAULT_RETENTION
SELF_ID = "service.kodi.addonadmin"
# Kodi Manager's access token and LAN/write switches are only changed in Kodi:
# restoring an old copy of its own folder keeps the live settings.xml, so a
# replaced token or a LAN switch turned off cannot come back from a backup.
SELF_KEEP = ("settings.xml", "device_identity.xml")
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


def _source_files(src, skip_top=(), should_stop=None):
    """Relative paths of the regular files under src, never following symlinks."""
    files = []
    for root, dirs, names in tvos_storage.walk(src):
        if should_stop is not None and should_stop():
            raise BackupAborted("Snapshot stopped before it completed")
        rel = os.path.relpath(root, src)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in skip_top]
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in names:
            path = os.path.join(root, name)
            if not os.path.islink(path) and tvos_storage.is_file(path):
                files.append(os.path.relpath(path, src))
    return files


def _copy_file(src, dst, should_stop=None):
    """Copy one file via a temporary sibling, so ``dst`` is never left half-written."""
    def check_stop():
        if should_stop is not None and should_stop():
            raise BackupAborted("Snapshot stopped before it completed")

    check_stop()
    if tvos_storage.virtual_xml(src) or tvos_storage.virtual_xml(dst):
        data = tvos_storage.read_bytes(src)
        check_stop()
        atomic_write_bytes(dst, data)
        return
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(dst) + ".", suffix=".km-tmp",
                               dir=os.path.dirname(dst))
    os.close(fd)
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


def _copytree(src, dst, skip_top=(), should_stop=None, preserve_files=()):
    """Copy the regular files under src into dst. Symlinks are skipped on both sides:
    a link in src is not followed, and a link in dst is replaced, never written through.

    Each file is replaced atomically. ``should_stop`` is asked during traversal and copying;
    when it returns true the copy raises BackupAborted."""
    files = []
    if not src or not os.path.isdir(src):
        if src and tvos_storage.userdata(src):
            raise ValueError("tvOS source directory is missing; virtual XML cannot be enumerated safely")
        return files
    os.makedirs(dst, exist_ok=True)
    for rel_file in _source_files(src, skip_top, should_stop):
        if rel_file in preserve_files:
            continue
        if should_stop is not None and should_stop():
            raise BackupAborted("Snapshot stopped before it completed")
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
        if should_stop is None:
            _copy_file(os.path.join(src, rel_file), d)
        else:
            _copy_file(os.path.join(src, rel_file), d, should_stop=should_stop)
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


def prune(scope, keep=None):
    """Delete the oldest snapshots in a scope beyond the retention limit.

    IDs start with a sortable timestamp; modification time breaks ties within
    one second. Snapshots in ``keep`` (an id or a set of ids) are never removed.
    """
    keep = {keep} if isinstance(keep, str) else set(keep or ())
    root = _backup_path(scope)
    try:
        names = [n for n in os.listdir(root) if not os.path.islink(os.path.join(root, n))
                 and _read_manifest(os.path.join(root, n)).get("backup_id") == n]
    except OSError:
        return []
    names.sort(key=lambda n: (n[:15], os.path.getmtime(os.path.join(root, n))), reverse=True)
    removed = []
    for name in names[_retention:]:
        if name in keep:
            continue
        tvos_storage.rmtree(os.path.join(root, name), ignore_errors=True)
        removed.append(name)
    return removed


def _replace_tree(src, dst, skip_top=(), expected_files=None, preserve_files=()):
    """Make dst match src: copy every file from src, then remove files that src lacks.

    Top-level folders in `skip_top` are left untouched on both sides. Refuses
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
    wanted = set(_copytree(src, dst, skip_top, preserve_files=preserve_files)) | set(preserve_files)
    for root, _dirs, names in tvos_storage.walk(dst, topdown=False):
        rel = os.path.relpath(root, dst)
        if rel.split(os.sep)[0] in skip_top:
            continue
        for name in names:
            path = os.path.join(root, name)
            if os.path.relpath(path, dst) not in wanted:
                tvos_storage.remove(path)
        if root != dst and not os.path.islink(root) and not tvos_storage.listdir(root):
            os.rmdir(root)


def _restore_folder(aid, src, dest, skip, expected):
    """Make the live folder of ``aid`` match a snapshot (see _replace_tree)."""
    # Never transiently replace the live token/identity with snapshot values:
    # concurrent authenticated reads must see the same owner throughout restore.
    _replace_tree(src, dest, skip, expected_files=expected,
                  preserve_files=SELF_KEEP if aid == SELF_ID else ())


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
    """Commit the snapshot before retention can discard older recovery points."""
    _write_manifest(dest, manifest)
    capture_backup(manifest["backup_id"])
    prune(scope, keep=set(protect) | {manifest["backup_id"]})


@_with_backup_root
def create_backup(addon_info, kodi_version="", adapter="", protect=()):
    aid = addon_info["addon_id"]
    ts, backup_id, dest = allocate_backup(aid, protect)
    src = live_addon_data(addon_info)
    with discard_on_failure(dest):
        files = _copytree(src, os.path.join(dest, "addon_data"), skip_top=("backups",) if aid == SELF_ID else ())
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
def restore_backup(addon_info, backup_id):
    aid = addon_info["addon_id"]
    snapshot = _backup_path(aid, backup_id)
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
    undo = create_backup(addon_info, adapter=addon_info.get("adapter_name", ""), protect=(backup_id,))
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
                                  should_stop=should_stop)
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
    root = _backup_path("_stack", backup_id)
    if os.path.isdir(root) and not os.path.islink(root):
        tvos_storage.rmtree(root)
        return True
    return False


@_with_backup_root
def restore_stack_backup(index, backup_id):
    root = _backup_path("_stack", backup_id)
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
    # Every component is checked before the first one is replaced. A failure part
    # way through puts every component already touched back as it was.
    # That includes a failure to take a later component's undo snapshot.
    done = []
    try:
        for aid, addon, src, dest, skip, expected in plan:
            undo = create_backup(addon, adapter=addon.get("adapter_name", ""))
            undo_backups[aid] = undo["backup_id"]
            done.append((aid, dest, skip, undo))
            _restore_folder(aid, src, dest, skip, expected)
            restored.append(aid)
    except BaseException as exc:
        _roll_back(done, exc)
        raise
    return {"restored": restored, "skipped": skipped, "undo_backups": undo_backups, "restart_required": True}
