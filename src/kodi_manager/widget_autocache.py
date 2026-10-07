"""Route skin widget rows through the widget cache (opt-in, service start).

Rows added later with the skin's menu editor point straight at the source
add-on. When the ``widget_cache_auto`` setting is on, the service rewrites
those rows in Skin Shortcuts' DATA files to the cached URL on start-up, after
copying the original files to ``kodi-manager-backups/autocache-<time>/``.
Skin Shortcuts rebuilds the menu when it sees the changed files, so the rows
switch over from the next Kodi start or profile load.

Two Skin Shortcuts layouts are handled:

* skins that keep widget rows as shortcuts in widget groups (Bingie: Home
  widgets ``*-10000-1`` and hub groups ``*hub``), whose actions are rewritten;
* skins that keep a ``widgetPath`` property per menu item in
  ``skin.<name>.properties`` (most other Skin Shortcuts skins).

Only browseable rows are routed: Fen-family/POV ``build_*`` directories, TMDb
Helper rows marked ``widget=true`` (or Trakt user lists), and any directory of
the add-ons listed in the "Also route rows from these add-ons" setting.
"""
import ast
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

try:
    from .widget_cache import TMDB_HELPERS, cache_url, strip_skin_reload, validate_source
    from .fsutil import atomic_write_bytes, atomic_write_text
    from .backup import prune_folder
    from . import skin_layout
except ImportError:
    from widget_cache import TMDB_HELPERS, cache_url, strip_skin_reload, validate_source
    from fsutil import atomic_write_bytes, atomic_write_text
    from backup import prune_folder
    import skin_layout

WIDGET_FILES = re.compile(r"^skin\.[A-Za-z0-9_.-]+-(?:10000-1|[a-z]+hub)\.DATA\.xml$")
PROPERTY_FILES = re.compile(r"^skin\.[A-Za-z0-9_.-]+\.properties$")
WIDGET_PATH_PROPERTY = re.compile(r"^widgetPath(?:\.\d+)?$", re.I)
_ACTION = re.compile(r'ActivateWindow\((Videos|10025),"?(plugin://[^"]+?)"?,return\)')


def cacheable(source, extra_addons=()):
    parsed = urlsplit(source)
    query = parse_qs(parsed.query)
    if parsed.netloc in extra_addons:
        ok = True
    elif query.get("mode", [""])[0].startswith("build_"):
        ok = True
    elif parsed.netloc in TMDB_HELPERS:
        ok = query.get("widget") == ["true"] or query.get("info") == ["trakt_userlist"]
    else:
        return False
    try:
        validate_source(strip_skin_reload(source))
    except ValueError:
        return False
    return ok


def convert_action(text, extra_addons=()):
    """Return the cached form of a widget action, or None to leave it alone."""
    match = _ACTION.fullmatch((text or "").strip())
    if not match or not cacheable(match.group(2), extra_addons):
        return None
    return 'ActivateWindow(%s,"%s",return)' % (match.group(1), cache_url(match.group(2)))


def convert_path(path, extra_addons=()):
    """Return the cached form of a widget path, or None to leave it alone."""
    path = (path or "").strip()
    if not path.startswith("plugin://plugin.video.") or not cacheable(path, extra_addons):
        return None
    return cache_url(path)


def _backup(folder, stamp, name, path):
    root = os.path.join(folder, "kodi-manager-backups")
    if os.path.islink(root):
        raise ValueError("Backup directory must not be a symlink")
    backup = os.path.join(root, "autocache-" + stamp)
    os.makedirs(backup, exist_ok=True)
    shutil.copy2(path, os.path.join(backup, name), follow_symlinks=False)


def _properties(folder, name, stamp, extra_addons):
    path = os.path.join(folder, name)
    try:
        with open(path, encoding="utf-8") as fh:
            rows = ast.literal_eval(fh.read())
    except (OSError, ValueError, SyntaxError):
        return 0
    if not isinstance(rows, list):
        return 0
    count = 0
    for row in rows:
        if isinstance(row, list) and len(row) >= 4 and isinstance(row[2], str) and WIDGET_PATH_PROPERTY.match(row[2]):
            new = convert_path(row[3], extra_addons) if isinstance(row[3], str) else None
            if new:
                row[3] = new
                count += 1
    if count:
        _backup(folder, stamp, name, path)
        atomic_write_text(path, repr(rows))
    return count


def autocache(folder, now=None, extra_addons=()):
    """Rewrite direct widget rows in ``folder``. Returns {file name: rows changed}.

    Holds the skin layout lock (the dashboard's layout editor writes the same
    files), keeps XML comments, writes atomically and prunes old
    ``autocache-*`` backups to the retention setting.
    """
    with skin_layout._LOCK:
        return _autocache(folder, now, extra_addons)


def _autocache(folder, now, extra_addons):
    try:
        listing = sorted(os.listdir(folder))
    except OSError:
        return {}
    extra_addons = tuple(a.strip() for a in extra_addons if a and a.strip().startswith("plugin.video."))
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    changed = {}
    for name in (n for n in listing if PROPERTY_FILES.match(n)):
        if not os.path.islink(os.path.join(folder, name)):
            count = _properties(folder, name, stamp, extra_addons)
            if count:
                changed[name] = count
    for name in (n for n in listing if WIDGET_FILES.match(n)):
        path = os.path.join(folder, name)
        if os.path.islink(path):
            continue
        try:
            root = skin_layout._xml(skin_layout._read(path))
        except (OSError, ValueError, ET.ParseError):
            continue
        count = 0
        for action in root.iter("action"):
            new = convert_action(action.text, extra_addons)
            if new:
                action.text = new
                count += 1
        if not count:
            continue
        _backup(folder, stamp, name, path)
        atomic_write_bytes(path, ET.tostring(root, encoding="utf-8"))
        changed[name] = count
    if changed:
        prune_folder(os.path.join(folder, "kodi-manager-backups"), "autocache-", keep=("autocache-" + stamp,))
    return changed
