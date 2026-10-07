"""Fen Light keeps its settings in ``addon_data/plugin.video.fenlight/databases/settings.db``.

One reader and one writer for the settings page, the pipeline view and the
account editor. The database is opened through ``file:`` URIs built with
``Path.as_uri()`` (so spaces, ``#`` and ``?`` in paths work) with ``mode=ro``
or ``mode=rw``: neither ever creates an empty database.
"""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

try:
    from .kodi_api import translate
    from .validation import coerce_value
except ImportError:
    from kodi_api import translate
    from validation import coerce_value

FENLIGHT_ID = "plugin.video.fenlight"
DB_EDITABLE_TYPES = {"boolean", "bool", "string", "text", "path", "name", "action", "integer", "int", "number"}
_QUERY = "select setting_id, setting_type, setting_default, setting_value from settings order by setting_id"


def db_path(addon):
    if not addon or addon.get("addon_id") != FENLIGHT_ID:
        return ""
    return translate(os.path.join(addon.get("addon_data_path") or "", "databases", "settings.db"))


def _uri(path, mode):
    return Path(os.path.abspath(path)).as_uri() + "?mode=" + mode


def _scratch_dir():
    """Kodi's temp folder (always writable on Android), else the platform default."""
    for candidate in (translate("special://temp/"), tempfile.gettempdir()):
        if not candidate or candidate.startswith("special://"):
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue
    return None


def read_rows(addon):
    """[(id, type, default, value)] or [] when there is no database. Raises sqlite3.Error/OSError.

    A locked database (for example on SMB) is read from a private copy.
    """
    path = db_path(addon)
    if not path or not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect(_uri(path, "ro"), uri=True)
        try:
            return con.execute(_QUERY).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        pass
    fd, tmp = tempfile.mkstemp(prefix="fenlight_settings_", suffix=".db", dir=_scratch_dir())
    os.close(fd)
    try:
        shutil.copyfile(path, tmp)
        con = sqlite3.connect(_uri(tmp, "ro"), uri=True)
        try:
            return con.execute(_QUERY).fetchall()
        finally:
            con.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def coerce_db_value(setting_type, value):
    """Check a value against a settings.db type; returns the stored string or raises ValueError."""
    stype = (setting_type or "").lower()
    if stype not in DB_EDITABLE_TYPES:
        raise ValueError("Unsupported Fen Light DB setting type: %s" % stype)
    if isinstance(value, (dict, list, tuple)):
        raise ValueError("Expected a single value")
    if stype in ("boolean", "bool"):
        return coerce_value({"type": "bool"}, value)
    if stype in ("integer", "int"):
        if isinstance(value, bool):
            raise ValueError("Expected a whole number")
        try:
            return str(int(str(value).strip()))
        except ValueError:
            raise ValueError("Expected a whole number") from None
    if stype == "number":
        if isinstance(value, bool):
            raise ValueError("Expected a number")
        text = str(value).strip()
        try:
            float(text)
        except ValueError:
            raise ValueError("Expected a number") from None
        return text
    return "" if value is None else str(value)


def validate_changes(addon, changes):
    """[(setting_id, value)] -> [(setting_id, stored string)]; raises ValueError before anything is written."""
    path = db_path(addon)
    if not path or not os.path.isfile(path):
        raise ValueError("Fen Light settings.db not found")
    types = {sid: stype for sid, stype, _default, _value in read_rows(addon)}
    clean = []
    for sid, value in changes:
        if sid not in types:
            raise ValueError("Unknown Fen Light DB setting: %s" % sid)
        clean.append((sid, coerce_db_value(types[sid], value)))
    return clean


def write_changes(addon, clean):
    """Apply validated changes in one transaction. Never creates the database."""
    if not clean:
        return 0
    path = db_path(addon)
    if not path or not os.path.isfile(path):
        raise ValueError("Fen Light settings.db not found")
    con = sqlite3.connect(_uri(path, "rw"), uri=True)
    try:
        with con:
            for sid, value in clean:
                con.execute("update settings set setting_value=? where setting_id=?", (value, sid))
    finally:
        con.close()
    return len(clean)
