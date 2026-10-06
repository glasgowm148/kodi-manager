"""Route skin widget rows through the widget cache (opt-in, service start).

Rows added later with the skin's menu editor point straight at the source
add-on. When the ``widget_cache_auto`` setting is on, the service rewrites
those rows in Skin Shortcuts' DATA files to the cached URL on start-up, after
copying the original files to ``kodi-manager-backups/autocache-<time>/``.
Skin Shortcuts rebuilds the menu when it sees the changed files, so the rows
switch over from the next Kodi start or profile load.

Only widget groups are touched (Home widgets ``*-10000-1`` and hub groups
``*hub``), and only browseable rows: POV ``build_*`` directories and TMDb
Helper rows marked ``widget=true`` (or Trakt user lists).
"""
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

try:
    from .widget_cache import TMDB_HELPERS, cache_url, strip_skin_reload, validate_source
except ImportError:
    from widget_cache import TMDB_HELPERS, cache_url, strip_skin_reload, validate_source

WIDGET_FILES = re.compile(r"^skin\.[A-Za-z0-9_.-]+-(?:10000-1|[a-z]+hub)\.DATA\.xml$")
_ACTION = re.compile(r'ActivateWindow\((Videos|10025),"?(plugin://[^"]+?)"?,return\)')


def cacheable(source):
    parsed = urlsplit(source)
    query = parse_qs(parsed.query)
    if parsed.netloc == "plugin.video.pov":
        ok = query.get("mode", [""])[0].startswith("build_")
    elif parsed.netloc in TMDB_HELPERS:
        ok = query.get("widget") == ["true"] or query.get("info") == ["trakt_userlist"]
    else:
        return False
    try:
        validate_source(strip_skin_reload(source))
    except ValueError:
        return False
    return ok


def convert_action(text):
    """Return the cached form of a widget action, or None to leave it alone."""
    match = _ACTION.fullmatch((text or "").strip())
    if not match or not cacheable(match.group(2)):
        return None
    return 'ActivateWindow(%s,"%s",return)' % (match.group(1), cache_url(match.group(2)))


def autocache(folder, now=None):
    """Rewrite direct widget rows in ``folder``. Returns {file name: rows changed}."""
    try:
        names = sorted(n for n in os.listdir(folder) if WIDGET_FILES.match(n))
    except OSError:
        return {}
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    changed = {}
    for name in names:
        path = os.path.join(folder, name)
        if os.path.islink(path):
            continue
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError):
            continue
        count = 0
        for action in tree.getroot().iter("action"):
            new = convert_action(action.text)
            if new:
                action.text = new
                count += 1
        if not count:
            continue
        backup = os.path.join(folder, "kodi-manager-backups", "autocache-" + stamp)
        os.makedirs(backup, exist_ok=True)
        shutil.copy2(path, os.path.join(backup, name))
        tmp = path + ".km-tmp"
        tree.write(tmp, encoding="utf-8")
        os.replace(tmp, path)
        changed[name] = count
    return changed
