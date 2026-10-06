import json
import os
import shutil
import sqlite3
import xml.etree.ElementTree as ET

try:
    from .settings_schema import parse_schema, flatten_settings, parse_user_settings
    from .stack_detector import detect_stack
    from .validation import is_secret_like, mask_value, setting_editable, coerce_value, redact
    from .kodi_api import read_text, translate
    from .account_evidence import credential_present, summarize_account, account_provider, is_auth_field
    from .backup import allocate_backup
except ImportError:
    from settings_schema import parse_schema, flatten_settings, parse_user_settings
    from stack_detector import detect_stack
    from validation import is_secret_like, mask_value, setting_editable, coerce_value, redact
    from kodi_api import read_text, translate
    from account_evidence import credential_present, summarize_account, account_provider, is_auth_field
    from backup import allocate_backup

PLAYER_IDS = ["plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "plugin.video.umbrella", "plugin.video.seren"]
HELPER_IDS = ["plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper"]
PIPELINE_IDS = ["skin.bingie", "plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper", "plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "script.module.cocoscrapers", "script.trakt", "script.skinshortcuts", "shortcutmanager", "plugin.program.shortcutmanager"]
PIPELINE_SETTING_KEYWORDS = ("player", "default", "autoplay", "fallback", "external", "cocoscraper", "scraper.module", "provider.module", "resolver")
ACCOUNT_PROVIDERS = ("trakt", "torbox", "tmdb", "realdebrid", "real-debrid", "alldebrid", "all-debrid", "premiumize", "easynews", "debrid", "rd.", "ad.", "pm.", "tb.", "ed.", "oc.", "omdb", "fanart", "tvdb", "mdblist", "prowlarr", "furk")
ACCOUNT_CREDENTIAL_WORDS = ("token", "api", "key", "oauth", "refresh", "secret", "auth", "client", "username", "user", "login", "email", "password", "account", "enabled")
ACCOUNT_EXCLUDE_WORDS = ("watched", "indicator", "indicators", "calendar", "sync_interval", "refresh_widgets", "widget", "widgets", "rating", "ratings", "scrobble", "manager", "list", "lists", "sort", "flatten", "next_daily_clear", "cloud", "provider.", "store_resolved", "title_filter", "priority", "highlight")
TEXT_EXTS = (".xml", ".json", ".txt", ".properties", ".ini", ".strm")
DB_EDITABLE_TYPES = {"boolean", "bool", "string", "text", "path", "name", "action", "integer", "int", "number"}


def is_unset_value(value):
    if value is None:
        return True
    text = str(value).strip().lower()
    return text in ("", "none", "null", "undefined", "empty_setting", "not set", "n/a")


def is_account_setting(setting_id="", label="", value=""):
    text = ("%s %s" % (setting_id or "", label or "")).lower()
    if any(word in text for word in ACCOUNT_EXCLUDE_WORDS):
        return False
    provider_hit = any(word in text for word in ACCOUNT_PROVIDERS)
    credential_hit = any(word in text for word in ACCOUNT_CREDENTIAL_WORDS)
    return provider_hit and credential_hit


def pretty_label(setting_id):
    text = (setting_id or "").replace("_", " ").replace(".", " ").replace("-", " ")
    words = [w for w in text.split() if w not in ("plugin", "video", "fenlight")]
    aliases = {
        "default addon fanart": "Addon Fanart",
        "auto start fenlight": "Auto-start Fen Light",
        "limit concurrent threads": "Limit Threads",
        "max threads": "Max Threads",
        "trakt refresh widgets": "Refresh Widgets After Trakt",
        "store resolved to cloud torbox": "Save Resolved Links to TorBox",
        "store resolved to cloud torbox name": "TorBox Cloud Save Label",
        "extras enable extra ratings": "Extra Ratings",
        "provider debrid cloud highlight": "Debrid Cloud Highlight",
        "rd account id": "Real-Debrid Account",
        "rd alt api": "Real-Debrid Alt API",
        "rd client id": "Real-Debrid Client ID",
        "rd enabled": "Real-Debrid Enabled",
        "rd refresh": "Real-Debrid Refresh Token",
        "rd secret": "Real-Debrid Secret",
        "rd token": "Real-Debrid Token",
        "tb enabled": "TorBox Enabled",
        "tb token": "TorBox Token",
        "ad account id": "AllDebrid Account",
        "ad enabled": "AllDebrid Enabled",
        "ad token": "AllDebrid Token",
        "pm account id": "Premiumize Account",
        "pm enabled": "Premiumize Enabled",
        "pm token": "Premiumize Token",
        "ed token": "EasyDebrid Token",
        "oc token": "OffCloud Token",
        "omdb api": "OMDb API Key",
        "omdb apikey": "OMDb API Key",
        "fanart client key": "Fanart.tv API Key",
        "fanarttv clientkey": "Fanart.tv API Key",
        "tvdb token": "TVDb Token",
        "mdblist apikey": "MDBList API Key",
        "prowlarr token": "Prowlarr Token",
        "furk api key": "Furk API Key",
    }
    base = " ".join(words).strip().lower()
    if base in aliases:
        return aliases[base]
    return " ".join(w.upper() if w in ("tmdb", "api") else w.capitalize() for w in words) or setting_id


def setting_description(setting_id="", label=""):
    sid = (setting_id or "").lower()
    provider = ""
    if sid.startswith("rd."):
        provider = "Real-Debrid"
    elif sid.startswith("ad."):
        provider = "AllDebrid"
    elif sid.startswith("pm."):
        provider = "Premiumize"
    elif sid.startswith("tb."):
        provider = "TorBox"
    elif sid.startswith("ed."):
        provider = "EasyDebrid"
    elif sid.startswith("oc."):
        provider = "OffCloud"
    if provider:
        if sid.endswith(".enabled"):
            return "Turn %s account integration on or off." % provider
        if sid.endswith(".priority"):
            return "Order used when choosing %s results. Lower number usually means higher priority." % provider
        if sid.endswith(".token"):
            return "%s access token used by the add-on." % provider
        if sid.endswith(".refresh"):
            return "%s refresh token used to renew access." % provider
        if sid.endswith(".secret"):
            return "%s client secret used for authorization." % provider
        if sid.endswith(".client_id"):
            return "%s client ID used for authorization." % provider
        if sid.endswith(".account_id"):
            return "%s account name or account ID currently linked." % provider
        if sid.endswith(".alt_api"):
            return "Alternative %s API key/token." % provider
    rules = [
        ("tmdb", "TMDb API/account credential used for metadata and lists."),
        ("trakt", "Trakt account credential or authorization setting."),
        ("easynews_user", "EasyNews username."),
        ("easynews_password", "EasyNews password."),
        ("omdb", "OMDb API key used for ratings/metadata."),
        ("fanart", "Fanart.tv API key used for artwork."),
        ("tvdb", "TVDb token used for TV metadata."),
        ("mdblist", "MDBList API key used for list metadata."),
        ("prowlarr", "Prowlarr token used by scraper integration."),
        ("furk", "Furk account/API credential."),
        ("default_addon_fanart", "Artwork shown when Fen Light has no specific background."),
        ("autoplay", "Controls automatic playback behavior."),
        ("external", "Connects this add-on to an external helper/module."),
        ("scraper", "Controls scraper/provider integration."),
        ("provider", "Controls provider behavior or appearance."),
        ("timeout", "How long to wait before giving up."),
        ("thread", "Concurrency/performance setting."),
        ("quality", "Playback/source quality preference."),
        ("cache", "Cache behavior."),
        ("resume", "Resume playback behavior."),
    ]
    for key, desc in rules:
        if key in sid:
            return desc
    return "Kodi add-on setting. Change only if you know this behavior."


def _summary(addon):
    if not addon:
        return {"found": False, "addon_id": "", "status": "missing"}
    return {
        "found": bool(addon.get("installed") or addon.get("config_present") or addon.get("addon_data_present")),
        "addon_id": addon.get("addon_id", ""),
        "name": addon.get("name") or addon.get("addon_id", ""),
        "version": addon.get("version", ""),
        "installed": addon.get("installed"),
        "enabled": addon.get("enabled"),
        "config_present": bool(addon.get("config_present") or addon.get("addon_data_present")),
        "status": "active" if addon.get("active") else ("config present" if addon.get("config_present") else ("installed" if addon.get("installed") else "unknown")),
        "detected_from": addon.get("detected_from") or addon.get("sources") or [],
        "paths": addon.get("paths", {}),
    }


def _setting_obj(component, setting, source="settings.xml", account=False):
    sid = setting.get("id", "")
    label = setting.get("label") or sid
    masked = False
    editable = bool(setting.get("editable"))
    replacement_allowed = bool(account and source == "settings.xml")
    risk = "safe" if editable else "unsupported"
    obj = {
        "component": component,
        "id": sid,
        "label": pretty_label(sid) if label == sid or label.startswith("Label ") else label,
        "description": setting_description(sid, label),
        "type": setting.get("type", "unknown"),
        "value": setting.get("value", ""),
        "masked": masked,
        "editable": editable,
        "replacement_allowed": replacement_allowed,
        "reason": setting.get("warning") or ("" if editable else "read-only or unsupported"),
        "options": setting.get("options") or [],
        "source": source,
        "risk": risk,
    }
    for key in ("default", "default_known", "value_source", "is_default", "secret"):
        if key in setting:
            obj[key] = setting[key]
    return obj


def _parse_component_settings(addon):
    groups = []
    if not addon:
        return groups
    parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
    vals = parse_user_settings(addon.get("user_settings_path"))
    settings = []
    for group in parsed.get("groups", []):
        for setting in group.get("settings", []):
            text = ("%s %s" % (setting.get("id", ""), setting.get("label", ""))).lower()
            if any(k in text for k in PIPELINE_SETTING_KEYWORDS):
                settings.append(_setting_obj(addon["addon_id"], setting, "settings.xml"))
    if vals and not settings:
        for sid, value in sorted(vals.items()):
            if any(k in sid.lower() for k in PIPELINE_SETTING_KEYWORDS):
                settings.append({"component": addon["addon_id"], "id": sid, "label": pretty_label(sid), "description": setting_description(sid, sid), "type": "text", "value": value, "masked": False, "editable": True, "reason": "raw setting", "options": [], "source": "raw", "risk": "safe"})
    if settings:
        groups.append({"component": addon["addon_id"], "label": addon.get("name") or addon["addon_id"], "settings": settings})
    return groups


def _fenlight_db_settings(addon, account=False):
    if not addon or addon.get("addon_id") != "plugin.video.fenlight":
        return []
    db_path = translate(os.path.join(addon.get("addon_data_path") or "", "databases", "settings.db"))
    if not os.path.exists(db_path):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        rows = con.execute("select setting_id, setting_type, setting_default, setting_value from settings order by setting_id").fetchall()
        con.close()
    except Exception:
        return []
    out = []
    for sid, stype, _default, value in rows:
        text = ("%s %s" % (sid, value)).lower()
        is_match = is_account_setting(sid, sid, value) if account else any(k in text for k in PIPELINE_SETTING_KEYWORDS)
        if is_match:
            editable = bool((stype or "").lower() in DB_EDITABLE_TYPES)
            out.append({"component": "plugin.video.fenlight", "id": sid, "label": pretty_label(sid), "description": setting_description(sid, sid), "type": stype or "unknown", "value": value, "configured": credential_present(value), "masked": False, "editable": editable, "replacement_allowed": editable, "reason": "" if editable else "unsupported", "options": [], "source": "settings.db", "risk": "safe" if editable else "native_ui_recommended"})
    return out


def _scan_refs(root, addon_ids, limit=120):
    refs = []
    if not root or not os.path.isdir(root):
        return refs
    for base, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(TEXT_EXTS):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read(200000)
            except Exception:
                continue
            low = text.lower()
            found = [aid for aid in addon_ids if aid.lower() in low]
            if found:
                refs.append({"path": path, "refs": found, "count": sum(low.count(aid.lower()) for aid in found)})
            if len(refs) >= limit:
                return refs
    return refs


def _player_files(helper):
    data = (helper or {}).get("addon_data_path")
    root = translate(os.path.join(data, "players")) if data else ""
    files = []
    refs = _scan_refs(root, PLAYER_IDS)
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if os.path.isfile(os.path.join(root, name)):
                files.append({"filename": name, "path": os.path.join(root, name)})
    return {"folder": root, "files": files, "refs": refs}


def _routing(helper, addons, player_files):
    """Only a selected definition proves routing; installed files are candidates."""
    vals = parse_user_settings((helper or {}).get("user_settings_path"))
    parsed = parse_schema((helper or {}).get("settings_schema_path"), (helper or {}).get("path"), (helper or {}).get("user_settings_path"), True)
    for group in parsed.get("groups", []):
        for setting in group.get("settings", []):
            vals.setdefault(setting["id"], setting.get("value", ""))
    routes = {}
    for role, keys in (
        ("movie_player", ("default_player_movies", "movie_player", "player_movies")),
        ("episode_player", ("default_player_episodes", "episode_player", "player_episodes")),
        ("fallback_player", ("fallback_player", "default_player_fallback")),
    ):
        sid = next((key for key in keys if not is_unset_value(vals.get(key))), "")
        selected = str(vals.get(sid, ""))
        refs = [aid for aid in PLAYER_IDS if aid in selected]
        evidence = []
        if sid:
            evidence.append({"component": (helper or {}).get("addon_id", ""), "setting_id": sid, "source": "settings.xml"})
        # Match the exact filename selected by the helper. Other player files do
        # not identify the active route, even when only one add-on is installed.
        selected_file = selected
        # Helper appends the playback action to the selected JSON filename.
        for action in ("play_movie", "play_episode", "play_episode_next"):
            suffix = " " + action
            if selected_file.endswith(suffix):
                selected_file = selected_file[:-len(suffix)]
                break
        for entry in player_files.get("files", []):
            if entry["filename"] != os.path.basename(selected_file):
                continue
            try:
                data = json.loads(read_text(entry["path"]))
                data_text = json.dumps(data)
                refs = [aid for aid in PLAYER_IDS if aid in data_text]
                evidence.append({"path": entry["path"], "source": "selected_player_file", "refs": refs})
            except (OSError, ValueError):
                pass
        aid = refs[0] if len(refs) == 1 else ""
        routes[role] = {"value": (addons.get(aid) or {}).get("name") or aid or selected or "unknown", "addon_id": aid,
                        "source": "selected_player_file" if any(e.get("path") for e in evidence) else ("helper_setting" if sid else "unknown"),
                        "setting_id": sid, "editable": False, "confidence": "high" if aid else "unknown", "evidence": evidence}
    return routes


def _primary_player(players, routing):
    selected = {routing[key]["addon_id"] for key in ("movie_player", "episode_player") if routing[key]["addon_id"]}
    if len(selected) == 1:
        aid = next(iter(selected))
        return next((player for player in players if player["addon_id"] == aid), None), "selected"
    if not selected:
        available = [p for p in players if p.get("installed") and p.get("enabled") is not False]
        if len(available) == 1:
            return available[0], "inferred"
    return None, "unknown"


def _scraper_relationship(primary, selection, addons):
    """Installation alone never proves a selected player's scraper dependency."""
    unknown = {"found": False, "addon_id": "", "name": "Unknown", "status": "unknown", "used": None, "relationship": "unknown", "confidence": "unknown", "evidence": []}
    if not primary:
        return unknown
    path = translate(primary.get("path") or "")
    manifest = os.path.join(path, "addon.xml") if path else ""
    imports = []
    try:
        imports = [elem.get("addon") for elem in ET.fromstring(read_text(manifest)).findall("./requires/import")]
    except (OSError, ValueError, ET.ParseError):
        pass
    dependency = next((aid for aid in imports if aid and ("scraper" in aid.lower() or "magneto" in aid.lower())), "")
    if dependency:
        result = _summary(addons.get(dependency))
        result.update(addon_id=dependency, used=True if selection == "selected" else None, relationship="declared dependency", confidence="high", evidence=[{"path": manifest, "dependency": dependency}])
        return result
    # Fen-family external modules are optional, selected through settings.
    vals = parse_user_settings(primary.get("user_settings_path"))
    for sid, value in vals.items():
        if not any(word in sid.lower() for word in ("scraper", "provider.module", "external_module")):
            continue
        for aid in addons:
            module_names = (aid, aid.replace("script.module.", "", 1))
            if aid.startswith("script.module.") and value in module_names and ("scraper" in aid or "magneto" in aid):
                result = _summary(addons[aid])
                result.update(used=True if selection == "selected" else None, relationship="configured module", confidence="high", evidence=[{"component": primary["addon_id"], "setting_id": sid, "source": "settings.xml"}])
                return result
    magneto = os.path.join(path, "resources", "lib", "magneto") if path else ""
    sources = os.path.join(path, "resources", "lib", "modules", "sources.py") if path else ""
    if primary.get("addon_id") == "plugin.video.pov" and magneto and os.path.isdir(magneto):
        try:
            imported = "from magneto import sources" in read_text(sources)
        except OSError:
            imported = False
        if imported:
            return {"found": True, "addon_id": "", "name": "POV bundled Magneto", "status": "bundled", "used": True if selection == "selected" else None,
                    "relationship": "bundled implementation", "confidence": "high", "evidence": [{"path": sources, "module": "magneto"}]}
    return unknown


def _account_status(settings_groups, key):
    return summarize_account(settings_groups, key)


def _parse_account_settings(addon):
    if not addon:
        return []
    parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
    vals = parse_user_settings(addon.get("user_settings_path"))
    out = []
    seen = set()
    for group in parsed.get("groups", []):
        for setting in group.get("settings", []):
            text = ("%s %s" % (setting.get("id", ""), setting.get("label", ""))).lower()
            if is_account_setting(setting.get("id", ""), setting.get("label", ""), setting.get("value")) or (account_provider(setting.get("id"), addon["addon_id"]) and is_auth_field(setting.get("id"))):
                seen.add(setting.get("id", ""))
                obj = _setting_obj(addon["addon_id"], setting, "settings.xml", True)
                obj["configured"] = setting.get("id") in vals and credential_present(vals.get(setting.get("id")))
                obj["placeholder"] = "configured" if obj["configured"] else "not set"
                out.append(obj)
    for sid, value in sorted(vals.items()):
        if sid in seen:
            continue
        if is_account_setting(sid, sid, value) or (account_provider(sid, addon["addon_id"]) and is_auth_field(sid)):
            configured = credential_present(value)
            out.append({"component": addon["addon_id"], "id": sid, "label": pretty_label(sid), "description": setting_description(sid, sid), "type": "text", "value": value, "placeholder": "configured" if configured else "not set", "configured": configured, "masked": False, "editable": True, "replacement_allowed": True, "reason": "raw account setting", "options": [], "source": "raw", "risk": "safe"})
    return out


def build_accounts(kodi, index):
    index.refresh()
    groups = []
    for aid in ["plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper", "plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "script.module.cocoscrapers", "script.trakt", "skin.bingie"]:
        addon = index.get(aid)
        settings = _parse_account_settings(addon)
        if aid == "plugin.video.fenlight":
            settings += _fenlight_db_settings(addon, True)
        if settings:
            groups.append({"component": aid, "label": (addon or {}).get("name", aid), "settings": settings})
    return {"groups": groups, "summary": {key: summarize_account(groups, key) for key in ("trakt", "torbox", "tmdb", "debrid")}, "notes": ["Local authenticated editor. Values are shown so you can repair accounts. Saving creates backup first.", "Configured means credentials are present locally; account access has not been verified."]}


def build_pipeline(kodi, index):
    index.refresh()
    stack = detect_stack(kodi, index)
    addons = index.addons
    skin = addons.get(stack["skin"].get("addon_id")) or stack.get("skin")
    if isinstance(skin, dict):
        skin = dict(skin)
        skin["active"] = bool(stack["skin"].get("active"))
    helper = addons.get(stack["tmdbhelper"].get("addon_id")) or next((addons.get(a) for a in HELPER_IDS if addons.get(a)), None)
    players = [addons[aid] for aid in PLAYER_IDS if aid in addons and (addons[aid].get("config_present") or addons[aid].get("installed"))]
    pf = _player_files(helper)
    routing = _routing(helper, addons, pf)
    primary, primary_selection = _primary_player(players, routing)
    scraper = _scraper_relationship(primary, primary_selection, addons)
    nodes = [
        {"id": "kodi", "label": "Kodi", "addon_id": "", "status": "running", "detected_from": ["JSON-RPC"]},
        {"id": "skin", "label": "Bingie Skin", **_summary(skin)},
        {"id": "helper", "label": "Catalog / Metadata / Launcher", **_summary(helper)},
        {"id": "player", "label": "Playback Add-on", **_summary(primary)},
        {"id": "scraper", "label": "Scraper / Provider Module", **scraper},
        {"id": "accounts", "label": "Account Integrations", "addon_id": "", "status": "local settings", "detected_from": ["settings scan"]},
        {"id": "kodi_player", "label": "Kodi Internal Player", "addon_id": "", "status": "available", "detected_from": ["Kodi"]},
    ]
    edges = [
        {"from": "kodi", "to": "skin", "label": "interface", "evidence": ["active skin"]},
        {"from": "skin", "to": "helper", "label": "widgets / metadata paths", "evidence": []},
        {"from": "helper", "to": "player", "label": "player routing", "evidence": []},
        {"from": "player", "to": "scraper", "label": "provider/scraper module", "evidence": []},
        {"from": "player", "to": "accounts", "label": "account integrations", "evidence": []},
        {"from": "player", "to": "kodi_player", "label": "resolved playback", "evidence": ["Kodi player"]},
    ]
    settings_groups = []
    for aid in ["plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper", "plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "script.module.cocoscrapers", "script.trakt", "skin.bingie"]:
        addon = addons.get(aid)
        settings_groups += _parse_component_settings(addon)
    fen_db = _fenlight_db_settings(addons.get("plugin.video.fenlight"))
    if fen_db:
        settings_groups.append({"component": "plugin.video.fenlight", "label": "Fen Light database settings", "settings": fen_db})
    scan_roots = [a.get("addon_data_path") for a in [skin, addons.get("script.skinshortcuts"), addons.get("plugin.program.shortcutmanager") or addons.get("shortcutmanager")] if a]
    widget_refs = []
    for root in scan_roots:
        widget_refs += _scan_refs(root, HELPER_IDS + PLAYER_IDS + ["script.module.cocoscrapers"])
    accounts = build_accounts(kodi, index)["summary"]
    warnings = []
    if not helper:
        warnings.append("Helper add-on not detected.")
    if not players:
        warnings.append("Playback add-on not detected.")
    elif primary_selection == "unknown":
        warnings.append("Primary playback route is unknown; installed add-ons do not prove player selection.")
    edges[1]["evidence"] = widget_refs[:10]
    edges[2]["evidence"] = routing["movie_player"]["evidence"] + routing["episode_player"]["evidence"]
    edges[3]["evidence"] = scraper["evidence"]
    edges[3]["relationship"] = scraper["relationship"]
    edges[3]["used"] = scraper["used"]
    edges[4]["evidence"] = accounts["trakt"]["refs"][:5] + accounts["torbox"]["refs"][:5]
    return {
        "summary": {
            "active_skin": _summary(skin),
            "helper": _summary(helper),
            "primary_player": dict(_summary(primary), selection=primary_selection, confidence="high" if primary_selection == "selected" else ("low" if primary else "unknown")),
            "secondary_players": [_summary(p) for p in players if not primary or p["addon_id"] != primary.get("addon_id")],
            "scraper_module": scraper,
            "available_scraper_modules": [_summary(addons[aid]) for aid in ("script.module.cocoscrapers", "script.module.magneto") if aid in addons],
            "accounts": accounts,
            "integrations": accounts,
            "health": {"status": "warning" if warnings else "ok", "warnings": warnings},
        },
        "nodes": nodes,
        "edges": edges,
        "routing": routing,
        "settings_groups": settings_groups,
        "discovery": {"widget_path_refs": widget_refs, "player_files": pf, "account_refs": accounts, "raw_detection": {"stack": stack, "players": [_summary(p) for p in players]}},
    }


def pipeline_backup(index, kodi_version="", pipeline_obj=None):
    ts, backup_id, dest = allocate_backup("pipeline")
    included, skipped = [], []
    for aid in PIPELINE_IDS:
        addon = index.get(aid)
        src = addon.get("addon_data_path") if addon else ""
        if src and os.path.isdir(src):
            shutil.copytree(src, os.path.join(dest, aid), dirs_exist_ok=True)
            included.append(aid)
        else:
            skipped.append(aid)
    summary = (pipeline_obj or {}).get("summary", {})
    manifest = {"backup_id": backup_id, "timestamp": ts, "included_components": included, "skipped_components": skipped, "Kodi version": kodi_version, "active_skin": summary.get("active_skin", {}), "detected_helper": summary.get("helper", {}), "detected_primary_player": summary.get("primary_player", {}), "account_status": redact(summary.get("accounts", {})), "warnings": summary.get("health", {}).get("warnings", [])}
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def apply_pipeline_settings(kodi, index, changes, write_enabled=False, kodi_version=""):
    if not write_enabled:
        raise PermissionError("Writes disabled in service settings")
    pipe = build_pipeline(kodi, index)
    backup = pipeline_backup(index, kodi_version, pipe)
    changed = []
    for ch in changes:
        aid = ch.get("component")
        sid = ch.get("setting_id")
        addon = index.get(aid)
        if not addon:
            raise ValueError("Component not detected: %s" % aid)
        if aid == "plugin.video.fenlight" and ch.get("source") == "settings.db":
            value = str(ch.get("value"))
            db_path = translate(os.path.join(addon.get("addon_data_path") or "", "databases", "settings.db"))
            if not os.path.exists(db_path):
                raise ValueError("Fen Light settings.db not found")
            con = sqlite3.connect(db_path)
            row = con.execute("select setting_type from settings where setting_id=?", (sid,)).fetchone()
            if not row:
                con.close()
                raise ValueError("Unknown Fen Light DB setting: %s" % sid)
            if (row[0] or "").lower() not in DB_EDITABLE_TYPES:
                con.close()
                raise ValueError("Unsupported Fen Light DB setting type: %s" % sid)
            con.execute("update settings set setting_value=? where setting_id=?", (value, sid))
            con.commit()
            con.close()
            changed.append({"component": aid, "setting_id": sid, "source": "settings.db", "value_present": bool(str(value))})
            continue
        if ch.get("source") == "raw":
            raw_vals = parse_user_settings(addon.get("user_settings_path"))
            if sid not in raw_vals:
                raise ValueError("Unknown raw setting: %s" % sid)
            value = str(ch.get("value"))
            kodi.set_addon_setting(aid, sid, value)
            changed.append({"component": aid, "setting_id": sid, "source": "raw", "value_present": bool(str(value))})
            continue
        parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
        settings = flatten_settings(parsed)
        setting = settings.get(sid)
        if not setting:
            raise ValueError("Unknown setting: %s" % sid)
        if not setting_editable(setting, True):
            raise ValueError("Unsupported setting rejected: %s" % sid)
        value = coerce_value(setting, ch.get("value"))
        kodi.set_addon_setting(aid, sid, value)
        changed.append({"component": aid, "setting_id": sid, "value_present": bool(str(value))})
    return {"backup_id": backup["backup_id"], "changed_count": len(changed), "changed_settings": changed, "warnings": [], "restart_recommended": True}


def apply_account_settings(kodi, index, changes, write_enabled=False, kodi_version=""):
    if not write_enabled:
        raise PermissionError("Writes disabled in service settings")
    pipe = build_pipeline(kodi, index)
    backup = pipeline_backup(index, kodi_version, pipe)
    changed = []
    for ch in changes:
        aid = ch.get("component")
        sid = ch.get("setting_id")
        value = ch.get("value")
        if value is None:
            value = ""
        addon = index.get(aid)
        if not addon:
            raise ValueError("Component not detected: %s" % aid)
        if ch.get("source") == "settings.db" and aid == "plugin.video.fenlight":
            db_path = translate(os.path.join(addon.get("addon_data_path") or "", "databases", "settings.db"))
            con = sqlite3.connect(db_path)
            row = con.execute("select setting_type from settings where setting_id=?", (sid,)).fetchone()
            if not row:
                con.close()
                raise ValueError("Unknown Fen Light DB setting: %s" % sid)
            con.execute("update settings set setting_value=? where setting_id=?", (str(value), sid))
            con.commit()
            con.close()
            changed.append({"component": aid, "setting_id": sid, "source": "settings.db", "value_present": bool(str(value))})
            continue
        if ch.get("source") == "raw":
            kodi.set_addon_setting(aid, sid, str(value))
            changed.append({"component": aid, "setting_id": sid, "source": "raw", "value_present": bool(str(value))})
            continue
        parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
        settings = flatten_settings(parsed)
        setting = settings.get(sid)
        if not setting:
            raise ValueError("Account setting not safely writable: %s" % sid)
        stype = (setting.get("type") or "").lower()
        if stype not in ("text", "string", "password", "bool", "boolean", "integer", "int", "number", "select", "spinner", "enum"):
            raise ValueError("Only text secret replacement is supported: %s" % sid)
        kodi.set_addon_setting(aid, sid, coerce_value(setting, value))
        changed.append({"component": aid, "setting_id": sid, "value_present": bool(str(value))})
    return {"backup_id": backup["backup_id"], "changed_count": len(changed), "changed_settings": changed, "warnings": ["Kodi/add-on restart may be required."], "restart_recommended": True}


def switch_player(kodi, index, target, apply_to=None, keep_current_as_fallback=True, write_enabled=False, kodi_version=""):
    if not write_enabled:
        raise PermissionError("Writes disabled in service settings")
    addon = index.get(target)
    if not addon or not (addon.get("installed") or addon.get("config_present")):
        raise ValueError("%s is not detected. Install/configure it first, then rescan." % target)
    # Nothing is changed here, so no snapshot is taken.
    return {"supported": False, "backup_id": None, "reason": "Routing appears player-file/native-helper based; use native helper settings or add a safe adapter.", "target_player_addon_id": target, "applied_changes": [], "keep_current_as_fallback": bool(keep_current_as_fallback), "apply_to": apply_to or ["movie", "episode"]}
