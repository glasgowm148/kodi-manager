import json
import os
import platform
import posixpath
import re
import threading
import time
import ipaddress
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from .version import VERSION
    from .fix_protection import protection_for_kodi
    from .auth import authorized
    from .adapters import adapter_for
    from .addon_index import AddonIndex
    from .backup import set_retention, create_backup, create_stack_backup, list_backups, restore_backup, restore_stack_backup
    from .settings_schema import parse_schema, flatten_settings, parse_user_settings, setting_description
    from .stack_detector import detect_stack
    from .pipeline import build_pipeline, apply_pipeline_settings, pipeline_backup, switch_player, build_accounts, apply_account_settings, pretty_label
    from .kodi_api import debug_paths, translate
    from .validation import coerce_value, redact, mask_query_secrets
    from .widget_catalog import list_sources, browse_directory, suggest_kids_rows
    from .widget_filters import filter_items
    from .widget_preview import row_preview
    from .skin_layout import inspect_layout, preview_layout, apply_layout, request_rebuild
    from .widget_cache import WidgetCache, cache_url
    from .widget_rows import RowStore
    from . import fenlight_db
    from .write_policy import WriteRefused, check_writable, read_only_reason
    from .netconfig import is_loopback
    from .memstat import memory_status
except ImportError:
    from version import VERSION
    from fix_protection import protection_for_kodi
    from auth import authorized
    from adapters import adapter_for
    from addon_index import AddonIndex
    from backup import set_retention, create_backup, create_stack_backup, list_backups, restore_backup, restore_stack_backup
    from settings_schema import parse_schema, flatten_settings, parse_user_settings, setting_description
    from stack_detector import detect_stack
    from pipeline import build_pipeline, apply_pipeline_settings, pipeline_backup, switch_player, build_accounts, apply_account_settings, pretty_label
    from kodi_api import debug_paths, translate
    from validation import coerce_value, redact, mask_query_secrets
    from widget_catalog import list_sources, browse_directory, suggest_kids_rows
    from widget_filters import filter_items
    from widget_preview import row_preview
    from skin_layout import inspect_layout, preview_layout, apply_layout, request_rebuild
    from widget_cache import WidgetCache, cache_url
    from widget_rows import RowStore
    import fenlight_db
    from write_policy import WriteRefused, check_writable, read_only_reason
    from netconfig import is_loopback
    from memstat import memory_status

MAX_HANDLERS = 16
WIDGET_CACHE_DIR = "special://profile/addon_data/service.kodi.addonadmin/widget_cache"


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
    memory = memory_status()
    found = sum(1 for key in core if stack.get(key, {}).get("found") or stack.get(key, {}).get("active"))
    checks = [
        {"id": "jsonrpc", "label": "Kodi JSON-RPC", "status": "ok" if kodi.get_kodi_version() else "warning", "detail": kodi.get_kodi_version()},
        {"id": "stack", "label": "Core stack", "status": "ok" if found >= 4 else "warning", "detail": "%s/%s detected" % (found, len(core))},
        {"id": "addon_data", "label": "Addon config path", "status": "ok" if paths.get("addon_data_probe", {}).get("selected_path") else "error", "detail": paths.get("addon_data_probe", {}).get("selected_path", "")},
        {"id": "addons_path", "label": "Installed add-ons path", "status": "ok" if paths.get("addons_probe", {}).get("selected_path") else "warning", "detail": paths.get("addons_probe", {}).get("selected_path", "")},
        {"id": "write_mode", "label": "Write mode", "status": "ok" if config.get("write_enabled") else "warning", "detail": "enabled" if config.get("write_enabled") else "disabled"},
        dict({"id": "memory", "label": "Memory"}, **{k: v for k, v in memory.items() if k in ("status", "detail")}),
        {"id": "logs", "label": "Kodi log scan", "status": "error" if errors else ("warning" if warnings else "ok"), "detail": "%s errors · %s warnings in last 200 lines" % (len(errors), len(warnings))},
    ]
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
            "kodi_log_errors": len(errors),
            "kodi_log_warnings": len(warnings),
            "kodi_memory_mb": memory.get("kodi_mb"),
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


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super(ApiError, self).__init__(message)
        self.status, self.code, self.details = status, code, details


def _lock_layout(layout):
    """Read-only presentation of a layout while Write Mode is off."""
    layout["can_apply"] = False
    layout["new_section_available"] = False
    for section in layout.get("sections", []):
        section["editable"] = False
    layout["reasons"] = list(layout.get("reasons", [])) + ["Write Mode is disabled. Enable it in Kodi Manager service settings to apply this layout."]
    return layout


_ADDON = r"/api/addons/(?P<aid>[A-Za-z0-9._-]+)"

# (method, path regex, handler method, needs Write Mode, error code for ValueError)
ROUTES = [
    ("GET", r"/api/widget-cache/url", "widget_cache_url", False, "bad_request"),
    ("GET", r"/api/widget-cache/rows", "widget_rows_list", False, "bad_request"),
    ("POST", r"/api/widget-cache/rows", "widget_rows_add", True, "bad_request"),
    ("POST", r"/api/widget-cache/rows/remove", "widget_rows_remove", True, "bad_request"),
    ("GET", r"/api/widget-cache", "widget_cache_status", False, "bad_request"),
    ("POST", r"/api/widget-cache/refresh", "widget_cache_refresh", False, "bad_request"),
    ("GET", r"/api/fixes", "fixes_status", False, "bad_request"),
    ("POST", r"/api/fixes/repair", "fixes_repair", True, "bad_request"),
    ("GET", r"/api/widgets/sources", "widget_sources", False, "bad_request"),
    ("GET", r"/api/widgets/layout", "widget_layout", False, "bad_request"),
    ("POST", r"/api/widgets/browse", "widget_browse", False, "bad_request"),
    ("POST", r"/api/widgets/suggestions", "widget_suggestions", False, "bad_request"),
    ("POST", r"/api/widgets/row-preview", "widget_row_preview", False, "bad_request"),
    ("POST", r"/api/widgets/layout/preview", "widget_layout_preview", False, "bad_request"),
    ("POST", r"/api/widgets/layout/apply", "widget_layout_apply", True, "bad_request"),
    ("POST", r"/api/widgets/layout/rebuild", "widget_layout_rebuild", True, "bad_request"),
    ("GET", r"/api/status", "status", False, "bad_request"),
    ("GET", r"/api/bootstrap/status", "bootstrap_status", False, "bad_request"),
    ("GET", r"/api/stack", "stack", False, "bad_request"),
    ("GET", r"/api/health", "health", False, "bad_request"),
    ("GET", r"/api/integrations", "integrations", False, "bad_request"),
    ("GET", r"/api/accounts", "accounts", False, "bad_request"),
    ("PATCH", r"/api/accounts/settings", "accounts_patch", True, "account_write_blocked"),
    ("GET", r"/api/pipeline", "pipeline", False, "bad_request"),
    ("GET", r"/api/pipeline/debug", "pipeline_debug", False, "bad_request"),
    ("POST", r"/api/pipeline/rescan", "pipeline_rescan", False, "bad_request"),
    ("POST", r"/api/pipeline/backup", "pipeline_backup", True, "bad_request"),
    ("PATCH", r"/api/pipeline/settings", "pipeline_patch", True, "invalid_pipeline_setting"),
    ("POST", r"/api/pipeline/switch-player", "pipeline_switch_player", True, "switch_player_blocked"),
    ("POST", r"/api/playback/test", "playback_test", False, "bad_request"),
    ("GET", r"/api/debug/paths", "debug_paths", False, "bad_request"),
    ("GET", r"/api/debug/stack-raw", "debug_stack_raw", False, "bad_request"),
    ("GET", r"/api/addons", "addons", False, "bad_request"),
    ("GET", r"/api/search/config", "search_config", False, "bad_request"),
    ("GET", r"/api/logs", "logs", False, "bad_request"),
    ("GET", r"/api/kodi/logs", "kodi_logs", False, "bad_request"),
    ("POST", r"/api/addons/install", "addons_install", True, "bad_request"),
    ("POST", r"/api/stack/backup", "stack_backup", True, "bad_request"),
    ("GET", r"/api/stack/backups", "stack_backups", False, "bad_request"),
    ("GET", r"/api/backups/timeline", "backups_timeline", False, "bad_request"),
    ("POST", r"/api/stack/restore", "stack_restore", True, "bad_request"),
    ("GET", _ADDON, "addon_details", False, "bad_request"),
    ("GET", _ADDON + r"/settings", "addon_settings", False, "bad_request"),
    ("PATCH", _ADDON + r"/settings", "addon_settings_patch", True, "bad_request"),
    ("POST", _ADDON + r"/open-settings", "addon_open_settings", True, "bad_request"),
    ("POST", _ADDON + r"/backup", "addon_backup", True, "bad_request"),
    ("GET", _ADDON + r"/backups", "addon_backups", False, "bad_request"),
    ("POST", _ADDON + r"/restore", "addon_restore", True, "bad_request"),
    ("POST", r"/api/windows/open-skin-settings", "open_skin_settings", True, "bad_request"),
    ("POST", r"/api/trakt/sync", "trakt_sync", True, "bad_request"),
]
ROUTE_TABLE = [(method, re.compile(pattern + r"\Z"), name, needs_write, value_code)
               for method, pattern, name, needs_write, value_code in ROUTES]


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KodiManager/" + VERSION
        timeout = 20

        def log_message(self, fmt, *args):
            # The request line can carry ?token=...: mask query secrets before logging.
            state.log(mask_query_secrets(fmt % args))

        # --- responses -------------------------------------------------------

        def _send(self, status, data, content_type="application/json"):
            body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def ok(self, data=None):
            self._send(200, {"ok": True, "data": data if data is not None else {}})

        def err(self, status, code, message, details=None):
            self._send(status, {"ok": False, "code": code,
                                "error": {"code": code, "message": str(redact(message)), "details": redact(details or {})}})

        # --- request checks ----------------------------------------------------

        def _target(self):
            """The request path, or None after answering 400 for a non-origin-form target."""
            raw = self.path
            if not raw.startswith("/") or raw.startswith("//"):
                self.err(400, "bad_request", "Request target must be a plain path")
                return None
            parts = urlsplit(raw)
            if parts.scheme or parts.netloc or parts.fragment:
                self.err(400, "bad_request", "Request target must be a plain path")
                return None
            path = parts.path
            decoded = unquote(path)
            segments = decoded.split("/")[1:]
            if "//" in path or "\\" in decoded or any(seg in (".", "..") for seg in segments) or "\x00" in decoded:
                self.err(400, "bad_request", "Request path is not normalised")
                return None
            return path

        def _client_allowed(self):
            if is_loopback(state.config.get("host")):
                return True
            if _private_client(self.client_address[0]):
                return True
            self.err(403, "forbidden", "Non-private client rejected")
            return False

        def _origin_allowed(self):
            """Browsers send Origin on cross-site writes; the dashboard itself is same-origin."""
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            host = (self.headers.get("Host") or "").strip().lower()
            try:
                parsed = urlsplit(origin.strip())
                origin_host = parsed.netloc.lower() if parsed.scheme in ("http", "https") else ""
            except ValueError:
                origin_host = ""
            if origin_host and host and origin_host == host:
                return True
            self.err(403, "origin_mismatch", "Cross-origin request rejected")
            return False

        def _auth(self, path):
            if path == "/api/bootstrap/status" and self._bootstrap_allowed():
                return True
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

        # --- dispatch ----------------------------------------------------------

        def do_OPTIONS(self):
            # Same-origin dashboard: no CORS grant for other origins.
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PATCH(self):
            self._dispatch("PATCH")

        def _dispatch(self, method):
            self._body = None
            path = self._target()
            if path is None or not self._client_allowed():
                return
            is_api = path == "/api" or path.startswith("/api/")
            if not is_api:
                if method != "GET":
                    self.err(404, "not_found", "Route not found")
                    return
                try:
                    self.static(path)
                except Exception as exc:
                    self.err(500, "server_error", str(exc))
                return
            if method != "GET" and not self._origin_allowed():
                return
            if not self._auth(path):
                return
            self.route_api(method, path)

        def route_api(self, method, path):
            found = None
            for route_method, pattern, name, needs_write, value_code in ROUTE_TABLE:
                if route_method != method:
                    continue
                match = pattern.match(path)
                if match:
                    found = (match, name, needs_write, value_code)
                    break
            if found is None:
                self.err(404, "not_found", "Route not found")
                return
            match, name, needs_write, value_code = found
            try:
                if needs_write and not state.config.get("write_enabled"):
                    raise PermissionError("Write Mode is disabled")
                result = getattr(self, "api_" + name.replace("-", "_"))(**match.groupdict())
                self.ok(result)
            except ApiError as exc:
                self.err(exc.status, exc.code, str(exc), exc.details)
            except WriteRefused as exc:
                self.err(403, exc.code, str(exc))
            except PermissionError as exc:
                self.err(403, "write_disabled", str(exc))
            except ValueError as exc:
                self.err(400, value_code, str(exc))
            except (LookupError, FileNotFoundError) as exc:
                self.err(404, "not_found", exc.args[0] if exc.args and isinstance(exc.args[0], str) else "Not found")
            except Exception as exc:
                self.err(500, "server_error", str(exc))

        def static(self, path):
            path = unquote(path)
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

        # --- helpers -----------------------------------------------------------

        def body(self):
            """The JSON request body as a dict ({} when empty); anything else is a 400."""
            if self._body is not None:
                return self._body
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                raise ValueError("Invalid Content-Length") from None
            if length < 0 or length > 1000000 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Request body must be at most 1 MB with a fixed length")
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            self._body = data
            return data

        def query(self, name, default=""):
            return (parse_qs(urlsplit(self.path).query).get(name) or [default])[0]

        def _require_idle(self, message, status=400):
            players = state.kodi.jsonrpc("Player.GetActivePlayers")
            if not isinstance(players, dict) or "error" in players or players.get("result") != []:
                # Code playback_active. Restores answer 409 because {"force": true} overrides them;
                # actions that cannot be forced keep their historic 400.
                raise ApiError(status, "playback_active", message)

        def _require_idle_unless_forced(self, message):
            force = self.body().get("force", False)
            if not isinstance(force, bool):
                raise ValueError("force must be boolean")
            if not force:
                self._require_idle(message, status=409)

        def _addon(self, aid):
            state.index.refresh()
            addon = state.index.get(aid)
            if not addon:
                raise LookupError("Add-on not found")
            return addon

        def _rows(self):
            return RowStore(translate(WIDGET_CACHE_DIR))

        # --- widget cache --------------------------------------------------------

        def api_widget_cache_url(self):
            pages = self.query("pages")
            return {"url": cache_url(self.query("source"), pages=int(pages) if pages.isdigit() else None,
                                     hide_watched=self.query("hide_watched") == "true")}

        def api_widget_rows_list(self):
            return self._rows().listing()

        def api_widget_rows_add(self):
            body = self.body()
            pages = body.get("pages")
            return self._rows().add(body.get("label", ""), body.get("source", ""),
                                    pages=int(pages) if str(pages or "").isdigit() else None,
                                    hide_watched=bool(body.get("hide_watched")))

        def api_widget_rows_remove(self):
            self._rows().remove(str(self.body().get("id", "")))
            return {"removed": True}

        def api_widget_cache_status(self):
            return WidgetCache(translate(WIDGET_CACHE_DIR)).status()

        def api_widget_cache_refresh(self):
            return {"queued": WidgetCache(translate(WIDGET_CACHE_DIR)).queue_stale(everything=True)}

        # --- fixes ---------------------------------------------------------------

        def api_fixes_status(self):
            return protection_for_kodi().status()

        def api_fixes_repair(self):
            self._require_idle("Stop playback before restoring fixes")
            return protection_for_kodi().repair()

        # --- widgets and layout --------------------------------------------------

        def api_widget_sources(self):
            state.index.refresh()
            return list_sources(state.kodi, state.index)

        def api_widget_layout(self):
            state.index.refresh()
            layout = inspect_layout(state.kodi, state.index)
            return layout if state.config.get("write_enabled") else _lock_layout(layout)

        def api_widget_browse(self):
            body = self.body()
            if not isinstance(body.get("family_preview", False), bool):
                raise ValueError("family_preview must be boolean")
            state.index.refresh()
            result = browse_directory(state.kodi, state.index, body.get("path", ""), body.get("start", 0), body.get("limit", 48), refresh=body.get("refresh", False))
            if body.get("family_preview"):
                result["family_preview"] = filter_items([dict(item, file=item["path"]) for item in result["items"]], body.get("max_rating", "12A"), True)
            return result

        def api_widget_suggestions(self):
            self.body()
            state.index.refresh()
            return suggest_kids_rows(state.kodi, state.index)

        def api_widget_row_preview(self):
            body = self.body()
            state.index.refresh()
            return row_preview(state.kodi, state.index, body)

        def api_widget_layout_preview(self):
            body = self.body()
            state.index.refresh()
            layout = preview_layout(state.kodi, state.index, body)
            return layout if state.config.get("write_enabled") else _lock_layout(layout)

        def api_widget_layout_apply(self):
            body = self.body()
            state.index.refresh()
            return apply_layout(state.kodi, state.index, body, True)

        def api_widget_layout_rebuild(self):
            self.body()
            state.index.refresh()
            # Rebuilding reloads the skin, which interrupts whoever is watching.
            self._require_idle("Stop playback before rebuilding the TV menu")
            return request_rebuild(state.kodi, state.index)

        # --- status, stack, accounts, pipeline -----------------------------------

        def api_status(self):
            state.index.refresh()
            return {
                "service_version": VERSION,
                "Kodi version": state.kodi.get_kodi_version(),
                "server": {"host": state.config.get("host"), "port": state.config.get("port")},
                "write_enabled": state.config.get("write_enabled"),
                "allow_lan": state.config.get("allow_lan"),
                "active_skin": state.kodi.get_active_skin(),
                "current_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "platform": platform.platform(),
                "stack": detect_stack(state.kodi, state.index),
            }

        def api_bootstrap_status(self):
            seed = state.config.get("installer_seed", {})
            return {"installed": True, "web_url": "http://%s:%s" % (seed.get("kodi_ip_hint", "127.0.0.1"), state.config.get("port")), "needs_auth": True, "nonce_present": bool(seed.get("installer_nonce"))}

        def api_stack(self):
            state.index.refresh()
            return detect_stack(state.kodi, state.index)

        def api_health(self):
            return health_summary(state.kodi, state.index, state.config)

        def api_integrations(self):
            state.index.refresh()
            return integration_status(state.index)

        def api_accounts(self):
            state.index.refresh()
            return build_accounts(state.kodi, state.index)

        def api_accounts_patch(self):
            changes = self.body().get("changes", [])
            state.index.refresh()
            return apply_account_settings(state.kodi, state.index, changes, state.config.get("write_enabled"),
                                          state.kodi.get_kodi_version(), config=state.config)

        def api_pipeline(self):
            state.index.refresh()
            return build_pipeline(state.kodi, state.index)

        def api_pipeline_debug(self):
            state.index.refresh()
            pipe = build_pipeline(state.kodi, state.index)
            return {"pipeline": pipe, "paths": debug_paths(state.config.get("installer_seed", {})), "stack_raw": {"merged_records": state.index.addons, "classified_stack": detect_stack(state.kodi, state.index)}}

        def api_pipeline_rescan(self):
            try:
                state.index.refresh(force=True)  # An explicit rescan skips the refresh rate limit.
            except TypeError:
                state.index.refresh()
            return build_pipeline(state.kodi, state.index)

        def api_pipeline_backup(self):
            state.index.refresh()
            pipe = build_pipeline(state.kodi, state.index)
            return pipeline_backup(state.index, state.kodi.get_kodi_version(), pipe)

        def api_pipeline_patch(self):
            changes = self.body().get("changes", [])
            state.index.refresh()
            return apply_pipeline_settings(state.kodi, state.index, changes, state.config.get("write_enabled"),
                                           state.kodi.get_kodi_version(), config=state.config)

        def api_pipeline_switch_player(self):
            body = self.body()
            state.index.refresh()
            return switch_player(state.kodi, state.index, body.get("target_player_addon_id", ""), body.get("apply_to"), body.get("keep_current_as_fallback", True), state.config.get("write_enabled"), state.kodi.get_kodi_version())

        def api_playback_test(self):
            return playback_test(state.kodi, state.index, self.body())

        # --- debug and logs --------------------------------------------------------

        def api_debug_paths(self):
            return dict({"kodi_version": state.kodi.get_kodi_version(), "platform": platform.platform()}, **debug_paths(state.config.get("installer_seed", {})))

        def api_debug_stack_raw(self):
            state.index.refresh()
            listed = state.kodi.list_addons()
            return {
                "jsonrpc_addons_count": len(listed),
                "jsonrpc_ids": sorted([a.get("addon_id") for a in listed if a.get("addon_id")]),
                "addon_data_ids": state.index.probe.get("addon_data_probe", {}).get("selected_dirs", []),
                "installed_addon_ids": state.index.probe.get("addons_probe", {}).get("selected_dirs", []),
                "probe": state.index.probe,
                "merged_records": state.index.addons,
                "classified_stack": detect_stack(state.kodi, state.index),
            }

        def api_addons(self):
            state.index.refresh()
            return state.index.list()

        def api_search_config(self):
            state.index.refresh()
            q = self.query("q").lower().strip()
            if not q:
                return {"query": q, "results": []}
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
                            return {"query": q, "count": len(results), "results": results}
            return {"query": q, "count": len(results), "results": results}

        def api_logs(self):
            return {"lines": state.logs[-200:]}

        def api_kodi_logs(self):
            return {"lines": state.kodi.get_log_lines(500)}

        # --- install, backups, restores --------------------------------------------

        def api_addons_install(self):
            self.body()
            self._require_idle("Stop playback before opening Install from zip on the TV")
            return state.kodi.open_install_from_zip()

        def api_stack_backup(self):
            stack = detect_stack(state.kodi, state.index)
            ids = [stack[k].get("addon_id") for k in ("tmdbhelper", "fenlight", "fen", "pov", "cocoscrapers", "trakt")]
            ids.append(stack["skin"].get("addon_id"))
            ids += ["script.skinshortcuts", "shortcutmanager", "script.skin.helper.service", "script.skin.helper.widgets", "plugin.program.openwizard"]
            addons = [state.index.get(aid) for aid in ids if aid]
            return create_stack_backup(addons, state.kodi.get_kodi_version())

        def api_stack_backups(self):
            return {"backups": list_backups(stack=True)}

        def api_backups_timeline(self):
            return backup_timeline()

        def api_stack_restore(self):
            backup_id = self.body().get("backup_id", "")
            self._require_idle_unless_forced("Stop playback before restoring a backup")
            return restore_stack_backup(state.index, backup_id)

        # --- one add-on ----------------------------------------------------------------

        def api_addon_details(self, aid):
            addon = self._addon(aid)
            adapter = adapter_for(addon, state.kodi, state.index.addons)
            details = dict(addon)
            details["warnings"] = adapter.get_warnings(addon)
            details["related"] = adapter.extra_details(addon)
            return details

        def api_addon_settings(self, aid):
            addon = self._addon(aid)
            adapter = adapter_for(addon, state.kodi, state.index.addons)
            parsed = settings_for_addon(addon)
            reason = read_only_reason(aid, addon, state.config)
            parsed.update({"addon_id": aid, "name": addon.get("name"), "adapter": adapter.name,
                           "warnings": parsed.get("warnings", []) + adapter.get_warnings(addon),
                           "editable": reason is None, "read_only_reason": reason})
            return parsed

        def api_addon_settings_patch(self, aid):
            addon = self._addon(aid)
            check_writable(aid, addon, state.config)
            adapter = adapter_for(addon, state.kodi, state.index.addons)
            changes = self.body().get("changes", [])
            if not isinstance(changes, list):
                raise ValueError("changes must be a list")
            settings = flatten_settings(parse_schema(addon.get("settings_schema_path"), addon.get("path"), addon.get("user_settings_path"), True))
            clean, db_pairs = [], []
            for ch in changes:
                if not isinstance(ch, dict):
                    raise ValueError("Each change must be an object")
                sid = ch.get("id")
                if aid == fenlight_db.FENLIGHT_ID and ch.get("source") == "settings.db":
                    db_pairs.append((sid, ch.get("value")))
                    continue
                if ch.get("source") == "raw":
                    if sid not in parse_user_settings(addon.get("user_settings_path")):
                        raise ValueError("Unknown raw setting: %s" % sid)
                    if isinstance(ch.get("value"), (dict, list)):
                        raise ValueError("Expected a single value: %s" % sid)
                    clean.append({"id": sid, "value": str(ch.get("value")), "source": "raw"})
                    continue
                if sid not in settings:
                    raise ValueError("Unknown setting: %s" % sid)
                setting = settings[sid]
                if not setting.get("editable"):
                    raise ValueError("Setting not editable: %s" % sid)
                clean.append({"id": sid, "value": coerce_value(setting, ch.get("value"))})
            # The whole batch is validated (including settings.db types) before anything is written.
            db_clean = fenlight_db.validate_changes(addon, db_pairs) if db_pairs else []
            backup = create_backup(addon, state.kodi.get_kodi_version(), adapter.name)
            for ch in clean:
                state.kodi.set_addon_setting(aid, ch["id"], ch["value"])
            fenlight_db.write_changes(addon, db_clean)
            clean += [{"id": sid, "value": value, "source": "settings.db"} for sid, value in db_clean]
            return {"changed_count": len(clean), "backup_id": backup["backup_id"], "warnings": adapter.after_write(aid, clean)}

        def api_addon_open_settings(self, aid):
            self._addon(aid)
            return {"opened": state.kodi.open_addon_settings(aid)}

        def api_addon_backup(self, aid):
            addon = self._addon(aid)
            adapter = adapter_for(addon, state.kodi, state.index.addons)
            return create_backup(addon, state.kodi.get_kodi_version(), adapter.name)

        def api_addon_backups(self, aid):
            self._addon(aid)
            return {"backups": list_backups(aid)}

        def api_addon_restore(self, aid):
            addon = self._addon(aid)
            backup_id = self.body().get("backup_id", "")
            self._require_idle_unless_forced("Stop playback before restoring a backup")
            return restore_backup(addon, backup_id)

        # --- Kodi windows --------------------------------------------------------------

        def api_open_skin_settings(self):
            return {"opened": state.kodi.open_skin_settings()}

        def api_trakt_sync(self):
            addon = state.index.get("script.trakt")
            if not addon or not addon.get("enabled"):
                raise ApiError(404, "trakt_unavailable", "script.trakt not installed/enabled")
            return state.kodi.execute_addon("script.trakt", {"action": "sync"})

    return Handler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Daemon handler threads, at most MAX_HANDLERS at once.

    When every slot stays busy the connection is closed instead of queueing an
    unbounded number of threads that each wait on Kodi.
    """
    daemon_threads = True
    max_handlers = MAX_HANDLERS
    slot_wait = 5.0

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(self.max_handlers)
        ThreadingHTTPServer.__init__(self, *args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(timeout=self.slot_wait):
            self.shutdown_request(request)
            return
        try:
            ThreadingHTTPServer.process_request(self, request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            ThreadingHTTPServer.process_request_thread(self, request, client_address)
        finally:
            self._slots.release()


class ServerThread(threading.Thread):
    def __init__(self, kodi, config, web_root):
        super(ServerThread, self).__init__()
        self.daemon = True
        self.stopping = threading.Event()
        self.state = AdminState(kodi, config, web_root)
        set_retention(config.get("backup_retention", 20))
        self.httpd = BoundedThreadingHTTPServer((config["host"], int(config["port"])), make_handler(self.state))
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

    def update_config(self, config):
        """Swap settings that need no new socket (write mode, retention, widget cache) live."""
        self.state.config = config
        set_retention(config.get("backup_retention", 20))

    def stop(self):
        # Profile changes stop scripts while Kodi's UI thread is unavailable.
        # Never wait on a server thread that might be blocked in a Kodi call.
        self.stopping.set()
        self.httpd.server_close()
