"""The service's settings: read once at start and again when they are saved in Kodi.

``load_config`` also applies a one-time installer seed and writes its result file.
"""
import hashlib
import json
import os
import tempfile
import time

try:
    from .auth import generate_token
    from .kodi_api import translate
    from .netconfig import DEFAULT_PORT, effective_host, parse_int
except ImportError:
    from auth import generate_token
    from kodi_api import translate
    from netconfig import DEFAULT_PORT, effective_host, parse_int

# Settings that need a new listening socket when they change.
NETWORK_KEYS = ("host", "port", "allow_lan")


def _bool(v):
    return str(v).lower() in ("true", "1", "yes", "on")


# Boolean settings are read through Kodi's typed settings API when it exists
# (Kodi 20+); getSetting's text form is the fallback for older Kodi and fakes.
BOOL_KEYS = frozenset(("enabled", "shield_exit_workaround", "allow_lan", "write_enabled",
                       "widget_cache_auto", "delete_installer_result_after_first_login"))


def load_config(addon):
    def get(key, default=""):
        try:
            if key in BOOL_KEYS and hasattr(addon, "getSettings"):
                return "true" if addon.getSettings().getBool(key) else "false"
        except Exception:
            pass
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
            # Readers (the installer, /api/bootstrap/status) see the old file or the whole new one.
            write_private_file(os.path.join(data_dir, "installer_result.json"),
                               json.dumps(result, indent=2).encode("utf-8"))
            write_private_file(applied_path, seed_digest.encode("utf-8"))
        except Exception:
            pass
    return config


def write_private_file(path, data):
    """Replace ``path`` atomically with an owner-only file (it may hold the access token)."""
    fd, temp = tempfile.mkstemp(prefix="." + os.path.basename(path)[:40] + ".", suffix=".tmp",
                                dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
