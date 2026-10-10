"""Stale-while-revalidate cache for add-on widget rows.

Skins call add-on directories for every widget row each time a hub opens.
Heavy add-ons (POV, for example) spend 1-2 seconds of CPU per call before any
artwork can appear, and every row is requested at once. This module stores the
last listing of each row on disk so a row can be served from a lightweight
plugin call, then refreshed one at a time in the background by the service.

Widget URL:
    plugin://service.kodi.addonadmin/?mode=cached&source=<encoded directory URL>
    [&reload=$INFO[Window(Home).Property(km_widgets)]]

`reload` is ignored by the cache; it only lets the skin reload rows after the
service bumps ``Window(Home).Property(km_widgets)`` with fresh data.

Only stdlib imports at module level: this runs in every widget invocation.
"""
import hashlib
import json
import os
import re
import time
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlsplit, urlunsplit

PLUGIN_URL = "plugin://service.kodi.addonadmin/"
RELOAD_PROPERTY = "km_widgets"
RELOAD_INFO = "$INFO[Window(Home).Property(%s)]" % RELOAD_PROPERTY

TTL_PROGRESS = 15 * 60
TTL_DEFAULT = 6 * 3600
TTL_STATIC = 24 * 3600
PRUNE_AFTER = 21 * 86400
MAX_ITEMS = 200
MAX_CAST = 8

FIELDS = ["title", "genre", "year", "rating", "votes", "playcount", "director", "trailer",
          "tagline", "plot", "originaltitle", "lastplayed", "writer", "studio", "mpaa",
          "cast", "country", "imdbnumber", "premiered", "runtime", "firstaired", "season",
          "episode", "showtitle", "thumbnail", "fanart", "art", "resume", "uniqueid",
          "dateadded", "tag"]

_PROGRESS_MODES = {"build_continue_episode", "build_next_episode", "build_in_progress_episode"}
# TMDb Helper (and its Bingie fork) use ?info=... for routes and resolve
# their play items through setResolvedUrl, so those leaves stay playable.
TMDB_HELPERS = {"plugin.video.tmdb.bingie.helper", "plugin.video.themoviedb.helper"}
_PROGRESS_INFOS = {"trakt_ondeck", "trakt_ondeck_unwatched", "trakt_nextepisodes", "trakt_history",
                   "trakt_upnext", "trakt_inprogress", "trakt_watchlist", "trakt_recommendations",
                   "trakt_calendar", "trakt_mostwatched_user"}
_PROGRESS_ACTIONS = {"in_progress_movies", "in_progress_tvshows", "trakt_recommendations",
                     "trakt_watchlist", "trakt_watchlist_lists"}
_STATIC_MODES = {"build_season_list", "build_episode_list"}
_CONTENT = {"build_season_list": "seasons", "build_episode_list": "episodes",
            "build_continue_episode": "episodes", "build_next_episode": "episodes",
            "build_in_progress_episode": "episodes", "build_movie_list": "movies",
            "build_tvshow_list": "tvshows"}
_MEDIA = {"movie", "tvshow", "season", "episode", "musicvideo"}


def validate_source(source):
    """Accept only browseable video add-on directories, never action endpoints (see route_guard)."""
    try:
        from .route_guard import check_directory
    except ImportError:
        from route_guard import check_directory
    return check_directory(source, "Action endpoints cannot be cached")


def strip_skin_reload(source):
    """Drop skin reload counters ($INFO[...]) from a source: the cache has its own."""
    return re.sub(r"&reload=\$INFO\[[^\]]*\]", "", source)


def cache_url(source, reload=True, pages=None, hide_watched=False):
    """Cached widget URL. ``pages`` reads that many source pages (following the
    add-on's Next page item); ``hide_watched`` drops watched items when shown."""
    params = {"mode": "cached", "source": validate_source(strip_skin_reload(source))}
    if pages:
        params["pages"] = str(_clamp_pages(pages))
    if hide_watched:
        params["hide_watched"] = "true"
    url = PLUGIN_URL + "?" + urlencode(params)
    return url + "&reload=" + RELOAD_INFO if reload else url


def source_from_cache_url(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if parsed.netloc != "service.kodi.addonadmin" or query.get("mode") != ["cached"]:
        return None
    return query.get("source", [None])[0]


MAX_PAGES = 5
_LIST_MODES = {"build_movie_list", "build_tvshow_list", "build_trakt_list"}
POV_NEXT_ART = "special://home/addons/plugin.video.pov/resources/skins/Default/media/item_next.png"


def _clamp_pages(value):
    try:
        return max(1, min(MAX_PAGES, int(value)))
    except (TypeError, ValueError):
        return 1


def is_list_row(source):
    """Known movie/show list routes (not progress rows, seasons or episodes).

    ``build_*_list`` routes are shared by POV and the Fen family; TMDb Helper
    lists are its widget rows. Other add-ons are recognised from their own
    listing instead (see ``view_more_url``).
    """
    parsed = urlsplit(source)
    query = parse_qs(parsed.query)
    if is_progress(source):
        return False
    if query.get("mode", [""])[0] in _LIST_MODES:
        return True
    if parsed.netloc in TMDB_HELPERS:
        return query.get("widget") == ["true"] or query.get("info") == ["trakt_userlist"]
    return False


def default_pages(source):
    """Known list routes show about 20 items per page; read two so rows are not sparse."""
    return 2 if is_list_row(source) and urlsplit(source).netloc not in TMDB_HELPERS else 1


def view_more_url(source, has_more=False):
    """The full, paged listing behind a row, or None for rows without one.

    Known list routes always get one; any other add-on's row gets one when its
    listing offered a further page.
    """
    if not is_list_row(source):
        return source if has_more and not is_progress(source) else None
    parsed = urlsplit(source)
    if parsed.netloc in TMDB_HELPERS:
        pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != "widget"]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(pairs), ""))
    return source


def row_options(query):
    """(pages, hide_watched) from a cached widget URL's query."""
    source = query.get("source", [""])[0]
    pages = query.get("pages", [None])[0]
    pages = _clamp_pages(pages) if pages else default_pages(source)
    return pages, query.get("hide_watched", ["false"])[0] == "true"


def _route(source):
    query = parse_qs(urlsplit(source).query)
    return query.get("mode", [""])[0], query.get("action", [""])[0]


def is_progress(source):
    mode, action = _route(source)
    info = parse_qs(urlsplit(source).query).get("info", [""])[0]
    return mode in _PROGRESS_MODES or action in _PROGRESS_ACTIONS or info in _PROGRESS_INFOS


def helper_item(item, source):
    """Rebuild the ListItem properties TMDb Helper sets but JSON-RPC drops.

    Returns (properties, playable). TMDb Helper exposes every unique id as
    ``<name>_id``, every item URL parameter as ``item.<name>``, the source's
    ``widget`` flag, and marks ``info=play`` leaves playable (it resolves them
    with setResolvedUrl unless its "only resolve strm" option is on).
    """
    if urlsplit(source).netloc not in TMDB_HELPERS:
        return {}, False
    props = {"%s_id" % k: str(v) for k, v in (item.get("uniqueid") or {}).items() if k and v}
    query = parse_qs(urlsplit(item.get("file", "")).query)
    for key, values in query.items():
        if key and values and values[0]:
            props["item." + key] = values[0]
    if query.get("tmdb_type"):
        props["item.type"] = query["tmdb_type"][0]
    widget = parse_qs(urlsplit(source).query).get("widget")
    if widget:
        props["widget"] = widget[0]
    playable = urlsplit(item.get("file", "")).netloc in TMDB_HELPERS and query.get("info") == ["play"]
    return props, playable


def ttl_for(source):
    if is_progress(source):
        return TTL_PROGRESS
    return TTL_STATIC if _route(source)[0] in _STATIC_MODES else TTL_DEFAULT


def cache_key(source):
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:24]


def content_for(source, files):
    content = _CONTENT.get(_route(source)[0])
    if content:
        return content
    kinds = {media_type(item) for item in files}
    if len(kinds) == 1:
        return {"movie": "movies", "tvshow": "tvshows", "season": "seasons",
                "episode": "episodes", "musicvideo": "musicvideos"}.get(kinds.pop(), "videos")
    return "videos"


def media_type(item, content=None):
    kind = item.get("type")
    if kind in _MEDIA:
        return kind
    season, episode = item.get("season", -1), item.get("episode", -1)
    if isinstance(episode, int) and episode > 0:
        return "episode"
    if isinstance(season, int) and season >= 0 and item.get("filetype") == "directory":
        return "season"
    return {"movies": "movie", "tvshows": "tvshow", "seasons": "season", "episodes": "episode"}.get(content)


def _next_page(item):
    label = re.sub(r"\[/?(?:COLOR[^\]]*|B|I)\]", "", str(item.get("label", "")), flags=re.I).strip()
    return item.get("filetype") == "directory" and bool(re.match(r"next\s+page", label, re.I))


def _unwrap_image(value):
    if isinstance(value, str) and value.startswith("image://"):
        return unquote(value[8:]).rstrip("/")
    return value


def normalise(files):
    out = []
    for item in files:
        if not isinstance(item, dict) or not item.get("file") or _next_page(item):
            continue
        item = dict(item)
        art = {k: _unwrap_image(v) for k, v in (item.get("art") or {}).items() if v}
        for key in ("thumbnail", "fanart"):
            if item.get(key):
                art.setdefault("thumb" if key == "thumbnail" else key, _unwrap_image(item.pop(key)))
            else:
                item.pop(key, None)
        item["art"] = art
        if isinstance(item.get("cast"), list):
            item["cast"] = [dict(c, thumbnail=_unwrap_image(c.get("thumbnail", ""))) for c in item["cast"][:MAX_CAST]]
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
        if len(out) >= MAX_ITEMS:
            break
    return out


def _next_page_url(source, current, item):
    """Accept only the same add-on route on a later page."""
    path = item.get("file")
    if not isinstance(path, str):
        return None
    try:
        validate_source(path)
    except ValueError:
        return None
    want, got = urlsplit(source), urlsplit(path)
    wq, gq = parse_qs(want.query), parse_qs(got.query)
    if got.netloc != want.netloc or path == current:
        return None
    for key in ("mode", "action", "info"):
        if wq.get(key) != gq.get(key):
            return None
    return path if gq.get("new_page") or gq.get("page") else None


def fetch(jsonrpc, source, pages=1):
    """Read the source directory through Kodi JSON-RPC. Raises on any failure."""
    return fetch_listing(jsonrpc, source, pages)[0]


def fetch_listing(jsonrpc, source, pages=1):
    """Read up to ``pages`` pages. Returns (items, has_more, next_page_art).

    Follows the add-on's own Next page item; any failed page raises so a
    partial refresh cannot replace the last complete listing. ``has_more`` says the add-on offered another page.
    """
    current, out, more, art = validate_source(source), [], False, None
    for _page in range(_clamp_pages(pages)):
        reply = jsonrpc("Files.GetDirectory", {"directory": current, "media": "video", "properties": FIELDS})
        if not isinstance(reply, dict) or reply.get("error") or not isinstance(reply.get("result"), dict):
            raise ValueError("Source directory could not be read")
        files = reply["result"].get("files")
        files = files if isinstance(files, list) else []
        seen = {item["file"] for item in out}
        out.extend(item for item in normalise(files) if item["file"] not in seen)
        nxt = [item for item in files if isinstance(item, dict) and _next_page(item)]
        current = _next_page_url(source, current, nxt[0]) if len(nxt) == 1 else None
        more = bool(current)
        if nxt and not art:
            item_art = nxt[0].get("art") or {}
            art = _unwrap_image(item_art.get("thumb") or item_art.get("icon") or nxt[0].get("thumbnail") or "") or None
        if not current or len(out) >= MAX_ITEMS:
            break
    return out[:MAX_ITEMS], more, art


def _digest(files):
    return hashlib.sha1(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


class WidgetCache:
    def __init__(self, root):
        self.root = root
        self.entries = os.path.join(root, "entries")
        self.queue = os.path.join(root, "queue")
        self.queued_pages = {}
        self.health_dir = os.path.join(root, "health")

    def _write(self, path, data, fsync=True):
        try:
            from .fsutil import atomic_write_json
        except ImportError:
            from fsutil import atomic_write_json
        atomic_write_json(path, data, fsync=fsync, separators=(",", ":"))

    def entry_path(self, source):
        return os.path.join(self.entries, cache_key(source) + ".json")

    def load(self, source):
        try:
            with open(self.entry_path(source), encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            return None
        return entry if isinstance(entry, dict) and entry.get("source") == source and isinstance(entry.get("files"), list) else None

    def save(self, source, files, now=None, pages=1, more=False, next_art=None):
        """Store a listing. Returns True when it differs from the previous one."""
        now = time.time() if now is None else now
        old = self.load(source)
        digest = _digest(files)
        self.record_success(source)
        self._write(self.entry_path(source), {"source": source, "fetched_at": now, "digest": digest,
                                              "pages": _clamp_pages(pages), "more": bool(more),
                                              "next_art": next_art,
                                              "content": content_for(source, files), "files": files})
        return old is None or old.get("digest") != digest

    def health(self, source):
        try:
            with open(os.path.join(self.health_dir, cache_key(source) + ".json"), encoding="utf-8") as fh:
                value = json.load(fh)
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def record_failure(self, source, now, reason="unavailable"):
        previous = self.health(source)
        failures = min(20, int(previous.get("failures", 0)) + 1)
        # The health file contains no provider URL, token, title or raw exception.
        self._write(os.path.join(self.health_dir, cache_key(source) + ".json"), {
            "failures": failures, "last_failure": now, "reason": reason,
            "retry_at": now + min(3600, 60 * 2 ** min(failures - 1, 6))}, fsync=False)

    def record_success(self, source):
        try:
            os.remove(os.path.join(self.health_dir, cache_key(source) + ".json"))
        except FileNotFoundError:
            pass

    def retry_ready(self, source, now):
        return now >= float(self.health(source).get("retry_at", 0))

    def is_stale(self, entry, now=None):
        now = time.time() if now is None else now
        return now - float(entry.get("fetched_at", 0)) > ttl_for(entry["source"])

    def touch(self, source, now=None):
        """Record use via the file mtime (cheap) at most once a day."""
        path = self.entry_path(source)
        now = time.time() if now is None else now
        try:
            if now - os.path.getmtime(path) > 86400:
                os.utime(path, (now, now))
        except OSError:
            pass

    def request(self, source, priority=False, pages=None):
        path = os.path.join(self.queue, cache_key(source) + ".json")
        if priority or pages or not os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    previous = json.load(fh)
            except (OSError, ValueError):
                previous = {}
            job = {"source": source, "priority": bool(priority or previous.get("priority")),
                   "at": previous.get("at", time.time())}
            pages = max(pages or 1, previous.get("pages", 1))
            if pages:
                job["pages"] = _clamp_pages(pages)
            self._write(path, job, fsync=False)  # A lost job is re-queued by the next sweep.

    def pages_for(self, source):
        """Pages to read when refreshing: whatever a row asked for, at least the default."""
        entry = self.load(source) or {}
        return max(self.queued_pages.get(source, 1), _clamp_pages(entry.get("pages", 1)), default_pages(source))

    def take_queue(self, limit=None, ready=None):
        """Claim eligible jobs in priority order; leave unselected files untouched."""
        try:
            names = [n for n in os.listdir(self.queue) if n.endswith(".json")]
        except OSError:
            return []
        jobs = []
        for name in names:
            path = os.path.join(self.queue, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    job = json.load(fh)
                if not isinstance(job, dict) or not isinstance(job.get("source"), str):
                    raise ValueError("Invalid queued job")
                jobs.append((job, path))
            except (OSError, ValueError):
                try:
                    os.remove(path)
                except OSError:
                    pass
        jobs.sort(key=lambda pair: (not pair[0].get("priority"), pair[0].get("at", 0)))
        seen, out = set(), []
        for job, path in jobs:
            source = job["source"]
            if source in seen or (ready is not None and not ready(source)):
                continue
            if limit is not None and len(out) >= limit:
                break
            try:
                os.remove(path)
            except OSError:
                continue
            if job.get("pages"):
                self.queued_pages[source] = max(self.queued_pages.get(source, 1), _clamp_pages(job["pages"]))
            seen.add(source)
            out.append(source)
        return out

    def all_entries(self):
        try:
            names = sorted(n for n in os.listdir(self.entries) if n.endswith(".json"))
        except OSError:
            return []
        out = []
        for name in names:
            path = os.path.join(self.entries, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    entry = json.load(fh)
                entry["_used_at"] = os.path.getmtime(path)
            except (OSError, ValueError):
                continue
            if isinstance(entry, dict) and isinstance(entry.get("source"), str):
                out.append(entry)
        return out

    def queue_stale(self, now=None, progress_only=False, everything=False):
        count = 0
        for entry in self.all_entries():
            progress = is_progress(entry["source"])
            if progress_only and not progress:
                continue
            if everything or progress_only or self.is_stale(entry, now):
                self.request(entry["source"], priority=progress)
                count += 1
        return count

    def prune(self, now=None):
        now = time.time() if now is None else now
        removed = 0
        for entry in self.all_entries():
            if now - max(entry["_used_at"], float(entry.get("fetched_at", 0))) > PRUNE_AFTER:
                try:
                    os.remove(self.entry_path(entry["source"]))
                    removed += 1
                except OSError:
                    pass
        return removed

    def status(self, now=None):
        now = time.time() if now is None else now
        rows = []
        for entry in self.all_entries():
            rows.append({"source": entry["source"], "items": len(entry.get("files", [])),
                         "age_seconds": int(now - float(entry.get("fetched_at", 0))),
                         "stale": self.is_stale(entry, now), "progress": is_progress(entry["source"]),
                         "health": self.health(entry["source"])})
        try:
            queued = len([n for n in os.listdir(self.queue) if n.endswith(".json")])
        except OSError:
            queued = 0
        return {"root": self.root, "entries": rows, "queued": queued}


_INFO_KEYS = {"title": "title", "year": "year", "mpaa": "mpaa", "plot": "plot", "tagline": "tagline",
              "originaltitle": "originaltitle", "imdbnumber": "imdbnumber", "premiered": "premiered",
              "firstaired": "aired", "trailer": "trailer", "lastplayed": "lastplayed",
              "dateadded": "dateadded", "playcount": "playcount", "showtitle": "tvshowtitle",
              "runtime": "duration", "genre": "genre", "director": "director", "writer": "writer",
              "studio": "studio", "country": "country", "tag": "tag"}


def _set_info(xbmc, li, item, kind):
    """JSON-RPC item fields to ListItem metadata on Kodi 19 and 20+ (see kodi_compat)."""
    try:
        from .kodi_compat import set_video_info
    except ImportError:
        from kodi_compat import set_video_info
    info = {label: item[key] for key, label in _INFO_KEYS.items() if key in item}
    for key in ("season", "episode"):
        if isinstance(item.get(key), int) and item[key] >= 0:
            info[key] = item[key]
    if kind:
        info["mediatype"] = kind
    rating = votes = None
    if item.get("rating"):
        try:
            rating = float(item["rating"])
            votes = int(str(item.get("votes", 0)).replace(",", "") or 0)
        except (TypeError, ValueError):
            rating = None
    unique_ids = item.get("uniqueid") if isinstance(item.get("uniqueid"), dict) else None
    set_video_info(li, info, resume=item.get("resume") or {}, unique_ids=unique_ids, default_id="tmdb",
                   rating=rating, votes=votes, cast=item.get("cast") if isinstance(item.get("cast"), list) else None,
                   actor=getattr(xbmc, "Actor", None))


def render(xbmc, xbmcgui, xbmcplugin, handle, entry, today=None, helper_playable=True,
           hide_watched=False, view_more=None, limit=0, view_more_art=None):
    content = entry.get("content") or content_for(entry["source"], entry["files"])
    xbmcplugin.setContent(handle, content)
    today = today or time.strftime("%Y-%m-%d")
    try:
        from .item_actions import item_actions
    except ImportError:
        from item_actions import item_actions
    items = []
    for item in entry["files"]:
        if hide_watched and int(item.get("playcount") or 0) > 0:
            continue
        url = item["file"]
        folder = item.get("filetype") == "directory"
        kind = media_type(item, content)
        li = xbmcgui.ListItem(label=item.get("label") or item.get("title") or "", path=url, offscreen=True)
        _set_info(xbmc, li, item, kind)
        li.setArt(item.get("art") or {})
        props, context = item_actions(item, kind, entry["source"])
        extra, playable = helper_item(item, entry["source"])
        playable = playable and helper_playable
        props.update(extra)
        resume = item.get("resume") or {}
        if resume.get("position") and resume.get("total"):
            props["watchedprogress"] = str(int(100 * float(resume["position"]) / float(resume["total"])))
        if str(item.get("lastplayed", ""))[:10] == today:
            props["km_watched_today"] = "true"
        if props:
            li.setProperties(props)
        if context:
            li.addContextMenuItems(context)
        # Like the source add-on: folders browse; POV leaves run POV's own play
        # route (never playable); TMDb Helper play leaves resolve a URL.
        if playable and not folder:
            li.setProperty("IsPlayable", "true")
        items.append((url, li, folder))
    if view_more and limit > 1 and len(items) > limit - 1:
        # The skin shows at most ``limit`` items: keep room for View more.
        items = items[:limit - 1]
    if view_more and (items or entry.get("more")):
        li = xbmcgui.ListItem(label="View more", path=view_more, offscreen=True)
        art = view_more_art or (POV_NEXT_ART if urlsplit(view_more).netloc == "plugin.video.pov" else "DefaultFolder.png")
        li.setArt({"thumb": art, "poster": art, "icon": art})
        li.setProperties({"specialsort": "bottom", "km_view_more": "true"})
        items.append((view_more, li, True))
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


def helper_resolves(source):
    """TMDb Helper marks play items playable unless "only resolve strm" is on."""
    helper = urlsplit(source).netloc
    if helper not in TMDB_HELPERS:
        return True
    try:
        import xbmcaddon
        return xbmcaddon.Addon(helper).getSetting("only_resolve_strm") != "true"
    except Exception:
        return True


def skin_widget_limit(xbmc, configured=0):
    """Most items a skin shows in one row (0 = no known limit).

    The "Row item limit" setting wins; otherwise use Bingie's
    Skin.String(WidgetsGlobalLimit) when the skin defines it.
    """
    try:
        if int(configured or 0) > 0:
            return int(configured)
    except (TypeError, ValueError):
        pass
    try:
        return int(xbmc.getInfoLabel("Skin.String(WidgetsGlobalLimit)") or 0)
    except (ValueError, TypeError, AttributeError):
        return 0


def configured_row_limit():
    try:
        import xbmcaddon
        return int(xbmcaddon.Addon("service.kodi.addonadmin").getSetting("widget_row_limit") or 0)
    except Exception:
        return 0


def jsonrpc_via(xbmc):
    def call(method, params=None):
        return json.loads(xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})))
    return call


def cache_root(xbmcvfs):
    return xbmcvfs.translatePath("special://profile/addon_data/service.kodi.addonadmin/widget_cache")


def serve(argv, xbmc, xbmcgui, xbmcplugin, xbmcvfs):
    handle = int(argv[1])
    cache = source = None
    try:
        query = parse_qs(argv[2].lstrip("?"))
        source = validate_source(query.get("source", [""])[0])
        pages, hide_watched = row_options(query)
        cache = WidgetCache(cache_root(xbmcvfs))
        entry = cache.load(source)
        if entry is None:
            files, more, next_art = fetch_listing(jsonrpc_via(xbmc), source, pages)
            entry = {"source": source, "files": files, "content": content_for(source, files),
                     "more": more, "next_art": next_art}
            try:
                cache.save(source, files, pages=pages, more=more, next_art=next_art)
            except OSError:
                pass
        else:
            if _clamp_pages(entry.get("pages", 1)) < pages:
                cache.request(source, priority=True, pages=pages)
            elif cache.is_stale(entry):
                cache.request(source, priority=True)
            cache.touch(source)
        render(xbmc, xbmcgui, xbmcplugin, handle, entry, helper_playable=helper_resolves(source),
               hide_watched=hide_watched, view_more=view_more_url(source, entry.get("more")),
               limit=skin_widget_limit(xbmc, configured_row_limit()), view_more_art=entry.get("next_art"))
    except Exception as exc:
        if cache is not None and source is not None:
            try:
                cache.record_failure(source, time.time())
                cache.request(source, priority=True)
            except OSError:
                pass
        xbmc.log("Kodi Manager widget cache: %s" % type(exc).__name__, xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


class Refresher:
    """Background, one-at-a-time refresh of queued widget rows (service side).

    Refreshing runs the source add-on (often POV) once per row, so it only
    happens while the TV is quiet: nothing playing, no busy or progress dialog
    (POV searching for sources) and no remote presses for a while. A failed or
    very short playback does not trigger a full refresh, and full refreshes
    are rate-limited.
    """

    EVERYTHING_EVERY = 30 * 60   # at most one full refresh per 30 minutes
    SHORT_PLAYBACK = 120         # seconds; shorter plays are treated as failed starts
    MAX_ROWS_PER_TICK = 2
    WORK_BUDGET = 10
    BATCH_PAUSE = 10
    ROW_PAUSE = 1.5              # seconds between rows so Kodi stays responsive

    def __init__(self, cache, jsonrpc, is_playing, bump, log=lambda msg: None, clock=time.time,
                 external_reload=lambda: "", is_busy=lambda: False, sleep=None):
        self.cache, self.jsonrpc, self.is_playing, self.bump, self.log, self.clock = cache, jsonrpc, is_playing, bump, log, clock
        self.is_busy = is_busy
        self.sleep = sleep or (lambda seconds: None)
        self.next_work = clock()
        self.next_sweep = clock() + 20
        self.after_playback = []
        self.playback_started_at = None
        self.last_everything = float("-inf")
        # Add-ons such as TMDb Helper bump their own reload property after a
        # Trakt sync; follow it so personal rows refresh at the same time.
        self.external_reload = external_reload
        self.last_external = None

    def playback_started(self):
        self.playback_started_at = self.clock()

    def playback_stopped(self):
        now = self.clock()
        started, self.playback_started_at = self.playback_started_at, None
        if started is not None and now - started < self.SHORT_PLAYBACK:
            # A failed start or a quick back-out: watched state barely changed.
            self.after_playback = [(now + 5, "progress")]
            return
        # Progress rows first (POV updates its local state on stop), then
        # again plus everything else once Trakt has had time to sync.
        self.after_playback = [(now + 5, "progress"), (now + 120, "everything")]

    def _quiet(self):
        try:
            return not self.is_playing() and not self.is_busy()
        except Exception:
            return False

    def tick(self, should_stop=lambda: False):
        now = self.clock()
        if not self._quiet() or now < self.next_work:
            return 0
        token = self.external_reload()
        if token != self.last_external:
            if self.last_external is not None:
                self.cache.queue_stale(now, progress_only=True)
            self.last_external = token
        due = [kind for at, kind in self.after_playback if at <= now]
        self.after_playback = [(at, kind) for at, kind in self.after_playback if at > now]
        for kind in due:
            if kind == "everything":
                if now - self.last_everything < self.EVERYTHING_EVERY:
                    kind = "stale"
                else:
                    self.last_everything = now
            self.cache.queue_stale(now, progress_only=kind == "progress", everything=kind == "everything")
        if now >= self.next_sweep:
            self.next_sweep = now + 300
            self.cache.queue_stale(now)
            self.cache.prune(now)
        changed = done = attempted = 0
        started = self.clock()
        first = True
        for source in self.cache.take_queue(limit=self.MAX_ROWS_PER_TICK,
                                                 ready=lambda value: self.cache.retry_ready(value, self.clock())):
            if (should_stop() or not self._quiet() or attempted >= self.MAX_ROWS_PER_TICK
                    or self.clock() - started >= self.WORK_BUDGET
                    or not self.cache.retry_ready(source, self.clock())):
                self.cache.request(source, priority=is_progress(source))
                continue
            if not first:
                self.sleep(self.ROW_PAUSE)
            first = False
            if should_stop() or not self._quiet():
                self.cache.request(source, priority=is_progress(source))
                continue
            try:
                attempted += 1
                validate_source(source)
                pages = self.cache.pages_for(source)
                files, more, next_art = fetch_listing(self.jsonrpc, source, pages)
                previous = self.cache.load(source)
                if not files and previous and previous.get("files") and not is_progress(source):
                    # Many providers report a failed fetch as a successful empty directory.
                    # Do not erase useful discovery rows on that ambiguous result.
                    self.cache.record_failure(source, self.clock(), "unexpected_empty")
                    self.cache.request(source)
                    continue
                changed += bool(self.cache.save(source, files, self.clock(), pages=pages, more=more, next_art=next_art))
                done += 1
            except Exception as exc:
                self.cache.record_failure(source, self.clock())
                self.cache.request(source, priority=is_progress(source))
                self.log("Widget refresh failed (%s); preserving cached row" % type(exc).__name__)
        if attempted:
            self.next_work = self.clock() + self.BATCH_PAUSE
        if changed:
            self.bump(str(int(self.clock())))
            self.log("Widget cache refreshed %d rows, %d changed" % (done, changed))
        return done
