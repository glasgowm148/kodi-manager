"""Read-only explanations of add-ons; dependency absence never proves safe removal."""
import re


PURPOSES = {
    "xbmc.python": "Kodi's Python interface, required by Python players, scripts and services.",
    "xbmc.gui": "Kodi's skin and user-interface framework.",
    "xbmc.addon": "Kodi's base add-on framework.",
    "xbmc.core": "Kodi's core add-on interface.",
    "xbmc.json": "Kodi's JSON interface used by add-ons and remote clients.",
    "xbmc.metadata": "Kodi's metadata-scraper framework.",
    "xbmc.webinterface": "Kodi's web-interface framework.",
    "kodi.resource": "Kodi's framework for language, artwork and other resource packs.",
    "service.kodi.addonadmin": "Runs this dashboard, settings editor and configuration backups.",
    "plugin.video.fen": "Movie and TV player with source searching and account integrations.",
    "plugin.video.fenlight": "Movie and TV player with source searching and account integrations.",
    "plugin.video.pov": "Movie and TV player with its own source searching and account integrations.",
    "script.module.cocoscrapers": "External source-searching module selected by compatible players; includes a settings-monitor service.",
    "script.module.magneto": "Source-searching module used by compatible players; may be selected in player settings.",
    "plugin.video.themoviedb.helper": "Movie and TV browsing, widgets and routing to your selected playback add-on.",
    "plugin.video.tmdb.bingie.helper": "Movie and TV browsing, widgets and playback routing for Bingie.",
    "script.skinshortcuts": "Builds the skin's menus and widget shortcuts.",
    "script.bingie.helper": "Provides helper features used by the Bingie skin.",
    "script.bingie.toolbox": "Provides tools used by the Bingie skin.",
    "script.bingie.widgets": "Provides home-screen widgets used by the Bingie skin.",
    "script.trakt": "Synchronizes watch history with Trakt; players may also have their own Trakt integration.",
    "plugin.program.openwizard": "Maintenance, cleanup and build-management tools; can include background maintenance.",
    "script.xbmcbackup": "Backs up and restores Kodi files; may run scheduled backups.",
    "script.keymap": "Edits remote-control and keyboard button mappings.",
    "plugin.program.autocompletion": "Provides suggestions for the skin's on-screen keyboard.",
    "script.xbmc.unpausejumpback": "Rewinds briefly when you resume paused playback.",
    "plugin.switchback": "Switches between recently played media.",
    "script.splash.cycler": "Rotates Kodi startup splash images.",
    "plugin.close.kodi": "Force-closes Kodi when invoked by a shortcut or menu action.",
    "plugin.video.imdb.trailers": "Plays IMDb trailers; may be invoked by the skin's trailer buttons.",
    "plugin.video.catchuptvandmore": "Provides catch-up programmes and live TV from supported broadcasters.",
    "plugin.video.iplayerwww": "Provides BBC iPlayer television and radio.",
    "pvr.iptvsimple": "Loads IPTV playlists and programme guides for Kodi's Live TV.",
    "service.subtitles.a4ksubtitles": "Searches multiple subtitle providers during playback.",
    "service.xbmc.versioncheck": "Checks for newer Kodi versions and displays update notices.",
    "script.module.inputstreamhelper": "Checks playback components such as InputStream Adaptive and Widevine.",
}

ROLES = {
    "system": ("Kodi component", "Provides a component bundled with Kodi."),
    "skin": ("Skin", "Controls Kodi's appearance, menus and home screen."),
    "repository": ("Update repository", "Supplies add-on downloads and updates; removing it can stop future updates."),
    "library": ("Shared library", "Provides code for other add-ons, including integrations selected in settings."),
    "video": ("Video add-on", "Provides video browsing or playback features."),
    "service": ("Service", "Provides background features when enabled."),
    "resource": ("Resource pack", "Provides images, languages, fonts or other resources for Kodi and add-ons."),
    "other": ("Other add-on", "Provides optional Kodi features; check its description and integrations."),
}


def plain_text(value, limit=600):
    text = str(value or "").replace("[CR]", " ")
    text = re.sub(r"\[/?(?:B|I|COLOR(?:\s+[^\]]*)?)\]", "", text, flags=re.I)
    return " ".join(text.split())[:limit]


def role_for(addon):
    aid = addon.get("addon_id", "")
    kind = addon.get("type", "")
    extensions = addon.get("extensions", [])
    if addon.get("builtin_addons_present") or aid.startswith(("xbmc.", "kodi.binary.")) or aid == "kodi.resource":
        return "system"
    if aid.startswith("skin.") or kind == "xbmc.gui.skin":
        return "skin"
    if kind == "xbmc.addon.repository" or "xbmc.addon.repository" in extensions:
        return "repository"
    if aid.startswith("script.module.") or kind == "xbmc.python.module":
        return "library"
    if aid.startswith("resource.") or kind.startswith("kodi.resource."):
        return "resource"
    if aid.startswith("plugin.video."):
        return "video"
    if kind == "xbmc.service" or aid.startswith("service."):
        return "service"
    return "other"


def annotate_addons(addons, active_skin=""):
    """Annotate an index snapshot in place, after all manifests have been merged."""
    reverse = {}
    for aid, addon in addons.items():
        if addon.get("installed") is not True:
            continue
        for dep in addon.get("dependencies", []):
            target = dep.get("addonid") or dep.get("addon")
            if target and target != aid:
                reverse.setdefault(target, {})[aid] = {
                    "addon_id": aid, "name": plain_text(addon.get("name") or aid),
                    "enabled": addon.get("enabled"), "optional": dep.get("optional") in (True, "true"),
                }
    for aid, addon in addons.items():
        role = role_for(addon)
        addon["active_skin"] = aid == active_skin
        addon["role"], addon["role_label"] = role, ROLES[role][0]
        binary_purpose = "Kodi's compatibility interface for compiled add-ons. Leave it installed." if aid.startswith("kodi.binary.") else ""
        addon["purpose"] = PURPOSES.get(aid) or binary_purpose or plain_text(addon.get("summary")) or ROLES[role][1]
        addon["dependencies"] = [dict(dep, version=addons.get(dep.get("addonid") or dep.get("addon"), {}).get("version", dep.get("version", "")))
                                 for dep in addon.get("dependencies", [])]
        addon["has_service"] = ("xbmc.service" in addon.get("extensions", [])
                                or addon.get("type") == "xbmc.service") if addon.get("metadata_available") else None
        addon["required_by"] = sorted(reverse.get(aid, {}).values(), key=lambda a: a["addon_id"])
        if addon.get("installed") is not True:
            code, label, detail = "config_only", "Saved config", "Installation is unconfirmed. Saved settings are not a running add-on."
        elif role == "system":
            code, label, detail = "keep", "Keep Kodi component", "Bundled with Kodi or part of its core. Leave it installed."
        elif aid == "service.kodi.addonadmin":
            code, label, detail = "keep", "Keep dashboard", "Removing this add-on removes this dashboard and its services."
        elif aid == active_skin:
            code, label, detail = "keep", "Keep active skin", "This profile currently uses this skin. Change skins before considering removal."
        elif addon["required_by"]:
            code, label, detail = "dependency", "Check dependents", "Other installed add-ons declare this dependency. Disabled add-ons and optional dependencies are included."
        elif addon.get("enabled") is False:
            code, label, detail = "review_disabled", "Review disabled", "Disabled in this profile, with no declared dependents found. Check other profiles, widgets and player settings before uninstalling."
        else:
            code, label, detail = "check_usage", "Check usage", "No declared dependents found. This does not prove it is unused: check other profiles, skin actions, widgets and player settings."
        addon["cleanup"] = {"code": code, "label": label, "detail": detail}
    return addons
