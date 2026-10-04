import json
import os
import zipfile

try:
    from .path_probe import translate_special, listdir_xbmcvfs, listdir_os, probe_all
except ImportError:
    from path_probe import translate_special, listdir_xbmcvfs, listdir_os, probe_all

try:
    import xbmc
    import xbmcaddon
    import xbmcgui
    import xbmcvfs
except ImportError:
    xbmc = xbmcaddon = xbmcgui = xbmcvfs = None


def translate(path):
    return translate_special(path)


def _dir_path(path):
    return path if path.endswith(("/", "\\")) else path + "/"


def exists(path):
    if xbmcvfs:
        try:
            return bool(xbmcvfs.exists(path) or xbmcvfs.exists(translate(path)))
        except Exception:
            pass
    return os.path.exists(translate(path))


def safe_listdir(path):
    first = listdir_xbmcvfs(path)
    if first.get("ok"):
        return first
    second = listdir_xbmcvfs(translate(path))
    if second.get("ok"):
        return second
    return listdir_os(translate(path))


def read_text(path):
    if xbmcvfs:
        try:
            fh = xbmcvfs.File(path)
            data = fh.read()
            fh.close()
            if isinstance(data, bytes):
                return data.decode("utf-8", "replace")
            return data
        except Exception:
            pass
    with open(translate(path), "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def debug_paths(seed=None):
    return probe_all(seed or {})


class KodiAPI:
    def __init__(self, installer_seed=None):
        self.installer_seed = installer_seed or {}

    def jsonrpc(self, method, params=None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        if not xbmc:
            return {"error": {"message": "Kodi APIs unavailable"}}
        try:
            return json.loads(xbmc.executeJSONRPC(json.dumps(payload)))
        except Exception as exc:
            return {"error": {"message": str(exc)}}

    def get_kodi_version(self):
        res = self.jsonrpc("Application.GetProperties", {"properties": ["version", "name"]})
        ver = res.get("result", {}).get("version", {})
        if isinstance(ver, dict):
            return "%s.%s" % (ver.get("major", ""), ver.get("minor", ""))
        return str(ver or "")

    def get_application_properties(self):
        return self.jsonrpc("Application.GetProperties", {"properties": ["version", "name"]}).get("result", {})

    def list_addons(self):
        props = ["name", "version", "enabled", "path", "dependencies"]
        res = self.jsonrpc("Addons.GetAddons", {"properties": props, "enabled": "all"})
        addons = res.get("result", {}).get("addons", [])
        out = []
        for item in addons:
            item["addon_id"] = item.get("addonid") or item.get("addon_id")
            if item.get("path"):
                item["path"] = translate(item["path"])
            out.append(item)
        return out

    def get_addon_details(self, addon_id):
        props = ["name", "version", "enabled", "path", "dependencies"]
        res = self.jsonrpc("Addons.GetAddonDetails", {"addonid": addon_id, "properties": props})
        item = res.get("result", {}).get("addon", {})
        if not item:
            return {}
        item["addon_id"] = item.get("addonid") or addon_id
        if item.get("path"):
            item["path"] = translate(item["path"])
        return item

    def get_active_skin(self):
        res = self.jsonrpc("Settings.GetSettingValue", {"setting": "lookandfeel.skin"})
        skin_id = res.get("result", {}).get("value", "")
        info = self.get_addon_details(skin_id) if skin_id else {}
        return {"addon_id": skin_id, "name": info.get("name", ""), "version": info.get("version", ""), "path": info.get("path", "")}

    def open_addon_settings(self, addon_id):
        if xbmcaddon:
            xbmcaddon.Addon(addon_id).openSettings()
            return True
        return False

    def set_addon_setting(self, addon_id, setting_id, value):
        if xbmcaddon:
            xbmcaddon.Addon(addon_id).setSetting(setting_id, value)
            return True
        raise RuntimeError("Kodi xbmcaddon unavailable")

    def execute_addon(self, addon_id, params=None):
        return self.jsonrpc("Addons.ExecuteAddon", {"addonid": addon_id, "params": params or {}})

    def open_skin_settings(self):
        if xbmc:
            xbmc.executebuiltin("ActivateWindow(skinsettings)")
            return True
        return False

    def get_log_lines(self, n=300):
        candidates = [
            "special://logpath/kodi.log",
            os.path.join(translate("special://logpath/"), "kodi.log"),
            os.path.join(translate("special://profile/"), "kodi.log"),
        ]
        for path in candidates:
            try:
                text = read_text(path)
                return text.splitlines()[-int(n):]
            except Exception:
                continue
        return []

    def install_local_addon(self, source_path):
        if not source_path:
            raise ValueError("source_path required")
        lower = source_path.lower()
        if "://" in source_path and not source_path.startswith("special://"):
            raise ValueError("Only local Kodi paths are allowed")
        if lower.endswith(".zip"):
            if xbmc:
                xbmc.executebuiltin("InstallAddon(%s)" % source_path)
                return {"started": True, "method": "InstallAddon", "source_path": source_path}
            return {"started": False, "error": "xbmc unavailable"}
        raise ValueError("Only local .zip add-on install is supported from service UI")

    def notify(self, title, message):
        if xbmcgui:
            xbmcgui.Dialog().notification(title, message)

    def log(self, message, level="info"):
        if xbmc:
            lvl = xbmc.LOGDEBUG if level == "debug" else xbmc.LOGINFO
            xbmc.log("[Kodi Manager] %s" % message, lvl)


def service_addon():
    return xbmcaddon.Addon("service.kodi.addonadmin") if xbmcaddon else None
