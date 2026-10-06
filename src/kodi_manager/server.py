import json
import os
import platform
import posixpath
import shutil
import sqlite3
import tempfile
import threading
import time
import ipaddress
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlparse

try:
    from .version import VERSION
    from .client import READ_POSTS
    from .fix_protection import protection_for_kodi
    from .auth import authorized
    from .addon_index import AddonIndex
    from .adapters import adapter_for
    from .backup import set_retention, create_backup, create_stack_backup, list_backups, restore_backup, restore_stack_backup
    from .settings_schema import parse_schema, flatten_settings, parse_user_settings
    from .stack_detector import detect_stack
    from .pipeline import build_pipeline, apply_pipeline_settings, pipeline_backup, switch_player, build_accounts, apply_account_settings, pretty_label, setting_description, DB_EDITABLE_TYPES
    from .kodi_api import debug_paths, safe_listdir, translate
    from .validation import coerce_value, redact, is_secret_like, mask_value
    from .widget_catalog import list_sources, browse_directory, suggest_kids_rows
    from .widget_filters import filter_items
    from .widget_preview import row_preview
    from .skin_layout import inspect_layout, preview_layout, apply_layout, request_rebuild
except ImportError:
    from version import VERSION
    from client import READ_POSTS
    from fix_protection import protection_for_kodi
    from auth import authorized
    from addon_index import AddonIndex
    from adapters import adapter_for
    from backup import set_retention, create_backup, create_stack_backup, list_backups, restore_backup, restore_stack_backup
    from settings_schema import parse_schema, flatten_settings, parse_user_settings
    from stack_detector import detect_stack
    from pipeline import build_pipeline, apply_pipeline_settings, pipeline_backup, switch_player, build_accounts, apply_account_settings, pretty_label, setting_description, DB_EDITABLE_TYPES
    from kodi_api import debug_paths, safe_listdir, translate
    from validation import coerce_value, redact, is_secret_like, mask_value
    from widget_catalog import list_sources, browse_directory, suggest_kids_rows
    from widget_filters import filter_items
    from widget_preview import row_preview
    from skin_layout import inspect_layout, preview_layout, apply_layout, request_rebuild


class AdminState:
    def __init__(self, kodi, config, web_root):
        self.kodi = kodi
        self.config = config
        self.web_root = web_root
        self.index = AddonIndex(kodi)
        self.logs = []

    def log(self, msg):
        safe = str(redact({"msg": msg})["msg"])
        self.logs.append("%s %s" % (time.strftime("%H:%M:%S"), safe))
        self.logs = self.logs[-300:]
        self.kodi.log(safe)


def _private_client(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return bool(addr.is_private or addr.is_loopback)
    except ValueError:
        return False


def _setting_count(groups):
    return sum(len(g.get("settings", [])) for g in groups or [])


def _raw_settings_group(addon):
    vals = parse_user_settings(addon.get("user_settings_path"))
    return {"id": "raw_user_settings", "label": "Raw user settings", "settings": [{"id": k, "label": pretty_label(k), "description": setting_description(k, k), "type": "text", "value": v, "default": "", "options": [], "editable": True, "masked": False, "warning": "Schema missing; edited as raw text", "raw": {"source": "raw"}} for k, v in sorted(vals.items())]}


def _fenlight_db_settings(addon):
    if addon.get("addon_id") != "plugin.video.fenlight":
        return []
    db_path = translate(os.path.join(addon.get("addon_data_path") or "", "databases", "settings.db"))
    if not db_path or not os.path.exists(db_path):
        return []
    tmp = ""
    try:
        try:
            con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
        except Exception:
            # Fallback for SMB-style locks. On Android, use addon_data-adjacent temp; /tmp may not exist.
            tmp_dir = os.path.dirname(os.path.dirname(addon.get("addon_data_path") or db_path))
            tmp = os.path.join(tmp_dir, "service.kodi.addonadmin", "fenlight_settings_tmp.db")
            try:
                os.makedirs(os.path.dirname(tmp))
            except Exception:
                fd, tmp = tempfile.mkstemp(prefix="fenlight_settings_", suffix=".db")
                os.close(fd)
            shutil.copyfile(db_path, tmp)
            con = sqlite3.connect(tmp)
        rows = con.execute("select setting_id, setting_type, setting_default, setting_value from settings order by setting_id").fetchall()
        con.close()
        settings = []
        for sid, stype, default, value in rows:
            masked = False
            editable = bool((stype or "").lower() in DB_EDITABLE_TYPES)
            settings.append({
                "id": sid,
                "label": pretty_label(sid),
                "description": setting_description(sid, sid),
                "type": stype or "text",
                "value": value,
                "default": default,
                "options": [],
                "editable": editable,
                "masked": masked,
                "warning": "" if editable else "Fen Light settings.db setting is unsupported",
                "raw": {"source": "plugin.video.fenlight/databases/settings.db"},
            })
        return settings
    except Exception as exc:
        return [{"id": "fenlight_db_error", "label": "Fen Light settings.db", "type": "error", "value": str(exc), "default": "", "options": [], "editable": False, "masked": False, "warning": "Could not read Fen Light settings.db", "raw": {}}]
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


def settings_for_addon(addon):
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


def health_summary(kodi, index, config):
    index.refresh()
    stack = detect_stack(kodi, index)
    addons = index.list()
    paths = debug_paths(config.get("installer_seed", {}))
    logs = kodi.get_log_lines(200)
    errors = [line for line in logs if "error" in line.lower() or "exception" in line.lower() or "traceback" in line.lower()]
    warnings = [line for line in logs if "warning" in line.lower() or "warn:" in line.lower()]
    core = ["skin", "tmdbhelper", "fenlight", "fen", "pov", "cocoscrapers"]
    found = sum(1 for key in core if stack.get(key, {}).get("found") or stack.get(key, {}).get("active"))
    checks = [
        {"id": "jsonrpc", "label": "Kodi JSON-RPC", "status": "ok" if kodi.get_kodi_version() else "warning", "detail": kodi.get_kodi_version()},
        {"id": "stack", "label": "Core stack", "status": "ok" if found >= 4 else "warning", "detail": "%s/%s detected" % (found, len(core))},
        {"id": "addon_data", "label": "Addon config path", "status": "ok" if paths.get("addon_data_probe", {}).get("selected_path") else "error", "detail": paths.get("addon_data_probe", {}).get("selected_path", "")},
        {"id": "addons_path", "label": "Installed add-ons path", "status": "ok" if paths.get("addons_probe", {}).get("selected_path") else "warning", "detail": paths.get("addons_probe", {}).get("selected_path", "")},
        {"id": "write_mode", "label": "Write mode", "status": "ok" if config.get("write_enabled") else "warning", "detail": "enabled" if config.get("write_enabled") else "disabled"},
        {"id": "logs", "label": "Kodi log scan", "status": "error" if errors else ("warning" if warnings else "ok"), "detail": "%s errors · %s warnings in last 200 lines" % (len(errors), len(warnings))},
    ]
    status = "error" if any(c["status"] == "error" for c in checks) else ("warning" if any(c["status"] == "warning" for c in checks) else "ok")
    return {
        "status": status,
        "checks": checks,
        "stats": {
            "addons": len(addons),
            "enabled_addons": len([a for a in addons if a.get("enabled") is True]),
            "config_folders": len([a for a in addons if a.get("config_present")]),
            "stack_detected": found,
            "kodi_log_errors": len(errors),
            "kodi_log_warnings": len(warnings),
        },
        "recent_errors": errors[-20:],
        "recent_warnings": warnings[-20:],
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


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KodiManager/" + VERSION
        timeout = 20

        def log_message(self, fmt, *args):
            state.log(fmt % args)

        def _send(self, status, data, content_type="application/json"):
            body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def ok(self, data=None):
            self._send(200, {"ok": True, "data": data if data is not None else {}})

        def err(self, status, code, message, details=None):
            self._send(status, {"ok": False, "error": {"code": code, "message": message, "details": redact(details or {})}})

        def _auth(self):
            if not self.path.startswith("/api/"):
                return True
            if urlparse(self.path).path == "/api/bootstrap/status" and self._bootstrap_allowed():
                return True
            if state.config.get("host") == "0.0.0.0" and not _private_client(self.client_address[0]):
                self.err(403, "forbidden", "Non-private client rejected")
                return False
            if not authorized(self.headers.get("Authorization"), state.config.get("auth_token")):
                self.err(401, "unauthorized", "Missing or invalid bearer token")
                return False
            if state.config.get("delete_installer_result_after_first_login"):
                try:
                    os.remove(os.path.join(state.config.get("addon_data_dir", ""), "installer_result.json"))
                except Exception:
                    pass
            return True

        def _bootstrap_allowed(self):
            data_dir = state.config.get("addon_data_dir", "")
            return os.path.exists(os.path.join(data_dir, "installer_seed.json")) and os.path.exists(os.path.join(data_dir, "installer_result.json"))

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain")

        def _json_body(self):
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 0 or length > 1_000_000 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Request body must be at most 1 MB with a fixed length")
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            if not self._auth():
                return
            try:
                if self.path.startswith("/api/"):
                    self.route_api("GET")
                else:
                    self.static()
            except Exception as exc:
                self.err(500, "server_error", str(exc))

        def do_POST(self):
            if not self._auth():
                return
            try:
                self.route_api("POST")
            except PermissionError as exc:
                self.err(403, "write_disabled", str(exc))
            except ValueError as exc:
                self.err(400, "bad_request", str(exc))
            except Exception as exc:
                self.err(500, "server_error", str(exc))

        def do_PATCH(self):
            if not self._auth():
                return
            try:
                self.route_api("PATCH")
            except PermissionError as exc:
                self.err(403, "write_disabled", str(exc))
            except ValueError as exc:
                self.err(400, "bad_request", str(exc))
            except Exception as exc:
                self.err(500, "server_error", str(exc))

        def static(self):
            path = unquote(urlparse(self.path).path)
            if path == "/":
                path = "/index.html"
            rel = posixpath.normpath(path).lstrip("/")
            full = os.path.abspath(os.path.join(state.web_root, rel))
            web_root = os.path.abspath(state.web_root)
            if os.path.commonpath([web_root, full]) != web_root or not os.path.isfile(full):
                self.err(404, "not_found", "File not found")
                return
            ctype = "text/html" if full.endswith(".html") else "text/css" if full.endswith(".css") else "application/javascript" if full.endswith(".js") else "application/octet-stream"
            with open(full, "rb") as fh:
                self._send(200, fh.read(), ctype)

        def _require_idle(self, message):
            players = state.kodi.jsonrpc("Player.GetActivePlayers")
            if not isinstance(players, dict) or "error" in players or players.get("result") != []:
                raise ValueError(message)

        def _addon(self, aid):
            state.index.refresh()
            addon = state.index.get(aid)
            if not addon:
                self.err(404, "not_found", "Add-on not found")
                return None
            return addon

        def route_api(self, method):
            path = urlparse(self.path).path
            parts = [p for p in path.split("/") if p]
            if method != "GET" and not (method == "POST" and path in READ_POSTS):
                if not state.config.get("write_enabled"):
                    raise PermissionError("Write Mode is disabled")
            if path == "/api/fixes" and method == "GET":
                self.ok(protection_for_kodi().status())
                return
            if path == "/api/fixes/repair" and method == "POST":
                if not state.config.get("write_enabled"):
                    raise PermissionError("Write Mode is disabled")
                self._require_idle("Stop playback before restoring fixes")
                self.ok(protection_for_kodi().repair())
                return
            if path in ("/api/widgets/sources", "/api/widgets/layout") and method == "GET":
                state.index.refresh()
                if path == "/api/widgets/sources":
                    self.ok(list_sources(state.kodi, state.index))
                else:
                    layout = inspect_layout(state.kodi, state.index)
                    if not state.config.get("write_enabled"):
                        layout["can_apply"] = False
                        layout["new_section_available"] = False
                        for section in layout.get("sections", []):
                            section["editable"] = False
                        layout["reasons"] = list(layout.get("reasons", [])) + ["Write Mode is disabled. Enable it in Kodi Manager service settings to apply this layout."]
                    self.ok(layout)
                return
            if method == "POST" and path in ("/api/widgets/browse", "/api/widgets/suggestions", "/api/widgets/row-preview", "/api/widgets/layout/preview", "/api/widgets/layout/apply", "/api/widgets/layout/rebuild"):
                body = self._json_body()
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object.")
                state.index.refresh()
                if path == "/api/widgets/row-preview":
                    self.ok(row_preview(state.kodi, state.index, body))
                elif path == "/api/widgets/browse":
                    if not isinstance(body.get("family_preview", False), bool):
                        raise ValueError("family_preview must be boolean")
                    result = browse_directory(state.kodi, state.index, body.get("path", ""), body.get("start", 0), body.get("limit", 48), refresh=body.get("refresh", False))
                    if body.get("family_preview"):
                        result["family_preview"] = filter_items([{**item, "file": item["path"]} for item in result["items"]], body.get("max_rating", "12A"), True)
                    self.ok(result)
                elif path == "/api/widgets/suggestions":
                    self.ok(suggest_kids_rows(state.kodi, state.index))
                elif path == "/api/widgets/layout/preview":
                    layout = preview_layout(state.kodi, state.index, body)
                    if not state.config.get("write_enabled"):
                        layout["can_apply"] = False
                        layout["new_section_available"] = False
                        for section in layout.get("sections", []):
                            section["editable"] = False
                        layout["reasons"] = list(layout.get("reasons", [])) + ["Write Mode is disabled. Enable it in Kodi Manager service settings to apply this layout."]
                    self.ok(layout)
                else:
                    write_enabled = bool(state.config.get("write_enabled"))
                    if not write_enabled:
                        raise PermissionError("Write Mode is disabled. Enable it in Kodi Manager service settings to apply this layout.")
                    if path.endswith("/rebuild"):
                        # Rebuilding reloads the skin, which interrupts whoever is watching.
                        self._require_idle("Stop playback before rebuilding the TV menu")
                        self.ok(request_rebuild(state.kodi, state.index))
                    else:
                        self.ok(apply_layout(state.kodi, state.index, body, write_enabled))
                return
            if method == "GET" and path == "/api/status":
                state.index.refresh()
                self.ok({
                    "service_version": VERSION,
                    "Kodi version": state.kodi.get_kodi_version(),
                    "server": {"host": state.config.get("host"), "port": state.config.get("port")},
                    "write_enabled": state.config.get("write_enabled"),
                    "allow_lan": state.config.get("allow_lan"),
                    "active_skin": state.kodi.get_active_skin(),
                    "current_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "platform": platform.platform(),
                    "stack": detect_stack(state.kodi, state.index),
                })
                return
            if method == "GET" and path == "/api/bootstrap/status":
                seed = state.config.get("installer_seed", {})
                self.ok({"installed": True, "web_url": "http://%s:%s" % (seed.get("kodi_ip_hint", "127.0.0.1"), state.config.get("port")), "needs_auth": True, "nonce_present": bool(seed.get("installer_nonce"))})
                return
            if method == "GET" and path == "/api/stack":
                state.index.refresh()
                self.ok(detect_stack(state.kodi, state.index))
                return
            if method == "GET" and path == "/api/health":
                self.ok(health_summary(state.kodi, state.index, state.config))
                return
            if method == "GET" and path == "/api/integrations":
                state.index.refresh()
                self.ok(integration_status(state.index))
                return
            if method == "GET" and path == "/api/accounts":
                state.index.refresh()
                self.ok(build_accounts(state.kodi, state.index))
                return
            if method == "PATCH" and path == "/api/accounts/settings":
                state.index.refresh()
                try:
                    self.ok(apply_account_settings(state.kodi, state.index, self._json_body().get("changes", []), state.config.get("write_enabled"), state.kodi.get_kodi_version()))
                except PermissionError as exc:
                    self.err(403, "write_disabled", str(exc))
                except ValueError as exc:
                    self.err(400, "account_write_blocked", str(exc))
                return
            if method == "GET" and path == "/api/pipeline":
                state.index.refresh()
                self.ok(build_pipeline(state.kodi, state.index))
                return
            if method == "GET" and path == "/api/pipeline/debug":
                state.index.refresh()
                pipe = build_pipeline(state.kodi, state.index)
                self.ok({"pipeline": pipe, "paths": debug_paths(state.config.get("installer_seed", {})), "stack_raw": {"merged_records": state.index.addons, "classified_stack": detect_stack(state.kodi, state.index)}})
                return
            if method == "POST" and path == "/api/pipeline/rescan":
                state.index.refresh()
                self.ok(build_pipeline(state.kodi, state.index))
                return
            if method == "POST" and path == "/api/pipeline/backup":
                state.index.refresh()
                pipe = build_pipeline(state.kodi, state.index)
                self.ok(pipeline_backup(state.index, state.kodi.get_kodi_version(), pipe))
                return
            if method == "PATCH" and path == "/api/pipeline/settings":
                state.index.refresh()
                body = self._json_body()
                try:
                    self.ok(apply_pipeline_settings(state.kodi, state.index, body.get("changes", []), state.config.get("write_enabled"), state.kodi.get_kodi_version()))
                except PermissionError as exc:
                    self.err(403, "write_disabled", str(exc))
                except ValueError as exc:
                    self.err(400, "invalid_pipeline_setting", str(exc))
                return
            if method == "POST" and path == "/api/pipeline/switch-player":
                state.index.refresh()
                body = self._json_body()
                try:
                    self.ok(switch_player(state.kodi, state.index, body.get("target_player_addon_id", ""), body.get("apply_to"), body.get("keep_current_as_fallback", True), state.config.get("write_enabled"), state.kodi.get_kodi_version()))
                except PermissionError as exc:
                    self.err(403, "write_disabled", str(exc))
                except ValueError as exc:
                    self.err(400, "switch_player_blocked", str(exc))
                return
            if method == "POST" and path == "/api/playback/test":
                self.ok(playback_test(state.kodi, state.index, self._json_body()))
                return
            if method == "GET" and path == "/api/debug/paths":
                self.ok(dict({"kodi_version": state.kodi.get_kodi_version(), "platform": platform.platform()}, **debug_paths(state.config.get("installer_seed", {}))))
                return
            if method == "GET" and path == "/api/debug/stack-raw":
                state.index.refresh()
                self.ok({
                    "jsonrpc_addons_count": len(state.kodi.list_addons()),
                    "jsonrpc_ids": sorted([a.get("addon_id") for a in state.kodi.list_addons() if a.get("addon_id")]),
                    "addon_data_ids": state.index.probe.get("addon_data_probe", {}).get("selected_dirs", []),
                    "installed_addon_ids": state.index.probe.get("addons_probe", {}).get("selected_dirs", []),
                    "probe": state.index.probe,
                    "merged_records": state.index.addons,
                    "classified_stack": detect_stack(state.kodi, state.index),
                })
                return
            if method == "GET" and path == "/api/addons":
                state.index.refresh()
                self.ok(state.index.list())
                return
            if method == "GET" and path == "/api/search/config":
                state.index.refresh()
                q = (parse_qs(urlparse(self.path).query).get("q") or [""])[0].lower().strip()
                if not q:
                    self.ok({"query": q, "results": []})
                    return
                results = []
                for addon in state.index.list():
                    parsed = settings_for_addon(addon)
                    for group in parsed.get("groups", []):
                        for setting in group.get("settings", []):
                            hay = " ".join(str(x or "") for x in [addon.get("addon_id"), addon.get("name"), group.get("label"), setting.get("id"), setting.get("label"), setting.get("value")]).lower()
                            if q in hay:
                                results.append({
                                    "addon_id": addon.get("addon_id"),
                                    "addon_name": addon.get("name"),
                                    "version": addon.get("version", ""),
                                    "group": group.get("label"),
                                    "id": setting.get("id"),
                                    "label": setting.get("label"),
                                    "value": setting.get("value"),
                                    "type": setting.get("type"),
                                    "description": setting.get("description"),
                                    "editable": setting.get("editable"),
                                    "masked": setting.get("masked"),
                                    "warning": setting.get("warning"),
                                })
                            if len(results) >= 500:
                                break
                        if len(results) >= 500:
                            break
                    if len(results) >= 500:
                        break
                self.ok({"query": q, "count": len(results), "results": results})
                return
            if method == "GET" and path == "/api/logs":
                self.ok({"lines": state.logs[-200:]})
                return
            if method == "GET" and path == "/api/kodi/logs":
                self.ok({"lines": state.kodi.get_log_lines(500)})
                return
            if method == "POST" and path == "/api/addons/install":
                self._json_body()
                self._require_idle("Stop playback before opening Install from zip on the TV")
                self.ok(state.kodi.open_install_from_zip())
                return
            if method == "POST" and path == "/api/stack/backup":
                stack = detect_stack(state.kodi, state.index)
                ids = [stack[k].get("addon_id") for k in ("tmdbhelper", "fenlight", "fen", "pov", "cocoscrapers", "trakt")]
                ids.append(stack["skin"].get("addon_id"))
                ids += ["script.skinshortcuts", "shortcutmanager", "script.skin.helper.service", "script.skin.helper.widgets", "plugin.program.openwizard"]
                addons = [state.index.get(aid) for aid in ids if aid]
                self.ok(create_stack_backup(addons, state.kodi.get_kodi_version()))
                return
            if method == "GET" and path == "/api/stack/backups":
                self.ok({"backups": list_backups(stack=True)})
                return
            if method == "GET" and path == "/api/backups/timeline":
                self.ok(backup_timeline())
                return
            if method == "POST" and path == "/api/stack/restore":
                self.ok(restore_stack_backup(state.index, self._json_body().get("backup_id", "")))
                return
            if len(parts) >= 3 and parts[1] == "addons":
                aid = unquote(parts[2])
                addon = self._addon(aid)
                if not addon:
                    return
                adapter = adapter_for(addon, state.kodi, state.index.addons)
                if len(parts) == 3 and method == "GET":
                    details = dict(addon)
                    details["warnings"] = adapter.get_warnings(addon)
                    details["related"] = adapter.extra_details(addon)
                    self.ok(details)
                    return
                action = parts[3] if len(parts) > 3 else ""
                if action == "settings" and method == "GET":
                    parsed = settings_for_addon(addon)
                    parsed.update({"addon_id": aid, "name": addon.get("name"), "adapter": adapter.name, "warnings": parsed.get("warnings", []) + adapter.get_warnings(addon)})
                    self.ok(parsed)
                    return
                if action == "settings" and method == "PATCH":
                    if not state.config.get("write_enabled"):
                        self.err(403, "write_disabled", "Writes disabled in service settings")
                        return
                    allowed = set(x.strip() for x in (state.config.get("allowed_addons_csv") or "").split(",") if x.strip())
                    if not addon.get("is_stack_addon") and aid not in allowed:
                        self.err(403, "addon_not_allowed", "Add-on is outside focused stack")
                        return
                    parsed = parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True)
                    settings = flatten_settings(parsed)
                    changes = self._json_body().get("changes", [])
                    clean = []
                    for ch in changes:
                        sid = ch.get("id")
                        if aid == "plugin.video.fenlight" and ch.get("source") == "settings.db":
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
                            clean.append({"id": sid, "value": str(ch.get("value")), "source": "settings.db"})
                            con.close()
                            continue
                        if ch.get("source") == "raw":
                            raw_vals = parse_user_settings(addon.get("user_settings_path"))
                            if sid not in raw_vals:
                                raise ValueError("Unknown raw setting: %s" % sid)
                            clean.append({"id": sid, "value": str(ch.get("value")), "source": "raw"})
                            continue
                        if sid not in settings:
                            raise ValueError("Unknown setting: %s" % sid)
                        setting = settings[sid]
                        if not setting.get("editable"):
                            raise ValueError("Setting not editable: %s" % sid)
                        clean.append({"id": sid, "value": coerce_value(setting, ch.get("value"))})
                    backup = create_backup(addon, state.kodi.get_kodi_version(), adapter.name)
                    for ch in clean:
                        if ch.get("source") == "settings.db":
                            db_path = translate(os.path.join(addon.get("addon_data_path") or "", "databases", "settings.db"))
                            con = sqlite3.connect(db_path)
                            con.execute("update settings set setting_value=? where setting_id=?", (ch["value"], ch["id"]))
                            con.commit()
                            con.close()
                        else:
                            state.kodi.set_addon_setting(aid, ch["id"], ch["value"])
                    self.ok({"changed_count": len(clean), "backup_id": backup["backup_id"], "warnings": adapter.after_write(aid, clean)})
                    return
                if action == "open-settings" and method == "POST":
                    self.ok({"opened": state.kodi.open_addon_settings(aid)})
                    return
                if action == "backup" and method == "POST":
                    self.ok(create_backup(addon, state.kodi.get_kodi_version(), adapter.name))
                    return
                if action == "backups" and method == "GET":
                    self.ok({"backups": list_backups(aid)})
                    return
                if action == "restore" and method == "POST":
                    self.ok(restore_backup(addon, self._json_body().get("backup_id", "")))
                    return
            if method == "POST" and path == "/api/windows/open-skin-settings":
                self.ok({"opened": state.kodi.open_skin_settings()})
                return
            if method == "POST" and path == "/api/trakt/sync":
                addon = state.index.get("script.trakt")
                if not addon or not addon.get("enabled"):
                    self.err(404, "trakt_unavailable", "script.trakt not installed/enabled")
                    return
                self.ok(state.kodi.execute_addon("script.trakt", {"action": "sync"}))
                return
            self.err(404, "not_found", "Route not found")

    return Handler


class ServerThread(threading.Thread):
    def __init__(self, kodi, config, web_root):
        super(ServerThread, self).__init__()
        self.daemon = True
        self.stopping = threading.Event()
        self.state = AdminState(kodi, config, web_root)
        set_retention(config.get("backup_retention", 20))
        self.httpd = ThreadingHTTPServer((config["host"], int(config["port"])), make_handler(self.state))
        self.httpd.timeout = 0.2

    def run(self):
        self.state.log("Server started at http://%s:%s" % (self.state.config["host"], self.state.config["port"]))
        try:
            while not self.stopping.is_set():
                try:
                    self.httpd.handle_request()
                except (OSError, ValueError):
                    if not self.stopping.is_set():
                        raise
        finally:
            self.httpd.server_close()

    def stop(self):
        # Profile changes stop scripts while Kodi's UI thread is unavailable.
        # Never wait on a server thread that might be blocked in a Kodi call.
        self.stopping.set()
        self.httpd.server_close()
