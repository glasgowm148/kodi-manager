"""Cached rows any skin can use as widgets.

Skins differ in how widget rows are stored, but every skin's widget picker can
browse a video add-on's folders. Kodi Manager's "Cached rows" folder therefore
lists the rows saved here; each entry is a folder whose path is the cached widget
URL, so picking it in the skin gives a fast, cached row.

Rows are added from the "Add to Kodi Manager cached rows" context menu on any
add-on folder, or through ``/api/widget-cache/rows``. They are stored per
profile in ``widget_cache/rows.json``.
"""
import json
import os
import re
import uuid

try:
    from .widget_cache import cache_url, validate_source, strip_skin_reload
except ImportError:
    from widget_cache import cache_url, validate_source, strip_skin_reload

MAX_ROWS = 200


def _clean_label(label):
    label = re.sub(r"\[/?(?:COLOR[^\]]*|B|I|UPPERCASE|LOWERCASE|CAPITALIZE)\]", "", str(label or ""), flags=re.I)
    label = " ".join(label.split())[:80]
    if not label:
        raise ValueError("Row name is required")
    return label


class RowStore:
    def __init__(self, root):
        self.path = os.path.join(root, "rows.json")

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            return []
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get("source"), str) and r.get("id")] \
            if isinstance(rows, list) else []

    def _save(self, rows):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = "%s.%d.tmp" % (self.path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=1)
        os.replace(tmp, self.path)

    def add(self, label, source, pages=None, hide_watched=False):
        source = validate_source(strip_skin_reload(source))
        rows = self.load()
        for row in rows:
            if row["source"] == source:
                row.update({"label": _clean_label(label), "pages": pages, "hide_watched": bool(hide_watched)})
                self._save(rows)
                return row
        if len(rows) >= MAX_ROWS:
            raise ValueError("Too many cached rows")
        row = {"id": uuid.uuid4().hex[:12], "label": _clean_label(label), "source": source,
               "pages": pages, "hide_watched": bool(hide_watched)}
        rows.append(row)
        self._save(rows)
        return row

    def remove(self, row_id):
        rows = self.load()
        kept = [r for r in rows if r["id"] != row_id]
        if len(kept) == len(rows):
            raise ValueError("Unknown cached row")
        self._save(kept)

    def listing(self):
        """Rows with the URL a skin should use for each."""
        return [dict(row, widget_url=cache_url(row["source"], pages=row.get("pages"),
                                               hide_watched=row.get("hide_watched")))
                for row in self.load()]


ROWS_URL = "plugin://service.kodi.addonadmin/?mode=rows"
DASHBOARD_URL = "plugin://service.kodi.addonadmin/?mode=dashboard"


def dashboard_message(settings, ip_address):
    """What to show on the TV so someone can open the dashboard: (heading, text)."""
    port = settings.get("port") or "8765"
    token = settings.get("auth_token") or ""
    lan = str(settings.get("allow_lan", "")).lower() == "true" and settings.get("host") == "0.0.0.0"
    if not lan or not ip_address or ip_address.startswith("127."):
        return ("Turn on network access", "Network access is off, so other devices can't reach the dashboard.[CR]"
                "Open Kodi Manager's settings, turn on LAN access, set host 0.0.0.0 and port %s, "
                "then restart Kodi." % port)
    return ("Open the dashboard", "On a phone or computer on your home network, open:[CR]"
            "[B]http://%s:%s[/B][CR]Access token: [B]%s[/B]" % (ip_address, port, token or "(restart Kodi to create one)"))


def render_home(xbmcgui, xbmcplugin, handle):
    """Add-on root: how to reach the dashboard, and the cached rows folder."""
    xbmcplugin.setContent(handle, "files")
    dashboard = xbmcgui.ListItem(label="Open the dashboard on another device", offscreen=True)
    dashboard.setArt({"icon": "DefaultAddonService.png", "thumb": "DefaultAddonService.png"})
    rows = xbmcgui.ListItem(label="Cached rows", offscreen=True)
    rows.setArt({"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"})
    items = [(DASHBOARD_URL, dashboard, False), (ROWS_URL, rows, True)]
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def render_rows(xbmcgui, xbmcplugin, handle, store):
    xbmcplugin.setContent(handle, "videos")
    items = []
    for row in store.listing():
        li = xbmcgui.ListItem(label=row["label"], path=row["widget_url"], offscreen=True)
        li.setArt({"icon": "DefaultFolder.png", "thumb": "DefaultFolder.png"})
        li.setProperty("km_cached_row", "true")
        items.append((row["widget_url"], li, True))
    if not items:
        li = xbmcgui.ListItem(label="No cached rows yet: open an add-on folder, then choose "
                                    "'Add to Kodi Manager cached rows' from its context menu", offscreen=True)
        items.append(("", li, False))
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def add_from_context(xbmc, xbmcgui, xbmcvfs, listitem):
    """Context-menu entry: save the focused add-on folder as a cached row."""
    try:
        from .widget_cache import cache_root
    except ImportError:
        from widget_cache import cache_root
    path = listitem.getPath() if listitem is not None else xbmc.getInfoLabel("ListItem.FolderPath")
    label = (listitem.getLabel() if listitem is not None else "") or xbmc.getInfoLabel("ListItem.Label")
    try:
        validate_source(strip_skin_reload(path))
    except ValueError:
        xbmcgui.Dialog().notification("Kodi Manager", "Only video add-on folders can be cached rows")
        return None
    name = xbmcgui.Dialog().input("Row name", defaultt=_clean_label(label) if label else "")
    if not name:
        return None
    row = RowStore(cache_root(xbmcvfs)).add(name, path)
    xbmcgui.Dialog().notification("Kodi Manager", "Added. In your skin's widget picker choose "
                                                  "Kodi Manager > Cached rows > %s" % row["label"])
    return row
