"""Friendly titles for cached home-screen rows, for the dashboard's Row health page.

A cached row only knows its add-on folder path, such as
``plugin://plugin.video.themoviedb.helper/?info=trakt_history&tmdb_type=movie``.
The household knows it as the label the skin shows. In order of preference:

1. the label Skin Shortcuts saved for the widget that uses this path (the
   skin's DATA.xml widget groups or a ``widgetName`` property), with Kodi,
   skin and add-on string ids (``32043``, ``$LOCALIZE[32043]``,
   ``$ADDON[skin.bingie 32043]``) resolved through Kodi, then the strings.po
   files, and dropped when they cannot be resolved;
2. a readable name built from the path: the folder's ``name`` parameter, or
   its ``info``/``mode``/``action`` value ("trakt_history" -> "Trakt history").

Where the row appears ("Home", "Movies hub") comes from the widget group. Only
small Skin Shortcuts files are read; nothing here asks an add-on for anything.
"""
import ast
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

try:
    from .widget_cache import source_from_cache_url, strip_skin_reload
except ImportError:
    from widget_cache import source_from_cache_url, strip_skin_reload

MAX_FILE = 2 * 1024 * 1024
_ACTION = re.compile(r'ActivateWindow\(\s*[^,]+,\s*"?(plugin://[^"]+?)"?\s*(?:,\s*return\s*)?\)\s*$', re.I)
_DATA = re.compile(r"^(?:skin\.[A-Za-z0-9_.]+-)?(?P<group>[A-Za-z0-9_.-]+)\.DATA\.xml$")
_PROPERTIES = re.compile(r"^skin\.[A-Za-z0-9_.-]+\.properties$")
_WIDGET = re.compile(r"^widget(Path|Name)(\.\d+)?$", re.I)
_FORMATTING = re.compile(r"\[/?(?:COLOR[^\]]*|B|I|UPPERCASE|LOWERCASE|CAPITALIZE|LIGHT|CR)\]", re.I)
_WORDS = {"tmdb": "TMDb", "trakt": "Trakt", "tv": "TV", "tvshows": "TV shows", "tvshow": "TV show", "imdb": "IMDb",
          "mdblist": "MDBList", "ondeck": "on deck", "nextepisodes": "next episodes", "upnext": "up next",
          "inprogress": "in progress", "mostwatched": "most watched", "userlist": "user list", "uk": "UK", "us": "US",
          "4k": "4K", "hd": "HD", "id": "ID", "pov": "POV"}
_DROP = {"build", "list", "widget", "dir", "info"}
_GROUPS = {"10000": "Home", "home": "Home", "mainmenu": "Main menu", "movies": "Movies", "tvshows": "TV shows",
           "tv": "TV shows", "livetv": "Live TV", "music": "Music", "kids": "Kids", "custom": "Custom", "favourites": "Favourites",
           "favorites": "Favourites"}
ADDON_NAMES = {"plugin.video.themoviedb.helper": "TMDb Helper", "plugin.video.tmdb.bingie.helper": "TMDb Helper",
               "plugin.video.pov": "POV", "plugin.video.fen": "Fen", "plugin.video.fenlight": "Fen Light",
               "plugin.video.iplayerwww": "BBC iPlayer", "plugin.video.youtube": "YouTube"}


def normalise_source(path):
    """The plain add-on path a widget row ends up reading, cached or not."""
    path = (path or "").strip().strip('"')
    if path.startswith("plugin://service.kodi.addonadmin/"):
        path = source_from_cache_url(path) or ""
    return strip_skin_reload(path) if path.startswith("plugin://") else ""


def clean_text(text):
    text = _FORMATTING.sub("", str(text or ""))
    return " ".join(text.split())[:80]


def resolve_label(label, kodi_string=None, addon_string=None, po_strings=None):
    """Turn a stored label into text, or "" when it is only an id nobody can resolve.

    ``kodi_string(n)`` asks Kodi (core and active-skin strings); ``addon_string(addon, n)``
    asks an add-on; ``po_strings`` is {id: text} from the skin's strings.po files.
    """
    text = clean_text(label)
    if not text:
        return ""
    addon = None
    match = re.fullmatch(r"\$ADDON\[\s*([A-Za-z0-9_.-]+)\s+(\d+)\s*\]", text, re.I)
    if match:
        addon, number = match.group(1), match.group(2)
    else:
        match = re.fullmatch(r"(?:\$(?:LOCALIZE|SKIN)\[\s*(\d+)\s*(?:\|[^\]]*)?\]|(\d+))", text, re.I)
        if not match:
            return "" if "$" in text else text
        number = match.group(1) or match.group(2)
    candidates = []
    if addon and addon_string:
        candidates.append(lambda: addon_string(addon, int(number)))
    if kodi_string and not addon:
        candidates.append(lambda: kodi_string(int(number)))
    if po_strings:
        candidates.append(lambda: po_strings.get(number, ""))
    for candidate in candidates:
        try:
            value = clean_text(candidate())
        except Exception:
            value = ""
        if value and "$" not in value:
            return value
    return ""


def group_name(group):
    """ "skin.bingie-movieshub" style group -> "Movies hub"; "10000-1" -> "Home"."""
    key = re.sub(r"^skin\.[A-Za-z0-9_.]+-", "", str(group or "")).lower()
    key = re.sub(r"-\d+$", "", key)
    hub = key.endswith("hub") and key != "hub"
    base = key[:-3] if hub else key
    name = _GROUPS.get(base) or humanise_words(base) or "Home"
    return "%s hub" % name if hub else name


def humanise_words(value):
    words = [w for w in re.split(r"[_\s.+-]+", str(value or "").lower()) if w and w not in _DROP]
    out = [_WORDS.get(w, w) for w in words]
    text = " ".join(out).strip()
    return text[:1].upper() + text[1:] if text else ""


def route_title(source, addon_names=None):
    """A readable title from the path alone: {"title", "addon"}."""
    parsed = urlsplit(source or "")
    query = parse_qs(parsed.query)
    addon_id = parsed.netloc
    names = dict(ADDON_NAMES, **{k: clean_text(v) for k, v in (addon_names or {}).items() if clean_text(v)})
    addon = names.get(addon_id) or humanise_words(addon_id.replace("plugin.video.", ""))
    for key in ("name", "list_name", "title", "label"):
        if query.get(key) and clean_text(query[key][0]) and not re.fullmatch(r"\d+", query[key][0]):
            return {"title": clean_text(query[key][0]), "addon": addon}
    for key in ("info", "action", "mode"):
        value = (query.get(key) or [""])[0]
        if value:
            title = humanise_words(value)
            kind = (query.get("tmdb_type") or query.get("media_type") or query.get("type") or [""])[0]
            plural = {"movie": "movies", "tv": "shows", "tvshow": "shows", "show": "shows", "both": ""}.get(kind.lower(), "")
            if plural and plural not in title.lower():
                title = "%s (%s)" % (title, plural)
            return {"title": title, "addon": addon}
    folder = parsed.path.strip("/")
    return {"title": humanise_words(folder) if folder else addon, "addon": addon}


def _read(path):
    if os.path.islink(path) or os.path.getsize(path) > MAX_FILE:
        raise ValueError("unexpected file")
    with open(path, "rb") as handle:
        return handle.read()


def skin_rows(shortcuts_root, resolve=lambda label: clean_text(label)):
    """{source: {"label", "where": [..]}} from Skin Shortcuts' saved widget rows."""
    found = {}

    def add(path, label, where):
        source = normalise_source(path)
        if not source:
            return
        record = found.setdefault(source, {"label": "", "where": []})
        text = resolve(label) if label else ""
        if text and not record["label"]:
            record["label"] = text
        if where and where not in record["where"]:
            record["where"].append(where)
    try:
        names = sorted(os.listdir(shortcuts_root))
    except OSError:
        return found
    for name in names:
        path = os.path.join(shortcuts_root, name)
        data = _DATA.match(name)
        try:
            if data and data.group("group") not in ("mainmenu",):
                root = ET.fromstring(_read(path))
                where = group_name(data.group("group"))
                for shortcut in root.iter("shortcut"):
                    match = _ACTION.match(shortcut.findtext("action", "") or "")
                    if match:
                        add(match.group(1), shortcut.findtext("label", ""), where)
            elif _PROPERTIES.match(name):
                rows = ast.literal_eval(_read(path).decode("utf-8"))
                if not isinstance(rows, list):
                    continue
                names_by_key = {}
                for row in rows:
                    if isinstance(row, (list, tuple)) and len(row) >= 4 and all(isinstance(v, str) for v in row[:4]):
                        m = _WIDGET.match(row[2])
                        if m and m.group(1).lower() == "name":
                            names_by_key[(row[0], row[1], m.group(2) or "")] = row[3]
                for row in rows:
                    if isinstance(row, (list, tuple)) and len(row) >= 4 and all(isinstance(v, str) for v in row[:4]):
                        m = _WIDGET.match(row[2])
                        if m and m.group(1).lower() == "path":
                            label = names_by_key.get((row[0], row[1], m.group(2) or ""), "")
                            add(row[3], label, group_name(row[1]))
        except (OSError, ValueError, SyntaxError, UnicodeError, ET.ParseError, MemoryError):
            continue
    return found


_PO_CACHE = {}


def skin_strings(skin_path):
    """{id: text} from the skin's English strings.po (fallback when Kodi can't say), cached by mtime."""
    root = os.path.join(skin_path or "", "language")
    candidates = [os.path.join(root, "resource.language.en_gb", "strings.po"),
                  os.path.join(skin_path or "", "resources", "language", "resource.language.en_gb", "strings.po")]
    for path in candidates:
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        cached = _PO_CACHE.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            from .language_resolver import LanguageResolver
        except ImportError:
            from language_resolver import LanguageResolver
        resolver = LanguageResolver()
        resolver.load_po(path)
        _PO_CACHE[path] = (stamp, dict(resolver.labels))
        return _PO_CACHE[path][1]
    return {}


def label_resolver(kodi, skin_path=""):
    """resolve(label) using Kodi's strings, the add-on's own strings, then the skin's strings.po."""
    po = skin_strings(skin_path)
    kodi_string = getattr(kodi, "get_localized_string", None)
    addon_string = getattr(kodi, "get_addon_string", None)
    return lambda label: resolve_label(label, kodi_string, addon_string, po)


def row_titles(sources, shortcuts_root, resolve=lambda label: clean_text(label), addon_names=None):
    """{source: {"title", "addon", "where", "from"}} for each cached source."""
    skin = skin_rows(shortcuts_root, resolve)
    out = {}
    for source in sources:
        route = route_title(source, addon_names)
        saved = skin.get(normalise_source(source)) or skin.get(source) or {}
        title = saved.get("label") or route["title"]
        out[source] = {"title": title, "addon": route["addon"], "where": saved.get("where", [])[:4],
                       "from": "skin" if saved.get("label") else "path"}
    return out
