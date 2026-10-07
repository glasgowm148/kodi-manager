import os
import sqlite3

try:
    from .settings_schema import parse_schema, parse_user_settings
    from .account_evidence import summarize_account, credential_present
    from .kodi_api import translate
except ImportError:
    from settings_schema import parse_schema, parse_user_settings
    from account_evidence import summarize_account, credential_present
    from kodi_api import translate

RELATED_SKIN = ["script.skinshortcuts", "shortcutmanager", "plugin.program.shortcutmanager", "script.module.metadatautils", "script.skin.helper.service", "script.skin.helper.widgets", "plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper", "plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "script.module.cocoscrapers", "script.trakt", "plugin.program.openwizard"]


def trakt_integration(addons):
    """Additive stack field: status/providers/evidence contain no credential values."""
    groups = []
    scanned = []
    for aid in ("plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper", "plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "script.trakt"):
        addon = addons.get(aid)
        if not addon:
            continue
        scanned.append(aid)
        vals = parse_user_settings(addon.get("user_settings_path"))
        parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
        settings = {s["id"]: dict(s, configured=s["id"] in vals and credential_present(vals.get(s["id"])))
                    for g in parsed.get("groups", []) for s in g.get("settings", [])}
        settings.update({sid: {"id": sid, "value": value, "configured": credential_present(value), "source": "settings.xml"} for sid, value in vals.items()})
        data_path = addon.get("addon_data_path")
        db_path = translate(os.path.join(data_path, "databases", "settings.db")) if data_path and aid == "plugin.video.fenlight" else ""
        if db_path and os.path.isfile(db_path):
            try:
                con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
                try:
                    rows = con.execute("select setting_id, setting_value from settings").fetchall()
                finally:
                    con.close()
                settings.update({sid: {"id": sid, "configured": credential_present(value), "source": "settings.db"} for sid, value in rows})
            except (OSError, sqlite3.Error):
                pass
        groups.append({"component": aid, "label": addon.get("name") or aid, "settings": list(settings.values())})
    result = summarize_account(groups, "trakt")
    result["scanned_addons"] = scanned
    return result


def _summary(addon, adapter_name=""):
    if not addon:
        return {"found": False, "installed": False, "config_present": False, "enabled": None}
    installed = addon.get("installed")
    if installed is None:
        installed = None
    else:
        installed = bool(installed)
    config = bool(addon.get("config_present") or addon.get("addon_data_present") or addon.get("has_user_settings"))
    return {
        "found": bool(installed or config),
        "installed": installed,
        "config_present": config,
        "jsonrpc_present": bool(addon.get("jsonrpc_present")),
        "home_addons_present": bool(addon.get("home_addons_present")),
        "builtin_addons_present": bool(addon.get("builtin_addons_present")),
        "installed_folder_present": bool(addon.get("installed_folder_present")),
        "addon_data_present": bool(addon.get("addon_data_present")),
        "enabled": addon.get("enabled"),
        "version": addon.get("version", ""),
        "addon_id": addon.get("addon_id", ""),
        "name": addon.get("name", ""),
        "adapter": adapter_name or addon.get("adapter_name", ""),
        "has_settings_schema": bool(addon.get("has_settings_schema")),
        "has_user_settings": bool(addon.get("has_user_settings")),
        "sources": addon.get("sources") or addon.get("detected_from", []),
        "detected_from": addon.get("detected_from") or addon.get("sources", []),
        "paths": addon.get("paths", {}),
        "variant": addon.get("variant", ""),
    }


def find_first(addons, matcher, prefer=()):
    for aid in prefer:
        if aid in addons and matcher(addons[aid]):
            return addons[aid]
    for addon in addons.values():
        if matcher(addon):
            return addon
    return None


def text(addon):
    return ("%s %s %s" % (addon.get("addon_id", ""), addon.get("name", ""), addon.get("path", ""))).lower()


def is_tmdb(addon):
    aid = (addon.get("addon_id") or "").lower()
    t = text(addon)
    return aid in ("plugin.video.themoviedb.helper", "plugin.video.tmdb.bingie.helper") or (aid.startswith("plugin.video.") and (("tmdb" in t and "helper" in t) or "themoviedb" in t))


def is_fenlight(addon):
    return (addon.get("addon_id") or "").lower() == "plugin.video.fenlight"


def is_fen(addon):
    return (addon.get("addon_id") or "").lower() == "plugin.video.fen"


def is_pov(addon):
    return (addon.get("addon_id") or "").lower() == "plugin.video.pov"


def is_coco(addon):
    aid = (addon.get("addon_id") or "").lower()
    return aid == "script.module.cocoscrapers" or (aid.startswith("script.module.") and "cocoscrapers" in aid)


def is_trakt(addon):
    return "trakt" in (addon.get("addon_id") or "").lower()


def detect_stack(kodi, index):
    addons = index.addons
    active = kodi.get_active_skin()
    skin = index.get(active.get("addon_id")) if active.get("addon_id") else None
    skin_text = "%s %s %s" % (active.get("addon_id", ""), active.get("name", ""), active.get("path", ""))
    skin_like = "bingie" in skin_text.lower()
    out = {"skin": _summary(skin or active, "BingieSkinAdapter" if skin_like else "GenericAdapter")}
    out["skin"]["bingie_like"] = skin_like
    out["skin"]["active"] = bool(active.get("addon_id"))
    if out["skin"]["active"]:
        out["skin"]["found"] = True
        out["skin"]["installed"] = True
        out["skin"]["enabled"] = True
    out["skin"]["role"] = "skin"
    out["tmdbhelper"] = _summary(find_first(addons, is_tmdb, ("plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper")))
    out["tmdbhelper"]["role"] = "tmdbhelper"
    if out["tmdbhelper"].get("addon_id") == "plugin.video.tmdb.bingie.helper":
        out["tmdbhelper"]["variant"] = "bingie"
        out["tmdbhelper"]["detected_as"] = "Bingie TMDb Helper"
    out["fenlight"] = _summary(find_first(addons, is_fenlight, ("plugin.video.fenlight",)))
    out["fenlight"]["role"] = "fenlight"
    out["fen"] = _summary(find_first(addons, is_fen, ("plugin.video.fen",)))
    out["fen"]["role"] = "fen"
    out["pov"] = _summary(find_first(addons, is_pov, ("plugin.video.pov",)))
    out["pov"]["role"] = "pov"
    out["cocoscrapers"] = _summary(find_first(addons, is_coco, ("script.module.cocoscrapers",)))
    out["cocoscrapers"]["role"] = "cocoscrapers"
    trakt = addons.get("script.trakt")
    out["trakt"] = _summary(trakt)
    out["trakt"]["role"] = "trakt_standalone"
    out["trakt"]["standalone_found"] = bool(trakt)
    out["trakt"]["message"] = "Trakt standalone add-on found." if trakt else "Trakt standalone add-on not found. Trakt may be configured inside TMDb Helper, Fen/Fen Light, POV, or the Bingie helper add-on."
    out["trakt_integration"] = trakt_integration(addons)
    out["related_skin_addons"] = {aid: _summary(addons.get(aid)) for aid in RELATED_SKIN}
    for aid in ("script.skinshortcuts", "shortcutmanager", "plugin.program.shortcutmanager"):
        if aid in out["related_skin_addons"]:
            out["related_skin_addons"][aid]["role"] = "skin_dependency"
    if "plugin.program.openwizard" in out["related_skin_addons"]:
        out["related_skin_addons"]["plugin.program.openwizard"]["role"] = "maintenance"
    out["bingie_build"] = {
        "active_skin": out["skin"],
        "script_skinshortcuts": _summary(addons.get("script.skinshortcuts")),
        "shortcutmanager": _summary(addons.get("plugin.program.shortcutmanager") or addons.get("shortcutmanager")),
        "openwizard": _summary(addons.get("plugin.program.openwizard")),
        "tmdb_bingie_helper": _summary(addons.get("plugin.video.tmdb.bingie.helper")),
        "fenlight": out["fenlight"],
        "fen": out["fen"],
        "pov": out["pov"],
        "cocoscrapers": out["cocoscrapers"],
        "trakt": out["trakt"],
    }
    warnings = []
    if not skin_like:
        warnings.append("Active skin is not detected as Bingie-like.")
    for key in ("tmdbhelper",):
        if not out[key].get("found"):
            warnings.append("%s missing from JSON-RPC, addons folder, and addon_data folder." % key)
    if not any(out[key].get("found") for key in ("fenlight", "fen", "pov")):
        warnings.append("Playback add-on not detected.")
    expected = (getattr(index, "probe", {}) or {}).get("expected_seen", {})
    if expected and not all(expected.values()):
        missing = [k for k, v in expected.items() if not v]
        warnings.append("Kodi service cannot see expected addon_data folders: %s. Run Diagnostics > Path Diagnostics." % ", ".join(missing))
    out["warnings"] = warnings
    out["raw_detection"] = addons
    return out
