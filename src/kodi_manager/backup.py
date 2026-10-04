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


def _copytree(src, dst):
    files = []
    if not os.path.exists(src):
        return files
    os.makedirs(dst, exist_ok=True)
    for root, dirs, names in os.walk(src):
        rel = os.path.relpath(root, src)
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
    return timestamp, backup_id, destination


def create_backup(addon_info, kodi_version="", adapter=""):
    aid = addon_info["addon_id"]
    ts, backup_id, dest = allocate_backup(aid)
    src = addon_info.get("addon_data_path") or translate("special://profile/addon_data/%s" % aid)
    files = _copytree(src, os.path.join(dest, "addon_data"))
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
    _copytree(src, dest)
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
            _copytree(src, os.path.join(root, addon["addon_id"]))
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
    restored, undo_backups = [], {}
    for aid in os.listdir(root):
        src = os.path.join(root, aid)
        if aid == "manifest.json" or not os.path.isdir(src):
            continue
        addon = index.get(aid)
        if addon:
            undo = create_backup(addon, adapter=addon.get("adapter_name", ""))
            undo_backups[aid] = undo["backup_id"]
            _copytree(src, addon["addon_data_path"])
            restored.append(aid)
    return {"restored": restored, "undo_backups": undo_backups, "restart_required": True}
