import os
import threading
import time
import xml.etree.ElementTree as ET

try:
    from .kodi_api import translate, safe_listdir, exists, read_text
    from .path_probe import probe_all
    from .adapters import adapter_for
    from .addon_catalog import annotate_addons, plain_text
except ImportError:
    from kodi_api import translate, safe_listdir, exists, read_text
    from path_probe import probe_all
    from adapters import adapter_for
    from addon_catalog import annotate_addons, plain_text

class IndexRefreshCancelled(RuntimeError):
    deferred = True


def check_cancelled(should_stop):
    if should_stop is not None and should_stop():
        raise IndexRefreshCancelled("Add-on index refresh cancelled")


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
        metadata = root.find("extension[@point='xbmc.addon.metadata']")
        def localized(tag):
            nodes = metadata.findall(tag) if metadata is not None else []
            preferred = next((node for node in nodes if (node.get("lang") or "en").lower().startswith("en")), None)
            node = preferred if preferred is not None else (nodes[0] if nodes else None)
            return plain_text(node.text if node is not None else "")
        extensions = [e.get("point", "") for e in root.findall("extension")
                      if e.get("point") != "xbmc.addon.metadata"]
        return {"addon_id": root.get("id", ""), "name": plain_text(root.get("name", "")),
                "version": root.get("version", ""), "addon_xml_present": True, "metadata_available": True,
                "summary": localized("summary"), "description": localized("description"),
                "extensions": extensions, "type": extensions[0] if extensions else "",
                "dependencies": [{"addonid": node.get("addon", ""), "minversion": node.get("version", ""),
                                  "optional": node.get("optional", "false").lower() == "true"}
                                 for node in root.findall("requires/import")]}
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
    info["addon_data_path"] = translate(addon.get("addon_data_path_override") or "") or (addon_data_path(aid) if aid else "")
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
    """Merged view of installed add-ons and addon_data folders.

    ``refresh`` builds a new dict and swaps it in under a lock, so readers
    never see a half-built index, and full rescans run at most once every
    REFRESH_INTERVAL seconds unless ``force=True``.
    """
    REFRESH_INTERVAL = 5.0

    def __init__(self, kodi, clock=time.monotonic):
        self.kodi = kodi
        self.addons = {}
        self.probe = {}
        self._clock = clock
        self._lock = threading.RLock()
        self._refreshed_at = None
        self.refresh(force=True)

    def refresh(self, force=False, should_stop=None):
        with self._lock:
            now = self._clock()
            if not force and self._refreshed_at is not None and now - self._refreshed_at < self.REFRESH_INTERVAL:
                return self.addons
            check_cancelled(should_stop)
            addons, probe = self._build(should_stop) if should_stop is not None else self._build()
            check_cancelled(should_stop)
            self.addons, self.probe = addons, probe
            self._refreshed_at = self._clock()
            return addons

    def _build(self, should_stop=None):
        addons = {}
        check_cancelled(should_stop)
        for addon in self.kodi.list_addons():
            check_cancelled(should_stop)
            aid = addon.get("addon_id")
            if aid:
                addon["jsonrpc_present"] = True
                addons[aid] = enrich_addon(addon, self.kodi, addons)
        seed = getattr(self.kodi, "installer_seed", {}) if self.kodi else {}
        check_cancelled(should_stop)
        probe = probe_all(seed)
        root = probe.get("addons_probe", {}).get("selected_path") or addons_root()
        for aid in safe_listdir(root)["dirs"]:
            check_cancelled(should_stop)
            folder = root + ("" if root.endswith(("/", "\\")) else "/") + aid
            meta = addon_xml_meta(folder)
            aid = meta.get("addon_id") or aid
            base = addons.get(aid, {"addon_id": aid})
            base.update(meta)
            base["path"] = base.get("path") or folder
            base["home_addons_present"] = True
            base["home_addon_path"] = folder
            addons[aid] = enrich_addon(base, self.kodi, addons)
        root = builtin_root()
        for aid in safe_listdir(root)["dirs"]:
            check_cancelled(should_stop)
            folder = root + aid
            meta = addon_xml_meta(folder)
            aid = meta.get("addon_id") or aid
            base = addons.get(aid, {"addon_id": aid})
            # A user-installed update takes precedence over Kodi's bundled copy.
            if not base.get("home_addons_present"):
                base.update(meta)
            base["path"] = base.get("path") or folder
            base["builtin_addons_present"] = True
            base["builtin_addon_path"] = folder
            addons[aid] = enrich_addon(base, self.kodi, addons)
        # Settings, backups and restores always use the active profile's addon_data, as
        # Kodi does. The probe (which may fall back to the master profile) is diagnostics
        # only. Paths are translated: file operations cannot open special:// URLs.
        data_root = "special://profile/addon_data/"
        live_root = translate(data_root)
        for aid in safe_listdir(data_root)["dirs"]:
            check_cancelled(should_stop)
            base = addons.get(aid, {"addon_id": aid, "name": aid, "enabled": None, "type": ""})
            base["addon_data_present"] = True
            base["addon_data_path_override"] = os.path.join(live_root, aid)
            addons[aid] = enrich_addon(base, self.kodi, addons)
        check_cancelled(should_stop)
        try:
            active_skin = self.kodi.get_active_skin().get("addon_id", "")
        except Exception:
            active_skin = ""
        return annotate_addons(addons, active_skin), probe

    def get(self, addon_id):
        addons = self.addons
        if addon_id not in addons:
            details = self.kodi.get_addon_details(addon_id)
            if details:
                details["jsonrpc_present"] = True
                with self._lock:
                    snapshot = {aid: dict(addon) for aid, addon in self.addons.items()}
                    snapshot[addon_id] = enrich_addon(details, self.kodi, snapshot)
                    active_skin = next((aid for aid, addon in snapshot.items() if addon.get("active_skin")), "")
                    self.addons = annotate_addons(snapshot, active_skin)
                    addons = self.addons
        return addons.get(addon_id)

    def list(self):
        return list(self.addons.values())
