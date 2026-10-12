"""Authenticated, bounded reads for non-ADB Kodi clients; no arbitrary file writes."""
import base64
import hashlib
import os
import re
import uuid
import xml.etree.ElementTree as ET

try:
    from . import tvos_storage
    from .fsutil import atomic_write_bytes, path_lock
    from .http_base import RequestHandler
    from .kodi_api import translate
except ImportError:
    import tvos_storage
    from fsutil import atomic_write_bytes, path_lock
    from http_base import RequestHandler
    from kodi_api import translate


def device_identity():
    path = translate("special://masterprofile/addon_data/service.kodi.addonadmin/device_identity.xml")
    with path_lock(path):
        if tvos_storage.exists(path):
            value = ET.fromstring(tvos_storage.read_bytes(path, 4096)).get("id", "")
            if not re.fullmatch(r"[a-f0-9]{32}", value):
                raise ValueError("Manager device identity is invalid; preserve private backups")
            return value
        value = uuid.uuid4().hex
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_bytes(path, ('<device id="%s" />' % value).encode())
        return value


def profile_root():
    master = os.path.realpath(translate("special://masterprofile/"))
    profile = os.path.realpath(translate("special://profile/"))
    if os.path.commonpath([master, profile]) != master:
        raise ValueError("Active Kodi profile is outside supported storage")
    relative = os.path.relpath(profile, master).replace(os.sep, "/")
    return "userdata" if relative == "." else "userdata/" + relative


def file_path(relative):
    if (not isinstance(relative, str) or len(relative) > 1024 or "\\" in relative
            or not re.fullmatch(r"[A-Za-z0-9_./ -]+", relative)
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("Invalid Kodi-relative file path")
    active = profile_root()
    if active == "userdata" and relative.startswith("userdata/profiles/"):
        raise ValueError("Only the active Kodi profile can be read")
    if relative.startswith(active + "/"):
        root = translate("special://profile/")
        suffix = relative[len(active) + 1:]
    elif relative.startswith("addons/"):
        root = translate("special://home/addons/")
        suffix = relative[7:]
    else:
        raise ValueError("Only active-profile or add-on text files can be read")
    if not relative.lower().endswith((".xml", ".json", ".properties", ".txt", ".po")):
        raise ValueError("Only bounded configuration text files can be read")
    target = os.path.abspath(os.path.join(root, suffix))
    if os.path.commonpath([os.path.realpath(root), os.path.realpath(target)]) != os.path.realpath(root):
        raise ValueError("Kodi file path leaves its directory")
    if any(os.path.islink(p) for p in _parents(target, os.path.abspath(root))):
        raise ValueError("Symlinked Kodi files are unsupported")
    return target


def _parents(path, root):
    while path != root:
        yield path
        path = os.path.dirname(path)


class PortableRoutes(RequestHandler):
    def api_portable_state(self):
        response = self.state.kodi.jsonrpc("Profiles.GetCurrentProfile")
        profile = response.get("result")
        if not isinstance(profile, dict) or not isinstance(profile.get("label"), str):
            raise ValueError("Current profile is unreadable")
        return {"platform": "tvos" if tvos_storage.is_tvos() else "other",
                "active": tvos_storage.application_active(), "device_id": device_identity(),
                "profile": profile["label"], "profile_root": profile_root()}

    def api_portable_file(self):
        path = self.query("path")
        data = tvos_storage.read_bytes(file_path(path), 600_000)
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "base64": base64.b64encode(data).decode("ascii")}
