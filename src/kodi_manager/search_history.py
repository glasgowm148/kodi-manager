"""Searches the viewer made, kept per Kodi profile, offered back as suggestions while typing.

The file is ``search_history.json`` in Kodi Manager's addon_data of the current profile, so the
Kids profile keeps its own list. Entries are newest first; the same search typed again (ignoring
case and spacing) moves to the top instead of repeating.
"""
import json
import os
import re
import time

try:
    from .fsutil import atomic_write_json, interprocess_lock, path_lock
except ImportError:
    from fsutil import atomic_write_json, interprocess_lock, path_lock

HISTORY_FILE = "special://profile/addon_data/service.kodi.addonadmin/search_history.json"
MAX_ENTRIES = 50
MAX_LENGTH = 100
MIN_LENGTH = 2


def clean(query):
    """A search as stored: one line, single spaces, at most MAX_LENGTH characters; "" if unusable."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(query or ""))
    text = re.sub(r"\s+", " ", text).strip()[:MAX_LENGTH].strip()
    return text if len(text) >= MIN_LENGTH else ""


def _key(text):
    return text.casefold()


class SearchHistory:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = path, clock

    def entries(self):
        """[{"query", "at"}] newest first; [] when the file is missing or unreadable."""
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        items = data.get("entries") if isinstance(data, dict) else None
        out = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("query"), str) and clean(item["query"]):
                at = item.get("at")
                out.append({"query": clean(item["query"]), "at": at if isinstance(at, (int, float)) else 0})
        return out

    def add(self, query):
        """Record a search; returns the stored text, or "" when it is too short to keep."""
        text = clean(query)
        if not text:
            return ""
        with path_lock(self.path), interprocess_lock(self.path):
            kept = [e for e in self.entries() if _key(e["query"]) != _key(text)]
            entries = [{"query": text, "at": int(self.clock())}] + kept
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            atomic_write_json(self.path, {"version": 1, "entries": entries[:MAX_ENTRIES]})
        return text

    def remove(self, query):
        key = _key(clean(query))
        with path_lock(self.path), interprocess_lock(self.path):
            entries = self.entries()
            kept = [e for e in entries if _key(e["query"]) != key]
            if len(kept) != len(entries):
                atomic_write_json(self.path, {"version": 1, "entries": kept})
        return len(entries) - len(kept)

    def clear(self):
        with path_lock(self.path), interprocess_lock(self.path):
            if os.path.exists(self.path):
                atomic_write_json(self.path, {"version": 1, "entries": []})

    def suggest(self, prefix, limit=5):
        """Earlier searches for what is typed so far, newest first within each rank.

        A search that starts with ``prefix`` ranks above one with a later word that starts with
        it ("trai" finds "traitors", then "the traitors"); the exact search typed is left out.
        An empty prefix gives the most recent searches.
        """
        typed = _key(clean(prefix) or str(prefix or "").strip())
        found = []
        for entry in self.entries():
            key = _key(entry["query"])
            if not typed:
                found.append((0, entry))
            elif key == typed:
                continue
            elif key.startswith(typed):
                found.append((0, entry))
            elif any(word.startswith(typed) for word in re.split(r"[\s\-:.,'&]+", key)[1:]):
                found.append((1, entry))
        found.sort(key=lambda pair: pair[0])   # stable: newest first inside each rank
        return [entry["query"] for _, entry in found[:max(0, int(limit))]]


# --- putting a search into the running skin ------------------------------------------------------

BINGIE = "skin.bingie"
BINGIE_SEARCH_WINDOW = "1109"
TMDB_HELPERS = ("plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper")


def _bool(kodi, condition):
    result = kodi.jsonrpc("XBMC.GetInfoBooleans", {"booleans": [condition]}).get("result") or {}
    return bool(result.get(condition))


def open_search(kodi, query, history=None):
    """Show ``query`` in the running skin's search, as if it had been typed there.

    Bingie: its search window (1109) with the term in Skin.String(CustomSearchTerm). Other skins:
    a TMDb Helper search listing in the Videos window. Returns {"opened", "query", "how"} or
    {"opened": False, "reason"} when the text is unusable or nothing can search.
    """
    try:
        from .skin_settings import quote_param
    except ImportError:
        from skin_settings import quote_param
    text = clean(query)
    if not text:
        return {"opened": False, "reason": "empty_query"}
    skin = (kodi.get_active_skin() or {}).get("addon_id", "")
    if skin == BINGIE:
        # An open keyboard would write its own text over the term when it closes.
        kodi.execute_builtin("Dialog.Close(virtualkeyboard,true)")
        kodi.execute_builtin("Skin.SetString(CustomSearchTerm,%s)" % quote_param(text))
        kodi.execute_builtin("SetProperty(CustomSearch,1,home)")
        if not _bool(kodi, "Window.IsActive(%s)" % BINGIE_SEARCH_WINDOW):
            kodi.execute_builtin("ActivateWindow(%s)" % BINGIE_SEARCH_WINDOW)
        how = "bingie"
    else:
        helper = next((aid for aid in TMDB_HELPERS if (kodi.get_addon_details(aid) or {}).get("enabled")), "")
        if not helper:
            return {"opened": False, "reason": "no_search_handler", "skin": skin}
        try:
            from urllib.parse import quote_plus
        except ImportError:  # pragma: no cover
            from urllib import quote_plus
        url = "plugin://%s/?info=search&tmdb_type=both&query=%s" % (helper, quote_plus(text))
        kodi.execute_builtin("ActivateWindow(Videos,%s,return)" % quote_param(url))
        how = helper
    if history is not None:
        history.add(text)
    return {"opened": True, "query": text, "how": how}
