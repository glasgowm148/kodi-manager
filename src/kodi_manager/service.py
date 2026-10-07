import hashlib
import json
import os
import time

try:
    import xbmc
except ImportError:
    xbmc = None

try:
    from .auth import generate_token
    from .kodi_api import KodiAPI, service_addon, translate
    from .netconfig import DEFAULT_PORT, effective_host, parse_int
    from .server import ServerThread
    from .shield_exit import ShieldExitGuard
    from .widget_cache import Refresher, WidgetCache, jsonrpc_via, RELOAD_PROPERTY
except ImportError:
    from auth import generate_token
    from kodi_api import KodiAPI, service_addon, translate
    from netconfig import DEFAULT_PORT, effective_host, parse_int
    from server import ServerThread
    from shield_exit import ShieldExitGuard
    from widget_cache import Refresher, WidgetCache, jsonrpc_via, RELOAD_PROPERTY

# Settings that need a new listening socket when they change.
NETWORK_KEYS = ("host", "port", "allow_lan")


def _bool(v):
    return str(v).lower() in ("true", "1", "yes", "on")


def load_config(addon):
    def get(key, default=""):
        try:
            val = addon.getSetting(key)
            return val if val != "" else default
        except Exception:
            return default
    token = get("auth_token", "")
    if not token:
        token = generate_token()
        try:
            addon.setSetting("auth_token", token)
        except Exception:
            pass
    data_dir = translate("special://profile/addon_data/service.kodi.addonadmin")
    flag = os.path.join(data_dir, "allow_lan_first_run.flag")
    seed_path = os.path.join(data_dir, "installer_seed.json")
    seed = {}
    seed_digest = ""
    if os.path.exists(seed_path):
        try:
            with open(seed_path, "rb") as fh:
                raw = fh.read()
            seed = json.loads(raw.decode("utf-8"))
            seed_digest = hashlib.sha256(raw).hexdigest()
        except Exception:
            seed = {}
    # The installer seed is a one-time handoff. Apply its network settings and
    # write installer_result.json once per seed, so later changes the user makes
    # in the add-on settings (for example switching LAN access off) persist.
    applied_path = os.path.join(data_dir, "installer_seed.applied")
    first_seed_run = False
    if seed:
        try:
            with open(applied_path, "r", encoding="utf-8") as fh:
                first_seed_run = fh.read().strip() != seed_digest
        except OSError:
            first_seed_run = True
    if os.path.exists(flag):
        try:
            addon.setSetting("allow_lan", "true")
            addon.setSetting("host", "0.0.0.0")
            addon.setSetting("port", "8765")
            os.remove(flag)
        except Exception:
            pass
    if first_seed_run:
        try:
            addon.setSetting("allow_lan", "true" if seed.get("allow_lan", True) else "false")
            addon.setSetting("host", seed.get("host", "0.0.0.0"))
            addon.setSetting("port", str(seed.get("port", 8765)))
        except Exception:
            pass
    allow_lan = _bool(get("allow_lan", "false"))
    # LAN access with the host left at 127.0.0.1 listens on 0.0.0.0; LAN off listens on loopback.
    host = effective_host(get("host", "127.0.0.1"), allow_lan)
    config = {
        "enabled": _bool(get("enabled", "true")),
        "shield_exit_workaround": _bool(get("shield_exit_workaround", "false")),
        "host": host,
        "port": parse_int(get("port", str(DEFAULT_PORT)), DEFAULT_PORT, 1, 65535),
        "allow_lan": allow_lan,
        "write_enabled": _bool(get("write_enabled", "false")),
        "auth_token": token,
        "log_level": get("log_level", "info"),
        "backup_retention": parse_int(get("backup_retention", "20"), 20, 1, 1000),
        "widget_cache_auto": _bool(get("widget_cache_auto", "false")),
        "widget_cache_auto_addons": [a.strip() for a in get("widget_cache_auto_addons", "").split(",") if a.strip()],
        "allowed_addons_csv": get("allowed_addons_csv", ""),
        "delete_installer_result_after_first_login": _bool(get("delete_installer_result_after_first_login", "false")),
        "installer_seed": seed,
        "addon_data_dir": data_dir,
    }
    if first_seed_run and token:
        try:
            os.makedirs(data_dir, exist_ok=True)
            result = {
                "ok": True,
                "web_url": "http://%s:%s" % (seed.get("kodi_ip_hint", "127.0.0.1"), config["port"]),
                "auth_token": token,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "installer_nonce": seed.get("installer_nonce", ""),
            }
            with open(os.path.join(data_dir, "installer_result.json"), "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2)
            with open(applied_path, "w", encoding="utf-8") as fh:
                fh.write(seed_digest)
        except Exception:
            pass
    return config


# Refresh cached rows only while the TV is quiet: no media loaded, no busy or
# progress dialog (POV searching for sources), no modal dialog and no remote
# press for a minute.
BUSY_CONDITION = ("Player.HasMedia | Window.IsActive(busydialog) | Window.IsActive(busydialognocancel)"
                  " | Window.IsActive(progressdialog) | Window.IsActive(extendedprogressdialog)"
                  " | Window.IsActive(progress_media.xml) | System.HasModalDialog | !System.IdleTime(60)")


def start_widget_refresher(kodi):
    """Refresh cached widget rows one at a time in the background."""
    if not xbmc:
        return None
    import threading
    import xbmcgui
    cache = WidgetCache(translate("special://profile/addon_data/service.kodi.addonadmin/widget_cache"))
    home = xbmcgui.Window(10000)
    player = xbmc.Player()
    refresher = Refresher(cache, jsonrpc_via(xbmc), player.isPlayingVideo,
                          lambda value: home.setProperty(RELOAD_PROPERTY, value), kodi.log,
                          external_reload=lambda: home.getProperty("TMDbBingieHelper.Widgets.Reload")
                          + "|" + home.getProperty("TMDbHelper.Widgets.Reload"),
                          is_busy=lambda: xbmc.getCondVisibility(BUSY_CONDITION))
    refresher.stop = threading.Event()
    refresher.sleep = refresher.stop.wait

    def run():
        while not refresher.stop.is_set():
            try:
                refresher.tick(refresher.stop.is_set)
            except Exception as error:
                kodi.log("Widget cache refresh error: %s" % type(error).__name__)
            refresher.stop.wait(2)

    # Daemon: profile changes stop scripts while Kodi calls may block.
    threading.Thread(target=run, name="km-widget-cache", daemon=True).start()
    return refresher


def start_watchdog(kodi):
    """Background connection and memory check; notifies once when something is wrong."""
    import threading
    try:
        from .netwatch import Watchdog
        from .memstat import memory_status
    except ImportError:
        from netwatch import Watchdog
        from memstat import memory_status
    watchdog = Watchdog(lambda title, message: kodi.notify(title, message),
                        is_quiet=lambda: not xbmc.getCondVisibility(BUSY_CONDITION),
                        memory=memory_status, log=kodi.log)
    watchdog.stop = threading.Event()

    def run():
        while not watchdog.stop.is_set():
            try:
                watchdog.tick()
            except Exception as error:
                kodi.log("Connection watchdog error: %s" % type(error).__name__)
            watchdog.stop.wait(15)

    threading.Thread(target=run, name="km-watchdog", daemon=True).start()
    return watchdog


def start_server(kodi, config, web_root, server_class=None):
    """Start the dashboard server; on failure (port in use, bad address) log, notify and return None."""
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


def main():
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
    root = os.path.abspath(addon.getAddonInfo("path"))
    web_root = os.path.join(root, "resources", "web")
    running = {"server": start_server(kodi, config, web_root), "config": config}
    if running["server"]:
        kodi.notify("Kodi Manager", "http://%s:%s" % (config["host"], config["port"]))
    supported = bool(xbmc and config['shield_exit_workaround']
                     and xbmc.getCondVisibility('System.Platform.Android')
                     and xbmc.getInfoLabel('System.BuildVersion').startswith('22.0-BETA2')
                     and os.path.isfile('/vendor/lib64/libnvglsi.so'))
    guard = ShieldExitGuard(supported, translate('special://logpath/kodi.log'),
                            os.path.join(os.path.dirname(__file__), 'shield_exit_guard.sh'),
                            translate('special://temp/shield-exit-result.json'))
    kodi.log('Shield exit workaround active=%s' % supported)
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
    watchdog = None
    if xbmc:
        try:
            watchdog = start_watchdog(kodi)
        except Exception as error:
            kodi.log('Connection watchdog unavailable: %s' % type(error).__name__)
    if xbmc:
        class ServiceMonitor(xbmc.Monitor):
            def onSettingsChanged(self):
                try:
                    new_config = load_config(service_addon())
                    kodi.installer_seed = new_config.get("installer_seed", {})
                    running["server"] = apply_settings_change(kodi, running["server"], running["config"], new_config, web_root)
                    running["config"] = new_config
                except Exception as error:
                    kodi.log("Settings reload failed: %s" % type(error).__name__)

            def onNotification(self, sender, method, data):
                if method in ('Player.OnPlay', 'Player.OnAVStart') and refresher:
                    if refresher.playback_started_at is None:
                        refresher.playback_started()
                if method == 'Player.OnStop' and refresher:
                    refresher.playback_stopped()
                if method == 'System.OnQuit':
                    try:
                        guard.arm()
                    except Exception as error:
                        kodi.log('Shield exit guard could not start: %s' % type(error).__name__)
        monitor = ServiceMonitor()
    else:
        monitor = None
    try:
        while True:
            if monitor and monitor.abortRequested():
                break
            if monitor:
                monitor.waitForAbort(1)
            else:
                time.sleep(1)
    finally:
        if refresher:
            refresher.stop.set()
        if watchdog:
            watchdog.stop.set()
        try:
            guard.on_abort()
            if supported:
                kodi.log('Shield exit guard armed=%s' % bool(guard.child))
        except Exception as error:
            kodi.log('Shield exit guard unavailable: %s' % type(error).__name__)
        if running["server"]:
            running["server"].stop()


if __name__ == "__main__":
    main()
