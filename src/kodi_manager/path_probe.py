import os

try:
    import xbmc
    import xbmcvfs
except ImportError:
    xbmc = xbmcvfs = None

EXPECTED_ADDON_DATA_IDS = [
    "skin.bingie",
    "plugin.video.tmdb.bingie.helper",
    "plugin.video.fenlight",
    "plugin.video.fen",
    "script.module.cocoscrapers",
]

ANDROID_KODI_ROOTS = [
    "/storage/emulated/0/Android/data/org.xbmc.kodi/files/.kodi",
    "/sdcard/Android/data/org.xbmc.kodi/files/.kodi",
    "/mnt/sdcard/Android/data/org.xbmc.kodi/files/.kodi",
]


def translate_special(path):
    try:
        if xbmcvfs:
            return xbmcvfs.translatePath(path)
    except Exception:
        pass
    try:
        if xbmc and hasattr(xbmc, "translatePath"):
            return xbmc.translatePath(path)
    except Exception:
        pass
    if path.startswith("special://profile/"):
        return path.replace("special://profile/", os.path.expanduser("~/.kodi/userdata/"))
    if path.startswith("special://home/"):
        return path.replace("special://home/", os.path.expanduser("~/.kodi/"))
    return path


def ensure_slash(path):
    return path if path.endswith(("/", "\\")) else path + "/"


def listdir_xbmcvfs(path):
    out = {"ok": False, "dirs": [], "files": [], "error": None, "path": path}
    if not xbmcvfs:
        out["error"] = "xbmcvfs unavailable"
        return out
    try:
        dirs, files = xbmcvfs.listdir(ensure_slash(path))
        out.update({"ok": True, "dirs": sorted([d.rstrip("/\\") for d in dirs]), "files": sorted(files)})
    except Exception as exc:
        out["error"] = str(exc)
    return out


def listdir_os(path):
    out = {"ok": False, "dirs": [], "files": [], "error": None, "path": path}
    try:
        if not os.path.isdir(path):
            out["error"] = "not a directory"
            return out
        dirs, files = [], []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                dirs.append(name)
            else:
                files.append(name)
        out.update({"ok": True, "dirs": sorted(dirs), "files": sorted(files)})
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _candidate_attempts(path):
    translated = translate_special(path)
    attempts = []
    attempts.append({"kind": "xbmcvfs", "input": path, "translated": translated, "result": listdir_xbmcvfs(path)})
    if translated != path:
        attempts.append({"kind": "xbmcvfs-translated", "input": translated, "translated": translated, "result": listdir_xbmcvfs(translated)})
    attempts.append({"kind": "os", "input": translated, "translated": translated, "result": listdir_os(translated)})
    return attempts


def probe_dir(label, candidate_paths, expected_ids=None):
    expected_ids = expected_ids or []
    attempts = []
    selected_path = ""
    selected_dirs = []
    best_ok = None
    for path in candidate_paths:
        for attempt in _candidate_attempts(path):
            attempt["label"] = label
            attempts.append(attempt)
            result = attempt["result"]
            if result.get("ok") and best_ok is None:
                best_ok = attempt
            if result.get("ok") and expected_ids and any(e in result.get("dirs", []) for e in expected_ids):
                selected_path = attempt["input"]
                selected_dirs = result.get("dirs", [])
                return {"selected_path": selected_path, "selected_dirs": selected_dirs, "attempts": attempts}
    if best_ok:
        selected_path = best_ok["input"]
        selected_dirs = best_ok["result"].get("dirs", [])
    return {"selected_path": selected_path, "selected_dirs": selected_dirs, "attempts": attempts}


def addon_data_candidates(seed=None):
    seed = seed or {}
    roots = seed.get("kodi_root_hint_android_candidates") or ANDROID_KODI_ROOTS
    return [
        "special://profile/addon_data/",
        "special://home/userdata/addon_data/",
        os.path.join(translate_special("special://profile/"), "addon_data"),
        os.path.join(translate_special("special://home/"), "userdata", "addon_data"),
    ] + [os.path.join(root, "userdata", "addon_data") for root in roots]


def addons_candidates(seed=None):
    seed = seed or {}
    roots = seed.get("kodi_root_hint_android_candidates") or ANDROID_KODI_ROOTS
    return [
        "special://home/addons/",
        "special://xbmc/addons/",
        os.path.join(translate_special("special://home/"), "addons"),
    ] + [os.path.join(root, "addons") for root in roots]


def probe_all(seed=None):
    seed = seed or {}
    expected = seed.get("expected_addon_data_ids") or EXPECTED_ADDON_DATA_IDS
    addon_data_probe = probe_dir("addon_data", addon_data_candidates(seed), expected)
    addons_probe = probe_dir("addons", addons_candidates(seed), expected)
    translated = {
        "special://home/": translate_special("special://home/"),
        "special://profile/": translate_special("special://profile/"),
        "special://profile/addon_data/": translate_special("special://profile/addon_data/"),
        "special://home/addons/": translate_special("special://home/addons/"),
    }
    seen = set(addon_data_probe.get("selected_dirs", [])) | set(addons_probe.get("selected_dirs", []))
    return {
        "translated": translated,
        "addon_data_probe": addon_data_probe,
        "addons_probe": addons_probe,
        "expected_seen": {aid: aid in seen for aid in expected},
    }
