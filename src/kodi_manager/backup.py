import json
import os
import shutil
import time
from pathlib import Path
import re
import uuid

try:
    from .kodi_api import translate
except ImportError:
    from kodi_api import translate


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


def _copytree(src, dst, skip_top=()):
    files = []
    if not src or not os.path.exists(src):
        return files
    os.makedirs(dst, exist_ok=True)
    for root, dirs, names in os.walk(src):
        rel = os.path.relpath(root, src)
        if rel == ".":
            # Never copy Kodi Manager's own backup store into a snapshot of itself.
            dirs[:] = [d for d in dirs if d not in skip_top]
        target_root = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(target_root, exist_ok=True)
        for name in names:
            s = os.path.join(root, name)
            d = os.path.join(target_root, name)
            shutil.copy2(s, d)
            files.append(os.path.relpath(s, src))
    return files


def allocate_backup(scope):
    """Reserve a unique directory before copying; never reuse a prior snapshot."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_id = timestamp + "-" + uuid.uuid4().hex
    destination = _backup_path(scope, backup_id)
    os.makedirs(destination, exist_ok=False)
    prune(scope, keep=backup_id)
    return timestamp, backup_id, destination


def prune(scope, keep=None):
    """Delete the oldest snapshots in a scope beyond the retention limit.

    IDs start with a sortable timestamp; modification time breaks ties within
    one second. The snapshot just allocated (`keep`) is never removed.
    """
    root = _backup_path(scope)
    try:
        names = [n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except OSError:
        return []
    names.sort(key=lambda n: (n[:15], os.path.getmtime(os.path.join(root, n))), reverse=True)
    removed = []
    for name in names[_retention:]:
        if name == keep:
            continue
        shutil.rmtree(os.path.join(root, name), ignore_errors=True)
        removed.append(name)
    return removed


def _replace_tree(src, dst, skip_top=()):
    """Make dst match src: copy every file from src, then remove files that src lacks.

    Top-level folders in `skip_top` are left untouched on both sides.
    """
    wanted = set(_copytree(src, dst, skip_top))
    for root, dirs, names in os.walk(dst, topdown=False):
        rel = os.path.relpath(root, dst)
        if rel.split(os.sep)[0] in skip_top:
            continue
        for name in names:
            path = os.path.join(root, name)
            if os.path.relpath(path, dst) not in wanted:
                os.remove(path)
        if root != dst and not os.listdir(root):
            os.rmdir(root)


def create_backup(addon_info, kodi_version="", adapter=""):
    aid = addon_info["addon_id"]
    ts, backup_id, dest = allocate_backup(aid)
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
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
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
    src = _backup_path(aid, backup_id, "addon_data")
    if not os.path.isdir(src):
        raise ValueError("Backup not found")
    dest = addon_info.get("addon_data_path") or translate("special://profile/addon_data/%s" % aid)
    undo = create_backup(addon_info, adapter=addon_info.get("adapter_name", ""))
    _replace_tree(src, dest, ("backups",) if aid == SELF_ID else ())
    return {"restored": True, "backup_id": backup_id,
            "undo_backup_id": undo["backup_id"], "restart_required": True}


def create_stack_backup(addons, kodi_version=""):
    ts, backup_id, root = allocate_backup("_stack")
    included, skipped = [], []
    for addon in addons:
        if not addon or not addon.get("addon_id"):
            continue
        src = addon.get("addon_data_path")
        if src and os.path.isdir(src):
            _copytree(src, os.path.join(root, addon["addon_id"]), skip_top=("backups",) if addon["addon_id"] == SELF_ID else ())
            included.append(addon["addon_id"])
        else:
            skipped.append(addon["addon_id"])
    manifest = {"backup_id": backup_id, "timestamp": ts, "included_folders": included, "skipped_folders": skipped, "Kodi version": kodi_version}
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def restore_stack_backup(index, backup_id):
    root = _backup_path("_stack", backup_id)
    if not os.path.isdir(root):
        raise ValueError("Stack backup not found")
    restored, skipped, undo_backups = [], [], {}
    for aid in os.listdir(root):
        src = os.path.join(root, aid)
        if aid == "manifest.json" or not os.path.isdir(src):
            continue
        addon = index.get(aid)
        dest = (addon or {}).get("addon_data_path") or (translate("special://profile/addon_data/%s" % aid) if addon else "")
        if addon and dest:
            undo = create_backup(addon, adapter=addon.get("adapter_name", ""))
            undo_backups[aid] = undo["backup_id"]
            _replace_tree(src, dest, ("backups",) if aid == SELF_ID else ())
            restored.append(aid)
        else:
            skipped.append(aid)
    return {"restored": restored, "skipped": skipped, "undo_backups": undo_backups, "restart_required": True}
