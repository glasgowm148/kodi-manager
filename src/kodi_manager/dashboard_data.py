"""What the dashboard shows, computed from Kodi, the add-on index and the service's own records.

Plain functions behind the API routes (api_*.py): settings of one add-on, account references,
Health, the overview screen, the backup timeline, row titles and the playback dry run. No HTTP here.
"""
import time
from urllib.parse import urlsplit
from typing import Any, Dict

try:
    from .version import VERSION
    from .fix_protection import protection_for_kodi
    from .backup import list_backups
    from .settings_schema import parse_schema, parse_user_settings, setting_description
    from .stack_detector import detect_stack
    from .pipeline import build_pipeline, pretty_label
    from .kodi_api import debug_paths, translate
    from .validation import redact
    from .widget_cache import ttl_for
    from . import fenlight_db
    from .memstat import memory_status
    from .netwatch import internet_check, latest_internet
    from .metrics import process_started_at, widget_row_counts
    from .row_titles import label_resolver, row_titles
    from .baseline import Baseline
    from .log_scan import scan_log_lines  # noqa: F401
    from . import maintenance
except ImportError:
    from version import VERSION
    from fix_protection import protection_for_kodi
    from backup import list_backups
    from settings_schema import parse_schema, parse_user_settings, setting_description
    from stack_detector import detect_stack
    from pipeline import build_pipeline, pretty_label
    from kodi_api import debug_paths, translate
    from validation import redact
    from widget_cache import ttl_for
    import fenlight_db
    from memstat import memory_status
    from netwatch import internet_check, latest_internet
    from metrics import process_started_at, widget_row_counts
    from row_titles import label_resolver, row_titles
    from baseline import Baseline
    from log_scan import scan_log_lines  # noqa: F401
    import maintenance

WIDGET_CACHE_DIR = "special://profile/addon_data/service.kodi.addonadmin/widget_cache"


def _setting_count(groups):
    return sum(len(g.get("settings", [])) for g in groups or [])


def _raw_settings_group(addon):
    vals = parse_user_settings(addon.get("user_settings_path"))
    return {"id": "raw_user_settings", "label": "Raw user settings", "settings": [{"id": k, "label": pretty_label(k), "description": setting_description(k, k), "type": "text", "value": v, "default": "", "options": [], "editable": True, "masked": False, "warning": "Schema missing; edited as raw text", "raw": {"source": "raw"}} for k, v in sorted(vals.items())]}


def _fenlight_db_settings(addon):
    try:
        rows = fenlight_db.read_rows(addon)
    except Exception as exc:
        return [{"id": "fenlight_db_error", "label": "Fen Light settings.db", "type": "error", "value": str(exc), "default": "", "options": [], "editable": False, "masked": False, "warning": "Could not read Fen Light settings.db", "raw": {}}]
    settings = []
    for sid, stype, default, value in rows:
        editable = bool((stype or "").lower() in fenlight_db.DB_EDITABLE_TYPES)
        settings.append({
            "id": sid,
            "label": pretty_label(sid),
            "description": setting_description(sid, sid),
            "type": stype or "text",
            "value": value,
            "default": default,
            "options": [],
            "editable": editable,
            "masked": False,
            "warning": "" if editable else "Fen Light settings.db setting is unsupported",
            "raw": {"source": "plugin.video.fenlight/databases/settings.db"},
        })
    return settings


def settings_for_addon(addon) -> Dict[str, Any]:
    """Dashboard settings show stored values, including tokens, so users can enter and repair them."""
    parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
    if _setting_count(parsed.get("groups")) == 0 and addon.get("has_user_settings"):
        raw_group = _raw_settings_group(addon)
        if parsed.get("groups"):
            parsed["groups"].append(raw_group)
        else:
            parsed["groups"] = [raw_group]
    db_settings = _fenlight_db_settings(addon)
    if db_settings:
        parsed.setdefault("groups", []).append({"id": "fenlight_db", "label": "Fen Light database settings", "settings": db_settings})
    return parsed


def integration_status(index):
    out = {"torbox": [], "trakt": [], "notes": []}
    scan_ids = ["plugin.video.fenlight", "plugin.video.fen", "plugin.video.pov", "plugin.video.tmdb.bingie.helper", "skin.bingie", "script.skinshortcuts", "shortcutmanager"]
    for aid in scan_ids:
        addon = index.get(aid)
        if not addon:
            continue
        parsed = settings_for_addon(addon)
        for group in parsed.get("groups", []):
            for setting in group.get("settings", []):
                hay = " ".join(str(x or "") for x in [setting.get("id"), setting.get("label"), setting.get("value")]).lower()
                item = {
                    "addon_id": aid,
                    "addon_name": addon.get("name", aid),
                    "version": addon.get("version", ""),
                    "group": group.get("label", ""),
                    "id": setting.get("id", ""),
                    "value": setting.get("value", ""),
                    "masked": setting.get("masked", False),
                    "editable": setting.get("editable", False),
                    "source": setting.get("raw", {}).get("source", "settings.xml"),
                }
                if "torbox" in hay:
                    out["torbox"].append(item)
                if "trakt" in hay:
                    out["trakt"].append(item)
    if not index.get("script.trakt"):
        out["notes"].append("Standalone script.trakt add-on not found. Trakt settings/widgets may be handled inside Fen/Fen Light/POV/Bingie components.")
    if out["torbox"]:
        out["notes"].append("TorBox references found. Fen Light stores its TorBox setting in settings.db, so Kodi Manager shows it read-only for now.")
    return out


STACK_EXTRA_IDS = ("script.skinshortcuts", "shortcutmanager", "script.skin.helper.service",
                   "script.skin.helper.widgets", "plugin.program.openwizard")


def stack_backup_addons(kodi, index):
    """Add-ons whose settings a stack checkpoint covers."""
    stack = detect_stack(kodi, index)
    ids = [stack[k].get("addon_id") for k in ("tmdbhelper", "fenlight", "fen", "pov", "cocoscrapers", "trakt")]
    ids.append(stack["skin"].get("addon_id"))
    ids += list(STACK_EXTRA_IDS)
    return [index.get(aid) for aid in ids if aid]


def make_baseline(kodi):
    return Baseline(translate("special://profile/addon_data/service.kodi.addonadmin/baseline.json"), kodi,
                    addon_path=lambda addon_id: (kodi.get_addon_details(addon_id) or {}).get("path", ""))


def maintenance_checks(kodi):
    """Protected settings, accounts and the nightly checkpoint for the Health page."""
    checks = []
    try:
        rows = make_baseline(kodi).check()
    except Exception:
        rows = []
    if rows:
        drift = [r for r in rows if not r["ok"] and not r["missing"]]
        check: Dict[str, Any] = {"id": "baseline", "label": "Protected settings",
                 "status": "warning" if drift else "ok",
                 "detail": ("%d changed: %s" % (len(drift), "; ".join("%s is %s, expected %s" % (r["label"], r["current"], r["expected"]) for r in drift)))
                 if drift else "%d settings as you set them" % len(rows)}
        if drift:
            check["action"] = {"label": "Re-apply", "path": "/api/baseline/apply"}
        checks.append(check)
    snap = maintenance.snapshot()
    checks.extend(dict(a) for a in snap["accounts"])
    nightly = snap["nightly"]
    if nightly:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(nightly["at"]))
        checks.append({"id": "nightly", "label": "Nightly checkpoint",
                       "status": "ok" if nightly["status"] == "ok" else "warning",
                       "detail": ("Last taken %s" % when) if nightly["status"] == "ok" else "Failed %s (%s)" % (when, nightly.get("error"))})
    return checks


def health_summary(kodi, index, config):
    index.refresh()
    stack = detect_stack(kodi, index)
    addons = index.list()
    paths = debug_paths(config.get("installer_seed", {}))
    history = kodi.get_log_history(limit=20)
    counts = history["counts"]
    log_status = "error" if counts["errors"] else ("warning" if counts["warnings"] or not history["available"] or history["catching_up"] else "ok")
    log_detail = "%s errors · %s warnings%s in the past 24 hours" % (counts["errors"], counts["warnings"], " · %s known notices" % counts["notices"] if counts["notices"] else "")
    if history.get('issues_ready'):
        log_detail += ' · %s issue groups' % history.get('issue_total', 0)
    if not history["available"]:
        log_detail += " · collection unavailable"
    elif history["catching_up"]:
        log_detail += " · importing available logs"
    core = ["skin", "tmdbhelper", "fenlight", "fen", "pov", "cocoscrapers"]
    memory = memory_status()
    found = sum(1 for key in core if stack.get(key, {}).get("found") or stack.get(key, {}).get("active"))
    checks = [
        {"id": "jsonrpc", "label": "Kodi JSON-RPC", "status": "ok" if kodi.get_kodi_version() else "warning", "detail": kodi.get_kodi_version()},
        {"id": "stack", "label": "Optional integrations", "status": "info", "detail": "%s recognised integrations detected; only install the add-ons you need" % found},
        {"id": "addon_data", "label": "Addon config path", "status": "ok" if paths.get("addon_data_probe", {}).get("selected_path") else "error", "detail": paths.get("addon_data_probe", {}).get("selected_path", "")},
        {"id": "addons_path", "label": "Installed add-ons path", "status": "ok" if paths.get("addons_probe", {}).get("selected_path") else "warning", "detail": paths.get("addons_probe", {}).get("selected_path", "")},
        {"id": "write_mode", "label": "Dashboard access", "status": "info", "detail": "Changes allowed" if config.get("write_enabled") else "View only; changes are disabled for this profile"},
        dict({"id": "memory", "label": "Memory"}, **{k: v for k, v in memory.items() if k in ("status", "detail")}),
        {"id": "logs", "label": "Recorded Kodi logs", "status": log_status, "detail": log_detail},
    ]
    internet = internet_check()
    if internet:
        checks.insert(len(checks) - 1, internet)
    for extra in maintenance_checks(kodi):
        checks.insert(len(checks) - 1, extra)
    checks = [c for c in checks if c.get("status") != "unknown"]
    status = "error" if any(c["status"] == "error" for c in checks) else ("warning" if any(c["status"] == "warning" for c in checks) else "ok")
    return {
        "status": status,
        "checks": checks,
        "stats": {
            "addons": len(addons),
            "enabled_addons": len([a for a in addons if a.get("enabled") is True]),
            "config_folders": len([a for a in addons if a.get("config_present")]),
            "stack_detected": found,
            "kodi_log_errors": counts["errors"],
            "kodi_log_warnings": counts["warnings"],
            "kodi_log_notices": counts["notices"],
            "kodi_log_warning_lines": counts["warning_lines"],
            "kodi_memory_mb": memory.get("kodi_mb"),
        },
        # Log lines can carry tokens and keys (URLs, headers): mask them like API errors.
        "recent_errors": redact([e["line"] for e in history["entries"] if e["level"] == "error"]),
        "recent_warnings": redact([e["line"] for e in history["entries"] if e["level"] != "error"]),
        "log_history": {k: history.get(k) for k in ("retention_hours", "since", "tracking_started_at", "last_scan_at", "available", "catching_up", "issues_ready", "issue_total", "recording_version", "counts", "since_update_counts", "last_problem_at", "now")},
        "log_issues": history.get('issues', [])[:5],
    }


def backup_timeline():
    stack = list_backups(stack=True)
    pipeline = list_backups("pipeline")
    items = []
    for kind, rows in (("stack", stack), ("pipeline", pipeline)):
        for row in rows:
            item = dict(row)
            item["kind"] = kind
            item["component_count"] = len(item.get("included_folders") or item.get("included_components") or [])
            item["skipped_count"] = len(item.get("skipped_folders") or item.get("skipped_components") or [])
            items.append(item)
    items.sort(key=lambda x: x.get("timestamp") or x.get("backup_id") or "", reverse=True)
    return {"items": items, "count": len(items)}


SHORTCUTS_DATA = "special://profile/addon_data/script.skinshortcuts"


def with_row_titles(kodi, index, entries):
    """Add title, addon_name, where and title_from to cached-row entries (see row_titles.py)."""
    sources = [e["source"] for e in entries if isinstance(e.get("source"), str)]
    addons = getattr(index, "addons", {}) or {}
    names = {}
    for source in sources:
        aid = urlsplit(source).netloc
        if aid in addons and (addons[aid] or {}).get("name"):
            names[aid] = addons[aid]["name"]
    skin = kodi.get_active_skin() if hasattr(kodi, "get_active_skin") else {}
    titles = row_titles(sources, translate(SHORTCUTS_DATA), label_resolver(kodi, (skin or {}).get("path", ""), (skin or {}).get("addon_id", "")), names)
    out = []
    for entry in entries:
        info = titles.get(entry.get("source"), {})
        out.append(dict(entry, title=info.get("title", ""), addon_name=info.get("addon", ""),
                        where=info.get("where", []), title_from=info.get("from", "path")))
    return out


def playback_state(kodi):
    """What the TV is doing: {active, type, title}. ``active`` is None when Kodi did not answer."""
    players = kodi.jsonrpc("Player.GetActivePlayers")
    result = players.get("result") if isinstance(players, dict) else None
    if not isinstance(result, list):
        return {"active": None, "type": "", "title": ""}
    if not result:
        return {"active": False, "type": "", "title": ""}
    player = result[0] if isinstance(result[0], dict) else {}
    state = {"active": True, "type": str(player.get("type") or "")[:20], "title": ""}
    if isinstance(player.get("playerid"), int):
        item = kodi.jsonrpc("Player.GetItem", {"playerid": player["playerid"], "properties": ["title", "showtitle"]})
        item = item.get("result", {}).get("item", {}) if isinstance(item, dict) else {}
        if isinstance(item, dict):
            title = item.get("title") or item.get("label") or ""
            show = item.get("showtitle") or ""
            state["title"] = str("%s: %s" % (show, title) if show and title else title or show)[:120]
            state["media"] = str(item.get("type") or "")[:20]
    return state


def current_profile(kodi):
    result = kodi.jsonrpc("Profiles.GetCurrentProfile")
    profile = result.get("result") if isinstance(result, dict) else None
    return str(profile.get("label") or "")[:60] if isinstance(profile, dict) else ""


def overview_summary(kodi, config):
    """Everything the dashboard's first screen needs, from figures the service already keeps.

    Cheap by design: no add-on scan, no log read and no network request.
    """
    memory = memory_status()
    internet = latest_internet()
    if internet:
        internet["age_seconds"] = max(0, int(time.time() - internet.get("checked_at", time.time())))
    try:
        stack_backups = list_backups(stack=True)
    except Exception:
        stack_backups = []
    stack_backups.sort(key=lambda b: str(b.get("timestamp") or b.get("backup_id") or ""), reverse=True)
    last = stack_backups[0] if stack_backups else None
    snap = maintenance.snapshot()
    baseline = snap["baseline"]
    if baseline is None:
        try:
            rows = make_baseline(kodi).check()
            drift = [r for r in rows if not r["ok"] and not r["missing"]]
            baseline = {"at": int(time.time()), "total": len(rows), "drifted": drift}
        except Exception:
            baseline = None
    try:
        fixes = protection_for_kodi().status()
        fixes = {"healthy": fixes.get("healthy"), "bundled": fixes.get("bundled"),
                 "attention": len([g for g in fixes.get("groups") or [] if g.get("status") != "ok"]),
                 "groups": len(fixes.get("groups") or [])}
    except Exception:
        fixes = {"healthy": None, "bundled": None, "attention": 0, "groups": 0}
    return {
        "generated_at": int(time.time()),
        "service_version": VERSION,
        "kodi_version": kodi.get_kodi_version(),
        "profile": current_profile(kodi),
        "write_enabled": config.get("write_enabled") is True,
        "playback": playback_state(kodi),
        "memory": memory,
        "internet": internet,
        "rows": widget_row_counts(translate(WIDGET_CACHE_DIR), ttl=ttl_for),
        "kodi_started_at": process_started_at(),
        "backups": {"count": len(stack_backups),
                    "last": {k: last.get(k) for k in ("backup_id", "timestamp", "note", "total_bytes")} if last else None,
                    "times": [b.get("timestamp") or b.get("backup_id") for b in stack_backups[:60]],
                    "nightly": snap["nightly"]},
        "protection": {"fixes": fixes,
                       "baseline": {"total": baseline["total"], "drifted": len(baseline["drifted"]),
                                    "labels": [r.get("label") for r in baseline["drifted"][:5]]} if baseline else None},
        "accounts": [{k: a.get(k) for k in ("id", "label", "status", "detail", "days_left", "renews") if k in a}
                     for a in snap["accounts"]],
    }


def playback_test(kodi, index, body):
    index.refresh()
    pipe = build_pipeline(kodi, index)
    target = body.get("target_player_addon_id") or pipe.get("summary", {}).get("primary_player", {}).get("addon_id")
    addon = index.get(target) if target else None
    plugin_url = body.get("plugin_url", "")
    steps = [
        {"step": "Kodi service reachable", "ok": bool(kodi.get_kodi_version()), "detail": kodi.get_kodi_version()},
        {"step": "Playback add-on detected", "ok": bool(addon and (addon.get("installed") or addon.get("config_present"))), "detail": target or "unknown"},
        {"step": "Pipeline routing known", "ok": bool(pipe.get("routing", {}).get("movie_player", {}).get("addon_id")), "detail": pipe.get("routing", {}).get("movie_player", {}).get("source", "unknown")},
        {"step": "Scraper module detected", "ok": bool(pipe.get("summary", {}).get("scraper_module", {}).get("found")), "detail": pipe.get("summary", {}).get("scraper_module", {}).get("addon_id", "")},
    ]
    active = kodi.jsonrpc("Player.GetActivePlayers").get("result", [])
    steps.append({"step": "Current player state", "ok": True, "detail": "active players: %s" % len(active)})
    if plugin_url:
        safe = plugin_url.startswith("plugin://")
        steps.append({"step": "Plugin URL format", "ok": safe, "detail": "plugin:// URL accepted" if safe else "Only plugin:// URLs allowed"})
        if safe and body.get("execute") is True:
            steps.append({"step": "Execution", "ok": False, "detail": "Blocked in MVP. Use native playback for actual media start."})
    return {"ok": all(s["ok"] for s in steps[:4]), "dry_run": True, "target_player_addon_id": target, "steps": steps, "pipeline_routing": pipe.get("routing", {})}
