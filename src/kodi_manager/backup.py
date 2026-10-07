import json
import os
import shutil
import time
from pathlib import Path
import re
import uuid

try:
    from .kodi_api import translate
    from .fsutil import atomic_write_json
except ImportError:
    from kodi_api import translate
    from fsutil import atomic_write_json


DEFAULT_RETENTION = 20
_retention = DEFAULT_RETENTION
SELF_ID = "service.kodi.addonadmin"


def set_retention(count):
    """Keep at most `count` snapshots per scope (add-on, _stack, pipeline); minimum 1."""
    global _retention
    try:
        _retention = max(1, int(count))
    except (TypeError, ValueError):
        _retention = DEFAULT_RETENTION


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


def _copytree(src, dst, skip_top=()):
    """Copy the regular files under src into dst. Symlinks are skipped on both sides:
    a link in src is not followed, and a link in dst is replaced, never written through."""
    files = []
    if not src or not os.path.isdir(src):
        return files
    os.makedirs(dst, exist_ok=True)
    for rel_file in _source_files(src, skip_top):
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
        shutil.copy2(os.path.join(src, rel_file), d, follow_symlinks=False)
        files.append(rel_file)
    return files


def allocate_backup(scope, protect=()):
    """Reserve a unique directory before copying; never reuse a prior snapshot.

    The new snapshot and every id in ``protect`` (for example the snapshot
    being restored) are exempt from the retention prune.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_id = timestamp + "-" + uuid.uuid4().hex
    destination = _backup_path(scope, backup_id)
    os.makedirs(destination, exist_ok=False)
    prune(scope, keep=set(protect) | {backup_id})
    return timestamp, backup_id, destination


def prune(scope, keep=None):
    """Delete the oldest snapshots in a scope beyond the retention limit.

    IDs start with a sortable timestamp; modification time breaks ties within
    one second. Snapshots in ``keep`` (an id or a set of ids) are never removed.
    """
    keep = {keep} if isinstance(keep, str) else set(keep or ())
    root = _backup_path(scope)
    try:
        names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
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


def _write_manifest(dest, manifest):
    atomic_write_json(os.path.join(dest, "manifest.json"), manifest, indent=2)


def _read_manifest(dest):
    try:
        with open(os.path.join(dest, "manifest.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def create_backup(addon_info, kodi_version="", adapter="", protect=()):
    aid = addon_info["addon_id"]
    ts, backup_id, dest = allocate_backup(aid, protect)
    src = addon_info.get("addon_data_path") or translate("special://profile/addon_data/%s" % aid)
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
    _write_manifest(dest, manifest)
    return manifest


def create_file_backup(scope, files, kodi_version="", note=""):
    """Snapshot only the given files: {relative name: absolute path}. Missing files are recorded."""
    ts, backup_id, dest = allocate_backup(scope)
    copied, missing = [], []
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
    _write_manifest(dest, manifest)
    return manifest


def list_backups(addon_id=None, stack=False):
    root = _backup_path("_stack" if stack else addon_id) if stack or addon_id else backup_root()
    if not os.path.isdir(root):
        return []
    out = []
    for name in sorted(os.listdir(root), reverse=True):
        man = os.path.join(root, name, "manifest.json")
        if os.path.exists(man):
            with open(man, "r", encoding="utf-8") as fh:
                out.append(json.load(fh))
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
    dest = addon_info.get("addon_data_path") or translate("special://profile/addon_data/%s" % aid)
    undo = create_backup(addon_info, adapter=addon_info.get("adapter_name", ""), protect=(backup_id,))
    _replace_tree(src, dest, skip, expected_files=expected)
    return {"restored": True, "backup_id": backup_id,
            "undo_backup_id": undo["backup_id"], "restart_required": True}


def create_stack_backup(addons, kodi_version=""):
    ts, backup_id, root = allocate_backup("_stack")
    included, skipped, counts = [], [], {}
    for addon in addons:
        if not addon or not addon.get("addon_id"):
            continue
        src = addon.get("addon_data_path")
        if src and os.path.isdir(src):
            files = _copytree(src, os.path.join(root, addon["addon_id"]), skip_top=("backups",) if addon["addon_id"] == SELF_ID else ())
            os.makedirs(os.path.join(root, addon["addon_id"]), exist_ok=True)
            counts[addon["addon_id"]] = len(files)
            included.append(addon["addon_id"])
        else:
            skipped.append(addon["addon_id"])
    manifest = {"backup_id": backup_id, "timestamp": ts, "included_folders": included, "skipped_folders": skipped,
                "file_counts": counts, "Kodi version": kodi_version}
    _write_manifest(root, manifest)
    return manifest


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
        dest = (addon or {}).get("addon_data_path") or (translate("special://profile/addon_data/%s" % aid) if addon else "")
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
    # Every component is checked before the first one is replaced.
    for aid, addon, src, dest, skip, expected in plan:
        undo = create_backup(addon, adapter=addon.get("adapter_name", ""))
        undo_backups[aid] = undo["backup_id"]
        _replace_tree(src, dest, skip, expected_files=expected)
        restored.append(aid)
    return {"restored": restored, "skipped": skipped, "undo_backups": undo_backups, "restart_required": True}
