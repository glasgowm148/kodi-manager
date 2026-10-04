import os
import xml.etree.ElementTree as ET

try:
    from .kodi_api import translate, safe_listdir, exists, read_text
    from .path_probe import probe_all
    from .adapters import adapter_for
except ImportError:
    from kodi_api import translate, safe_listdir, exists, read_text
    from path_probe import probe_all
    from adapters import adapter_for

STACK_IDS = {
    "plugin.video.themoviedb.helper", "plugin.video.tmdb.bingie.helper",
    "plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "script.module.cocoscrapers",
    "script.trakt", "skin.titan.bingie.mod", "skin.titan.bingie", "skin.bingie",
    "script.skinshortcuts", "plugin.program.shortcutmanager", "shortcutmanager", "plugin.program.openwizard",
}


def addon_data_path(addon_id):
    return translate("special://profile/addon_data/%s" % addon_id)


def addons_root():
    return "special://home/addons/"


def builtin_root():
    return "special://xbmc/addons/"


def addon_xml_meta(folder):
    xml_path = os.path.join(folder, "addon.xml")
    if not exists(xml_path):
        return {}
    try:
        root = ET.fromstring(read_text(xml_path))
        return {"addon_id": root.get("id", ""), "name": root.get("name", ""), "version": root.get("version", ""), "addon_xml_present": True}
    except Exception:
        return {"addon_xml_present": True}


def enrich_addon(addon, kodi=None, index=None):
    aid = addon.get("addon_id") or addon.get("addonid") or addon.get("id")
    path = addon.get("path") or ""
    schema = os.path.join(path, "resources", "settings.xml") if path else ""
    user = os.path.join(addon_data_path(aid), "settings.xml") if aid else ""
    info = dict(addon)
    info["addon_id"] = aid
    info["path"] = path
    info["addon_data_path"] = addon.get("addon_data_path_override") or (addon_data_path(aid) if aid else "")
    info["settings_schema_path"] = schema
    info["user_settings_path"] = user
    info["has_settings_schema"] = bool(schema and exists(schema))
    info["has_user_settings"] = bool(user and exists(user))
    info["jsonrpc_present"] = bool(addon.get("jsonrpc_present"))
    info["home_addons_present"] = bool(addon.get("home_addons_present"))
    info["builtin_addons_present"] = bool(addon.get("builtin_addons_present"))
    info["installed_folder_present"] = bool(addon.get("installed_folder_present") or info["home_addons_present"] or info["builtin_addons_present"] or (path and exists(path)))
    info["addon_data_present"] = bool(addon.get("addon_data_present") or (info["addon_data_path"] and exists(info["addon_data_path"])))
    info["addon_xml_present"] = bool(addon.get("addon_xml_present") or (path and exists(os.path.join(path, "addon.xml"))))
    info["config_present"] = bool(info["addon_data_present"])
    info["installed"] = True if info["installed_folder_present"] or info["jsonrpc_present"] else (None if info["addon_data_present"] else False)
    info["paths"] = {
        "addon_data": info["addon_data_path"],
        "home_addon": addon.get("home_addon_path", ""),
        "builtin_addon": addon.get("builtin_addon_path", ""),
    }
    sources = []
    if info["jsonrpc_present"]:
        sources.append("JSON-RPC")
    if info["installed_folder_present"]:
        sources.append("addons folder")
    if info["home_addons_present"]:
        sources.append("home_addons")
    if info["builtin_addons_present"]:
        sources.append("builtin_addons")
    if info["addon_data_present"]:
        sources.append("addon_data folder")
    info["sources"] = sources
    info["detected_from"] = sources
    if not info.get("name"):
        info["name"] = aid
    adapter = adapter_for(info, kodi, index)
    info["adapter_name"] = adapter.name
    info["safe_edit_supported"] = bool(adapter.safe_edit_supported)
    info["is_stack_addon"] = aid in STACK_IDS or adapter.name != "GenericAdapter"
    return info


class AddonIndex:
    def __init__(self, kodi):
        self.kodi = kodi
        self.addons = {}
        self.probe = {}
        self.refresh()

    def refresh(self):
        self.addons = {}
        for addon in self.kodi.list_addons():
            aid = addon.get("addon_id")
            if aid:
                addon["jsonrpc_present"] = True
                self.addons[aid] = enrich_addon(addon, self.kodi, self.addons)
        seed = getattr(self.kodi, "installer_seed", {}) if self.kodi else {}
        self.probe = probe_all(seed)
        root = self.probe.get("addons_probe", {}).get("selected_path") or addons_root()
        for aid in safe_listdir(root)["dirs"]:
                folder = root + ("" if root.endswith(("/", "\\")) else "/") + aid
                meta = addon_xml_meta(folder)
                aid = meta.get("addon_id") or aid
                base = self.addons.get(aid, {"addon_id": aid})
                base.update({k: v for k, v in meta.items() if v})
                base["path"] = base.get("path") or folder
                base["home_addons_present"] = True
                base["home_addon_path"] = folder
                self.addons[aid] = enrich_addon(base, self.kodi, self.addons)
        root = builtin_root()
        for aid in safe_listdir(root)["dirs"]:
                folder = root + aid
                meta = addon_xml_meta(folder)
                aid = meta.get("addon_id") or aid
                base = self.addons.get(aid, {"addon_id": aid})
                base.update({k: v for k, v in meta.items() if v})
                base["path"] = base.get("path") or folder
                base["builtin_addons_present"] = True
                base["builtin_addon_path"] = folder
                self.addons[aid] = enrich_addon(base, self.kodi, self.addons)
        data_root = self.probe.get("addon_data_probe", {}).get("selected_path") or "special://profile/addon_data/"
        for aid in safe_listdir(data_root)["dirs"]:
                base = self.addons.get(aid, {"addon_id": aid, "name": aid, "enabled": None, "type": ""})
                base["addon_data_present"] = True
                base["addon_data_path_override"] = data_root + ("" if data_root.endswith(("/", "\\")) else "/") + aid
                self.addons[aid] = enrich_addon(base, self.kodi, self.addons)
        return self.addons

    def get(self, addon_id):
        if addon_id not in self.addons:
            details = self.kodi.get_addon_details(addon_id)
            if details:
                details["jsonrpc_present"] = True
                self.addons[addon_id] = enrich_addon(details, self.kodi, self.addons)
        return self.addons.get(addon_id)

    def list(self):
        return list(self.addons.values())
