"""API handlers for what the TV is doing: status, overview, history, Health, accounts, playback setup,
diagnostics, logs and the Kodi windows the dashboard can open.
"""
import platform
import time

try:
    from .http_base import ApiError, RequestHandler
    from .version import VERSION
    from .dashboard_data import health_summary, integration_status, overview_summary, playback_test
    from .stack_detector import detect_stack
    from .pipeline import build_pipeline, apply_pipeline_settings, pipeline_backup, switch_player, build_accounts, apply_account_settings
    from .kodi_api import debug_paths, translate
    from .validation import redact
    from .metrics import HISTORY_FILE, MetricsHistory
except ImportError:
    from http_base import ApiError, RequestHandler
    from version import VERSION
    from dashboard_data import health_summary, integration_status, overview_summary, playback_test
    from stack_detector import detect_stack
    from pipeline import build_pipeline, apply_pipeline_settings, pipeline_backup, switch_player, build_accounts, apply_account_settings
    from kodi_api import debug_paths, translate
    from validation import redact
    from metrics import HISTORY_FILE, MetricsHistory


class StatusRoutes(RequestHandler):
    """Status, overview, metrics, stack, Health, accounts, pipeline, debug, logs, Kodi windows and Trakt."""

    # --- status, stack, accounts, pipeline -----------------------------------

    def api_status(self):
        self.state.index.refresh()
        return {
            "service_version": VERSION,
            "Kodi version": self.state.kodi.get_kodi_version(),
            "server": {"host": self.state.config.get("host"), "port": self.state.config.get("port")},
            "write_enabled": self.state.config.get("write_enabled"),
            "allow_lan": self.state.config.get("allow_lan"),
            "active_skin": self.state.kodi.get_active_skin(),
            "current_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform": platform.platform(),
            "stack": detect_stack(self.state.kodi, self.state.index),
        }

    def api_overview(self):
        return overview_summary(self.state.kodi, self.state.config)

    def api_metrics_history(self):
        return MetricsHistory(translate(HISTORY_FILE)).series(self.query("days", "7") or "7", now=time.time())

    def api_bootstrap_status(self):
        seed = self.state.config.get("installer_seed", {})
        return {"installed": True, "web_url": "http://%s:%s" % (seed.get("kodi_ip_hint", "127.0.0.1"), self.state.config.get("port")), "needs_auth": True, "nonce_present": bool(seed.get("installer_nonce"))}

    def api_stack(self):
        self.state.index.refresh()
        return detect_stack(self.state.kodi, self.state.index)

    def api_health(self):
        return health_summary(self.state.kodi, self.state.index, self.state.config)

    def api_integrations(self):
        self.state.index.refresh()
        return integration_status(self.state.index)

    def api_accounts(self):
        self.state.index.refresh()
        return build_accounts(self.state.kodi, self.state.index)

    def api_accounts_patch(self):
        changes = self.body().get("changes", [])
        self.state.index.refresh()
        return apply_account_settings(self.state.kodi, self.state.index, changes, self.state.config.get("write_enabled"),
                                      self.state.kodi.get_kodi_version(), config=self.state.config)

    def api_pipeline(self):
        self.state.index.refresh()
        return build_pipeline(self.state.kodi, self.state.index)

    def api_pipeline_debug(self):
        self.state.index.refresh()
        pipe = build_pipeline(self.state.kodi, self.state.index)
        return {"pipeline": pipe, "paths": debug_paths(self.state.config.get("installer_seed", {})), "stack_raw": {"merged_records": self.state.index.addons, "classified_stack": detect_stack(self.state.kodi, self.state.index)}}

    def api_pipeline_rescan(self):
        try:
            self.state.index.refresh(force=True)  # An explicit rescan skips the refresh rate limit.
        except TypeError:
            self.state.index.refresh()
        return build_pipeline(self.state.kodi, self.state.index)

    def api_pipeline_backup(self):
        self.state.index.refresh()
        pipe = build_pipeline(self.state.kodi, self.state.index)
        return pipeline_backup(self.state.index, self.state.kodi.get_kodi_version(), pipe)

    def api_pipeline_patch(self):
        changes = self.body().get("changes", [])
        self.state.index.refresh()
        return apply_pipeline_settings(self.state.kodi, self.state.index, changes, self.state.config.get("write_enabled"),
                                       self.state.kodi.get_kodi_version(), config=self.state.config)

    def api_pipeline_switch_player(self):
        body = self.body()
        self.state.index.refresh()
        return switch_player(self.state.kodi, self.state.index, body.get("target_player_addon_id", ""), body.get("apply_to"), body.get("keep_current_as_fallback", True), self.state.config.get("write_enabled"), self.state.kodi.get_kodi_version())

    def api_playback_test(self):
        return playback_test(self.state.kodi, self.state.index, self.body())

    # --- debug and logs --------------------------------------------------------

    def api_debug_paths(self):
        return dict({"kodi_version": self.state.kodi.get_kodi_version(), "platform": platform.platform()}, **debug_paths(self.state.config.get("installer_seed", {})))

    def api_debug_stack_raw(self):
        self.state.index.refresh()
        listed = self.state.kodi.list_addons()
        return {
            "jsonrpc_addons_count": len(listed),
            "jsonrpc_ids": sorted([a.get("addon_id") for a in listed if a.get("addon_id")]),
            "addon_data_ids": self.state.index.probe.get("addon_data_probe", {}).get("selected_dirs", []),
            "installed_addon_ids": self.state.index.probe.get("addons_probe", {}).get("selected_dirs", []),
            "probe": self.state.index.probe,
            "merged_records": self.state.index.addons,
            "classified_stack": detect_stack(self.state.kodi, self.state.index),
        }

    def api_logs(self):
        return {"lines": self.state.logs[-200:]}

    def api_kodi_logs(self):
        return {"lines": redact(self.state.kodi.get_log_lines(500))}

    # --- Kodi windows --------------------------------------------------------------

    def api_open_skin_settings(self):
        self._require_idle("Stop playback before opening skin settings on the TV")
        return {"opened": self.state.kodi.open_skin_settings()}

    def api_trakt_sync(self):
        addon = self.state.index.get("script.trakt")
        if not addon or not addon.get("enabled"):
            raise ApiError(404, "trakt_unavailable", "script.trakt not installed/enabled")
        # A full sync shows progress dialogs and competes with playback for the network.
        self._require_idle("Stop playback before syncing Trakt")
        return self.state.kodi.execute_addon("script.trakt", {"action": "sync"})
