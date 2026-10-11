"""The dashboard server: the API route table, the request handler built from it and the server thread.

The pieces live in their own modules: ``http_base`` (request checks, envelope, bounded server),
``api_status``, ``api_addons`` and ``api_widgets`` (the handlers by area) and ``dashboard_data``
(what they compute). Names that used to be defined here are re-exported for scripts and tests.
"""
import re
import threading
import time  # noqa: F401  (re-exported: tests patch server.time)
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler  # noqa: F401

try:
    from .version import VERSION  # noqa: F401
    from .backup import BackupAborted, set_retention  # noqa: F401
    from .kodi_api import translate  # noqa: F401
    from .netconfig import is_loopback  # noqa: F401
    from .metrics import HISTORY_FILE  # noqa: F401
    from .http_base import (  # noqa: F401
        HEADER_DEADLINE, MAX_HANDLERS, MAX_HANDLERS_PER_CLIENT, AdminState, ApiError, BoundedThreadingHTTPServer,
        RequestHandler, _private_client)
    from .dashboard_data import (  # noqa: F401
        SHORTCUTS_DATA, STACK_EXTRA_IDS, WIDGET_CACHE_DIR, backup_timeline, current_profile, health_summary,
        integration_status, maintenance_checks, make_baseline, overview_summary, playback_state, playback_test,
        settings_for_addon, stack_backup_addons, with_row_titles)
    from .api_addons import AddonRoutes
    from .api_status import StatusRoutes
    from .api_widgets import WidgetRoutes, _lock_layout  # noqa: F401
except ImportError:
    from version import VERSION  # noqa: F401
    from backup import BackupAborted, set_retention  # noqa: F401
    from kodi_api import translate  # noqa: F401
    from netconfig import is_loopback  # noqa: F401
    from metrics import HISTORY_FILE  # noqa: F401
    from http_base import (  # noqa: F401
        HEADER_DEADLINE, MAX_HANDLERS, MAX_HANDLERS_PER_CLIENT, AdminState, ApiError, BoundedThreadingHTTPServer,
        RequestHandler, _private_client)
    from dashboard_data import (  # noqa: F401
        SHORTCUTS_DATA, STACK_EXTRA_IDS, WIDGET_CACHE_DIR, backup_timeline, current_profile, health_summary,
        integration_status, maintenance_checks, make_baseline, overview_summary, playback_state, playback_test,
        settings_for_addon, stack_backup_addons, with_row_titles)
    from api_addons import AddonRoutes
    from api_status import StatusRoutes
    from api_widgets import WidgetRoutes, _lock_layout  # noqa: F401


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
    ("GET", r"/api/overview", "overview", False, "bad_request"),
    ("GET", r"/api/metrics/history", "metrics_history", False, "bad_request"),
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
    ("GET", r"/api/baseline", "baseline", False, "bad_request"),
    ("POST", r"/api/baseline/apply", "baseline_apply", True, "bad_request"),
    ("POST", r"/api/baseline/capture", "baseline_capture", True, "bad_request"),
    ("POST", r"/api/baseline/remove", "baseline_remove", True, "bad_request"),
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
    """A request handler class for ``state`` (an AdminState) answering ROUTES."""
    class Handler(StatusRoutes, AddonRoutes, WidgetRoutes):
        pass
    Handler.state = state
    Handler.route_table = tuple(ROUTE_TABLE)
    return Handler


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
        # Close the listening socket only. The server loop closes its own
        # request state; service shutdown never joins HTTP handlers here.
        self.httpd.socket.close()
