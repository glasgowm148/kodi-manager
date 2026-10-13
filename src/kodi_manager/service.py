"""Kodi Manager's service: starts the dashboard, the background work and the private extension,
reacts to settings changes and Kodi notifications, and stops everything when Kodi asks.

Settings are read in service_config.py; the background threads live in service_workers.py.
"""
import json
import os
import time

try:
    import xbmc
except ImportError:
    xbmc = None

try:
    from . import extension, profile_transition
    from .kodi_api import KodiAPI, service_addon, translate
    from .server import ServerThread
    from .shield_exit import ShieldExitGuard, process_start, supported_build
    # Re-exported: these lived here before the service was split up.
    from .service_config import BOOL_KEYS, NETWORK_KEYS, _bool, load_config, write_private_file  # noqa: F401
    from .service_workers import (  # noqa: F401
        BUSY_CONDITION, EXTERNAL_RELOAD_PROPERTIES, WIDGET_FAILURES_PROPERTY, WidgetHealth, external_reload_token,
        persistent_widget_failures, start_log_collector, start_maintenance, start_sampler, start_watchdog, start_widget_refresher, tv_busy)
except ImportError:
    import extension
    import profile_transition
    from kodi_api import KodiAPI, service_addon, translate
    from server import ServerThread
    from shield_exit import ShieldExitGuard, process_start, supported_build
    from service_config import BOOL_KEYS, NETWORK_KEYS, _bool, load_config, write_private_file  # noqa: F401
    from service_workers import (  # noqa: F401
        BUSY_CONDITION, EXTERNAL_RELOAD_PROPERTIES, WIDGET_FAILURES_PROPERTY, WidgetHealth, external_reload_token,
        persistent_widget_failures, start_log_collector, start_maintenance, start_sampler, start_watchdog, start_widget_refresher, tv_busy)


def media_playing():
    """True while Kodi has media loaded; False outside Kodi."""
    if not xbmc:
        return False
    try:
        return bool(xbmc.getCondVisibility("Player.HasMedia"))
    except Exception:
        return False


# Shared by every profile (special://temp): which Kodi process and profile ran
# the service last, so the dashboard address is announced once per Kodi session.
SESSION_STATE = "special://temp/kodi-manager-session.json"
# A start in another profile this soon after the service stopped is a profile switch
# (some setups switch profiles by restarting Kodi).
PROFILE_SWITCH_WINDOW = 120


def process_identity():
    """This Kodi process: PID plus its start time, so a reused PID is a new session."""
    pid = os.getpid()
    try:
        return "%d:%s" % (pid, process_start(pid))
    except Exception:
        return str(pid)


def read_session(path):
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_session(path, record):
    try:
        try:
            from .fsutil import atomic_write_bytes
        except ImportError:
            from fsutil import atomic_write_bytes
        atomic_write_bytes(path, json.dumps(record).encode("utf-8"), fsync=False)
    except Exception:
        pass


def announce_due(previous, process, profile, now):
    """Show the dashboard address on this start? Once per Kodi session, never on a profile switch.

    Not when the service already ran in this Kodi process (profile switches and
    add-on updates restart the service), and not when Kodi was restarted into
    another profile moments after the service stopped (a restart-based switch).
    """
    if previous.get("process") == process:
        return False
    stopped = previous.get("stopped_at")
    if (previous.get("profile") not in (None, profile) and isinstance(stopped, (int, float))
            and 0 <= now - stopped < PROFILE_SWITCH_WINDOW):
        return False
    return True


def dashboard_address(config, lan_ip=None):
    """The address to open: the TV's LAN address when listening on every interface, else the bound one."""
    host = str(config.get("host") or "127.0.0.1")
    if host in ("0.0.0.0", "::"):
        try:
            host = str((lan_ip() if callable(lan_ip) else lan_ip) or "127.0.0.1")
        except Exception:
            host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    return "http://%s:%s" % (host, config.get("port"))


def lan_address():
    """This TV's LAN IPv4 address, or "" (a short wait while Kodi looks it up)."""
    if not xbmc:
        return ""
    try:
        from .widget_rows import local_ip
    except ImportError:
        from widget_rows import local_ip
    return local_ip(xbmc, attempts=10)


def start_server(kodi, config, web_root, server_class=None, announce=False, lan_ip=None):
    """Start the dashboard server; on failure (port in use, bad address) log, notify and return None.

    ``announce`` shows the dashboard address (the TV's LAN address, not
    0.0.0.0) on the TV, unless something is playing: Kodi restarts this
    service when the add-on updates, which can happen in the middle of a film.
    """
    server_class = server_class or ServerThread
    try:
        server = server_class(kodi, config, web_root)
        server.start()
    except Exception as error:
        message = "Dashboard could not start on %s:%s (%s)" % (config.get("host"), config.get("port"), error)
        kodi.log(message)
        try:
            kodi.notify("Kodi Manager", "Dashboard unavailable: port %s could not be opened" % config.get("port"))
        except Exception:
            pass
        return None
    kodi.log("Kodi Manager URL http://%s:%s token configured=%s" % (config["host"], config["port"], bool(config.get("auth_token"))))
    if announce and not media_playing():
        kodi.notify("Kodi Manager", dashboard_address(config, lan_ip))
    return server


def apply_settings_change(kodi, server, old_config, new_config, web_root, server_class=None):
    """Settings were saved in Kodi. Returns the server that is now running (or None).

    A changed host, port or LAN switch restarts the server on the new socket;
    anything else (Write Mode, retention, allowed add-ons, widget cache
    options) is swapped into the running server without a restart.
    """
    if server is not None and all(old_config.get(k) == new_config.get(k) for k in NETWORK_KEYS):
        server.update_config(new_config)
        return server
    if server is not None:
        server.stop()
    kodi.log("Network settings changed: restarting the dashboard on %s:%s" % (new_config.get("host"), new_config.get("port")))
    return start_server(kodi, new_config, web_root, server_class)


def start_extension(kodi, monitor):
    """Start the optional private extension (extension.py) inside Kodi; returns it or None.

    Public builds have none, so this does nothing there. Its failures are
    logged by type only and never stop the service.
    """
    if not xbmc or monitor is None:
        return None
    private = extension.module()
    if extension.error:
        kodi.log("Private extension unavailable: %s" % extension.error)
    if private is None or monitor.abortRequested():
        return None
    start = getattr(private, "start", None)
    if callable(start):
        try:
            start(monitor, kodi.log)
        except Exception as error:
            kodi.log("Private extension start failed: %s" % type(error).__name__)
    return private


def stop_extension(kodi, private):
    stop = getattr(private, "stop", None) if private is not None else None
    if callable(stop):
        try:
            stop()
        except Exception as error:
            kodi.log("Private extension stop failed: %s" % type(error).__name__)


def retire_runtime(server=None, refresher=None, watchdog=None, log_collector=None):
    """Stop new work before extension shutdown can block on in-flight workers."""
    for stop in (log_collector, getattr(refresher, 'stop', None), getattr(watchdog, 'stop', None)):
        if stop is not None:
            stop.set()
    if server is not None:
        server.stop()


def shield_exit_supported(config):
    """This opt-in workaround is specific to reviewed NVIDIA builds, not Android generally."""
    return bool(xbmc and config['shield_exit_workaround']
                and xbmc.getCondVisibility('System.Platform.Android')
                and supported_build(xbmc.getInfoLabel('System.BuildVersion'))
                and os.path.isfile('/vendor/lib64/libnvglsi.so'))


def wait_for_shutdown(monitor, startup_monitor=None):
    """Keep the original abort signal if shutdown began during service startup.

    Kodi notifies each registered Monitor separately. A callback monitor created
    after that notification can still report False while the startup monitor
    already reports True.
    """
    while True:
        if ((startup_monitor is not None and startup_monitor.abortRequested())
                or (monitor is not None and monitor.abortRequested())):
            return
        if monitor is not None:
            monitor.waitForAbort(1)
        else:
            time.sleep(1)


def main():
    # A coordinated profile switch may already be cancelling this generation.
    startup_monitor = profile_transition.Monitor() if xbmc else None
    if startup_monitor is not None and startup_monitor.abortRequested():
        return
    addon = service_addon()
    kodi = KodiAPI()
    if not addon:
        return
    config = load_config(addon)
    kodi.installer_seed = config.get("installer_seed", {})
    try:
        kodi.log("Paths home=%s profile=%s addon_data=%s" % (translate("special://home/"), translate("special://profile/"), translate("special://profile/addon_data/")))
    except Exception:
        pass
    if not config["enabled"]:
        kodi.log("Service disabled")
        return
    if startup_monitor is not None and startup_monitor.abortRequested():
        return
    root = os.path.abspath(addon.getAddonInfo("path"))
    web_root = os.path.join(root, "resources", "web")
    session_path = translate(SESSION_STATE)
    session = {"process": process_identity(), "profile": translate("special://profile/")}
    announce = announce_due(read_session(session_path), session["process"], session["profile"], time.time())
    running = {"server": start_server(kodi, config, web_root, announce=announce, lan_ip=lan_address),
               "config": config}
    write_session(session_path, dict(session, started_at=time.time()))
    supported = shield_exit_supported(config)
    guard = ShieldExitGuard(supported, translate('special://logpath/kodi.log'),
                            os.path.join(os.path.dirname(__file__), 'shield_exit_guard.sh'),
                            translate('special://temp/shield-exit-result.json'))
    kodi.log('Shield exit workaround active=%s' % supported)
    try:
        previous_exit = guard.previous_report()
        if previous_exit:
            kodi.log('Previous Shield exit guard: %s' % previous_exit)
    except Exception as error:
        kodi.log('Shield exit guard report unavailable: %s' % type(error).__name__)
    private = start_extension(kodi, startup_monitor)
    if config.get("widget_cache_auto"):
        try:
            try:
                from .widget_autocache import autocache
            except ImportError:
                from widget_autocache import autocache
            changed = autocache(translate("special://profile/addon_data/script.skinshortcuts"),
                                extra_addons=config.get("widget_cache_auto_addons") or ())
            if changed:
                kodi.log("Widget cache: routed %d new rows through the cache (%s); active after the menu rebuilds"
                         % (sum(changed.values()), ", ".join(sorted(changed))))
        except Exception as error:
            kodi.log("Widget cache auto-routing failed: %s" % type(error).__name__)
    try:
        refresher = start_widget_refresher(kodi)
    except Exception as error:
        refresher = None
        kodi.log('Widget cache unavailable: %s' % type(error).__name__)
    log_collector = None
    try:
        log_collector = start_log_collector(kodi)
    except Exception as error:
        kodi.log('Log history unavailable: %s' % type(error).__name__)
    watchdog = None
    if xbmc:
        try:
            watchdog = start_watchdog(kodi)
        except Exception as error:
            kodi.log('Connection watchdog unavailable: %s' % type(error).__name__)
    if xbmc:
        class ServiceMonitor(profile_transition.Monitor):
            def onSettingsChanged(self):
                if self.abortRequested():
                    return
                try:
                    new_config = load_config(service_addon())
                    kodi.installer_seed = new_config.get("installer_seed", {})
                    running["server"] = apply_settings_change(kodi, running["server"], running["config"], new_config, web_root)
                    running["config"] = new_config
                except Exception as error:
                    kodi.log("Settings reload failed: %s" % type(error).__name__)

            def onNotification(self, sender, method, data):
                if self.abortRequested() and method != "System.OnQuit":
                    return
                if method in ('Player.OnPlay', 'Player.OnAVStart') and refresher:
                    if refresher.playback_started_at is None:
                        refresher.playback_started()
                if method == 'Player.OnStop' and refresher:
                    refresher.playback_stopped()
                if method == 'System.OnQuit':
                    try:
                        guard.arm()
                        if guard.child is not None:
                            kodi.log('Shield exit guard armed on quit')
                    except Exception as error:
                        kodi.log('Shield exit guard could not start: %s' % type(error).__name__)
        monitor = ServiceMonitor()
    else:
        monitor = None
    try:
        wait_for_shutdown(monitor, startup_monitor)
    finally:
        retire_runtime(running["server"], refresher, watchdog, log_collector)
        stop_extension(kodi, private)
        try:
            guard.on_abort()
            if supported:
                kodi.log('Shield exit guard armed=%s' % bool(guard.child))
        except Exception as error:
            kodi.log('Shield exit guard unavailable: %s' % type(error).__name__)
        write_session(session_path, dict(session, stopped_at=time.time()))
        kodi.log('Manager network shutdown complete')


if __name__ == "__main__":
    try:
        main()
    finally:
        # Acknowledge a coordinated profile switch (a no-op without a coordinator).
        profile_transition.drained("service.kodi.addonadmin")
