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
    from .server import ServerThread
    from .shield_exit import ShieldExitGuard
except ImportError:
    from auth import generate_token
    from kodi_api import KodiAPI, service_addon, translate
    from server import ServerThread
    from shield_exit import ShieldExitGuard


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
    if os.path.exists(seed_path):
        try:
            with open(seed_path, "r", encoding="utf-8") as fh:
                seed = json.load(fh)
        except Exception:
            seed = {}
    if os.path.exists(flag):
        try:
            addon.setSetting("allow_lan", "true")
            addon.setSetting("host", "0.0.0.0")
            addon.setSetting("port", "8765")
            os.remove(flag)
        except Exception:
            pass
    if seed:
        try:
            addon.setSetting("allow_lan", "true" if seed.get("allow_lan", True) else "false")
            addon.setSetting("host", seed.get("host", "0.0.0.0"))
            addon.setSetting("port", str(seed.get("port", 8765)))
        except Exception:
            pass
    allow_lan = _bool(get("allow_lan", "false"))
    host = get("host", "127.0.0.1")
    if host == "0.0.0.0" and not allow_lan:
        host = "127.0.0.1"
    config = {
        "enabled": _bool(get("enabled", "true")),
        "shield_exit_workaround": _bool(get("shield_exit_workaround", "false")),
        "host": host,
        "port": int(get("port", "8765")),
        "allow_lan": allow_lan,
        "write_enabled": _bool(get("write_enabled", "false")),
        "auth_token": token,
        "log_level": get("log_level", "info"),
        "backup_retention": int(get("backup_retention", "20")),
        "allow_secret_replacement": _bool(get("allow_secret_replacement", "false")),
        "allowed_addons_csv": get("allowed_addons_csv", ""),
        "delete_installer_result_after_first_login": _bool(get("delete_installer_result_after_first_login", "false")),
        "installer_seed": seed,
        "addon_data_dir": data_dir,
    }
    if seed and token:
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
        except Exception:
            pass
    return config


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
    server = ServerThread(kodi, config, web_root)
    server.start()
    kodi.log("Kodi Manager URL http://%s:%s token configured=%s" % (config["host"], config["port"], bool(config.get("auth_token"))))
    kodi.notify("Kodi Manager", "http://%s:%s" % (config["host"], config["port"]))
    supported = bool(xbmc and config['shield_exit_workaround']
                     and xbmc.getCondVisibility('System.Platform.Android')
                     and xbmc.getInfoLabel('System.BuildVersion').startswith('22.0-BETA2')
                     and os.path.isfile('/vendor/lib64/libnvglsi.so'))
    guard = ShieldExitGuard(supported, translate('special://logpath/kodi.log'),
                            os.path.join(os.path.dirname(__file__), 'shield_exit_guard.sh'),
                            translate('special://temp/shield-exit-result.json'))
    kodi.log('Shield exit workaround active=%s' % supported)
    if xbmc:
        class ServiceMonitor(xbmc.Monitor):
            def onNotification(self, sender, method, data):
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
        try:
            guard.on_abort()
            if supported:
                kodi.log('Shield exit guard armed=%s' % bool(guard.child))
        except Exception as error:
            kodi.log('Shield exit guard unavailable: %s' % type(error).__name__)
        server.stop()


if __name__ == "__main__":
    main()
