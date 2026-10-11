import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
import re
import uuid

try:
    from .kodi_api import translate
    from .fsutil import atomic_write_bytes, atomic_write_json
except ImportError:
    from kodi_api import translate
    from fsutil import atomic_write_bytes, atomic_write_json


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
SELF_KEEP = ("settings.xml",)


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
        shutil.rmtree(os.path.join(folder, name), ignore_errors=True)
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
    root = Path(backup_root()).resolve()
    target = root.joinpath(*parts)
    if root not in target.resolve().parents:
        raise ValueError('Backup path leaves its directory')
    return str(target)


def _source_files(src, skip_top=()):
    """Relative paths of the regular files under src, never following symlinks."""
    files = []
    for root, dirs, names in os.walk(src):
        rel = os.path.relpath(root, src)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in skip_top]
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in names:
            path = os.path.join(root, name)
            if not os.path.islink(path) and os.path.isfile(path):
                files.append(os.path.relpath(path, src))
    return files


def _copy_file(src, dst):
    """Copy one file via a temporary sibling, so ``dst`` is never left half-written."""
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(dst) + ".", suffix=".km-tmp",
                               dir=os.path.dirname(dst))
    os.close(fd)
    try:
        shutil.copy2(src, tmp, follow_symlinks=False)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _copytree(src, dst, skip_top=(), should_stop=None):
    """Copy the regular files under src into dst. Symlinks are skipped on both sides:
    a link in src is not followed, and a link in dst is replaced, never written through.

    Each file is replaced atomically. ``should_stop`` is asked before every file;
    when it returns true the copy raises BackupAborted."""
    files = []
    if not src or not os.path.isdir(src):
        return files
    os.makedirs(dst, exist_ok=True)
    for rel_file in _source_files(src, skip_top):
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
        _copy_file(os.path.join(src, rel_file), d)
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
        shutil.rmtree(dest, ignore_errors=True)
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
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)
        removed.append(name)
    return removed


def _replace_tree(src, dst, skip_top=(), expected_files=None):
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
    wanted = set(_copytree(src, dst, skip_top))
    for root, _dirs, names in os.walk(dst, topdown=False):
        rel = os.path.relpath(root, dst)
        if rel.split(os.sep)[0] in skip_top:
            continue
        for name in names:
            path = os.path.join(root, name)
            if os.path.relpath(path, dst) not in wanted:
                os.remove(path)
        if root != dst and not os.path.islink(root) and not os.listdir(root):
            os.rmdir(root)


def _restore_folder(aid, src, dest, skip, expected):
    """Make the live folder of ``aid`` match a snapshot (see _replace_tree)."""
    kept = {}
    if aid == SELF_ID:
        for name in SELF_KEEP:
            path = os.path.join(dest, name)
            if os.path.isfile(path) and not os.path.islink(path):
                with open(path, "rb") as handle:
                    kept[name] = handle.read()
            else:
                kept[name] = None
    _replace_tree(src, dest, skip, expected_files=expected)
    for name, data in kept.items():
        path = os.path.join(dest, name)
        if data is not None:
            atomic_write_bytes(path, data)
        elif os.path.isfile(path) and not os.path.islink(path):
            os.remove(path)


def _write_manifest(dest, manifest):
    atomic_write_json(os.path.join(dest, "manifest.json"), manifest, indent=2)


def _read_manifest(dest):
    try:
        with open(os.path.join(dest, "manifest.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def finish_backup(scope, dest, manifest, protect=()):
    """Commit the snapshot before retention can discard older recovery points."""
    _write_manifest(dest, manifest)
    prune(scope, keep=set(protect) | {manifest["backup_id"]})


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


def create_file_backup(scope, files, kodi_version="", note=""):
    """Snapshot only the given files: {relative name: absolute path}. Missing files are recorded."""
    ts, backup_id, dest = allocate_backup(scope)
    copied, missing = [], []
    with discard_on_failure(dest):
        for rel, path in sorted(files.items()):
            target = _backup_path(scope, backup_id, *rel.split("/"))
            if path and os.path.isfile(path) and not os.path.islink(path):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(path, target, follow_symlinks=False)
                copied.append(rel)
            else:
                missing.append(rel)
        manifest = {"backup_id": backup_id, "timestamp": ts, "included_files": copied, "missing_files": missing,
                    "included_components": sorted({rel.split("/")[0] for rel in copied}),
                    "skipped_components": [], "Kodi version": kodi_version, "note": note}
        finish_backup(scope, dest, manifest)
    return manifest


def list_backups(addon_id=None, stack=False):
    root = _backup_path("_stack" if stack else addon_id) if stack or addon_id else backup_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        folder = os.path.join(root, name)
        manifest = _read_manifest(folder) if not os.path.islink(folder) else {}
        if manifest.get("backup_id") == name:
            out.append(manifest)
    return out


def restore_backup(addon_info, backup_id):
    aid = addon_info["addon_id"]
    snapshot = _backup_path(aid, backup_id)
    src = os.path.join(snapshot, "addon_data")
    if not os.path.isdir(src):
        raise ValueError("Backup not found")
    manifest = _read_manifest(snapshot)
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
            _replace_tree(undo_src, dest, skip, expected_files=undo.get("files_copied"))
        except Exception:
            failed.append("%s (undo backup %s)" % (aid, undo["backup_id"]))
    if failed:
        raise RuntimeError("Restore failed (%s) and could not be rolled back for %s; restore those undo "
                           "backups" % (type(error).__name__, ", ".join(failed))) from error


def create_stack_backup(addons, kodi_version="", note="", should_stop=None):
    """Snapshot several add-ons' addon_data. ``should_stop`` (optional) aborts and discards it."""
    ts, backup_id, root = allocate_backup("_stack")
    included, skipped, counts = [], [], {}
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
                included.append(addon["addon_id"])
            else:
                skipped.append(addon["addon_id"])
        manifest = {"backup_id": backup_id, "timestamp": ts, "included_folders": included, "skipped_folders": skipped,
                    "file_counts": counts, "Kodi version": kodi_version, "note": note}
        finish_backup("_stack", root, manifest)
    return manifest


def delete_stack_backup(backup_id):
    root = _backup_path("_stack", backup_id)
    if os.path.isdir(root) and not os.path.islink(root):
        shutil.rmtree(root)
        return True
    return False


def restore_stack_backup(index, backup_id):
    root = _backup_path("_stack", backup_id)
    if not os.path.isdir(root):
        raise ValueError("Stack backup not found")
    counts = _read_manifest(root).get("file_counts") or {}
    restored, skipped, undo_backups = [], [], {}
    plan = []
    for aid in sorted(os.listdir(root)):
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
    done = []
    for aid, addon, src, dest, skip, expected in plan:
        undo = create_backup(addon, adapter=addon.get("adapter_name", ""))
        undo_backups[aid] = undo["backup_id"]
        done.append((aid, dest, skip, undo))
        try:
            _restore_folder(aid, src, dest, skip, expected)
        except BaseException as exc:
            _roll_back(done, exc)
            raise
        restored.append(aid)
    return {"restored": restored, "skipped": skipped, "undo_backups": undo_backups, "restart_required": True}
