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


def file_path(relative, active=None):
    if (not isinstance(relative, str) or len(relative) > 1024 or "\\" in relative
            or not re.fullmatch(r"[A-Za-z0-9_./ -]+", relative)
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("Invalid Kodi-relative file path")
    active = profile_root() if active is None else active
    if active == "userdata" and relative.startswith("userdata/profiles/"):
        raise ValueError("Only the active Kodi profile can be read")
    if active == "userdata":
        master = translate("special://masterprofile/")
        profiles = os.path.join(master, "profiles.xml")
        if tvos_storage.exists(profiles):
            # Kodi permits nonstandard profile directories, outside profiles/.
            for element in ET.fromstring(tvos_storage.read_bytes(profiles)).findall("./profile/directory"):
                directory = element.text or ""
                if directory.startswith("special://"):
                    directory = translate(directory)
                target = os.path.realpath(os.path.join(master, directory))
                if target != os.path.realpath(master) and os.path.commonpath([os.path.realpath(master), target]) == os.path.realpath(master):
                    prefix = "userdata/" + os.path.relpath(target, master).replace(os.sep, "/") + "/"
                    if relative.startswith(prefix):
                        raise ValueError("Only the active Kodi profile can be read")
    if relative.startswith(active + "/"):
        # Resolve from the captured profile, rather than a second mutable
        # special://profile lookup that could select a different profile.
        root = os.path.join(translate("special://masterprofile/"), *active.split("/")[1:])
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
        root = profile_root()
        response = self.state.kodi.jsonrpc("Profiles.GetCurrentProfile")
        profile = response.get("result")
        if not isinstance(profile, dict) or not isinstance(profile.get("label"), str):
            raise ValueError("Current profile is unreadable")
        if profile_root() != root:
            raise ValueError("Current profile changed; inspect again")
        return {"platform": "tvos" if tvos_storage.is_tvos() else "other",
                "active": tvos_storage.application_active(), "device_id": device_identity(),
                "profile": profile["label"], "profile_root": root}

    def api_portable_file(self):
        path = self.query("path")
        root, identifier = profile_root(), device_identity()
        for name, value in (("device_id", identifier), ("profile_root", root)):
            expected = self.query(name)
            if expected and expected != value:
                raise ValueError("Device/profile changed; inspect again")
        data = tvos_storage.read_bytes(file_path(path, root), 600_000)
        if profile_root() != root or device_identity() != identifier:
            raise ValueError("Device/profile changed during file read; inspect again")
        return {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "base64": base64.b64encode(data).decode("ascii"),
                "device_id": identifier, "profile_root": root}
