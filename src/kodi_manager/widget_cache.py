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

_ACTION_RE = re.compile(r"(?:^|[./_ -])(?:play\w*|resolve\w*|execute\w*|run|auth\w*|logout|delete\w*|remove\w*|set\w*|tools|search\w*|scrape\w*|clear\w*|download\w*|install\w*|uninstall\w*|reset\w*|sync\w*|update\w*|mark\w*|manager\w*)(?:$|[./_ -])", re.I)
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
    """Accept only browseable video add-on directories, never action endpoints."""
    if not isinstance(source, str) or not source or len(source) > 12000 or any(ord(c) < 32 for c in source):
        raise ValueError("Invalid source directory URL")
    parsed = urlsplit(source)
    if parsed.scheme != "plugin" or not re.fullmatch(r"plugin\.video\.[A-Za-z0-9_.-]+", parsed.netloc) or parsed.fragment:
        raise ValueError("Source must be a video add-on directory URL")
    if parsed.path not in ("", "/") and _ACTION_RE.search(unquote(parsed.path).strip("/")):
        raise ValueError("Action endpoints cannot be cached")
    for key, values in parse_qs(parsed.query).items():
        if key.lower() in ("mode", "action", "info", "do", "command") and any(
                _ACTION_RE.search(unquote(v)) and not unquote(v).startswith("build_") for v in values):
            raise ValueError("Action endpoints cannot be cached")
    return source


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
    """Movie/show lists (not progress rows, seasons or episodes)."""
    parsed = urlsplit(source)
    query = parse_qs(parsed.query)
    if is_progress(source):
        return False
    if parsed.netloc == "plugin.video.pov":
        return query.get("mode", [""])[0] in _LIST_MODES
    if parsed.netloc in TMDB_HELPERS:
        return query.get("widget") == ["true"] or query.get("info") == ["trakt_userlist"]
    return False


def default_pages(source):
    """POV lists show 20 items per page; read two so rows are not sparse."""
    return 2 if urlsplit(source).netloc == "plugin.video.pov" and is_list_row(source) else 1


def view_more_url(source):
    """The full, paged listing behind a row, or None for rows without one."""
    if not is_list_row(source):
        return None
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
    """Read the source directory through Kodi JSON-RPC. Raises on any failure.

    With ``pages`` > 1, follows the add-on's own Next page item. A failure on a
    later page keeps the pages already read.
    """
    current, out = validate_source(source), []
    for page in range(_clamp_pages(pages)):
        reply = jsonrpc("Files.GetDirectory", {"directory": current, "media": "video", "properties": FIELDS})
        if not isinstance(reply, dict) or reply.get("error") or not isinstance(reply.get("result"), dict):
            if page:
                break
            raise ValueError("Source directory could not be read")
        files = reply["result"].get("files")
        files = files if isinstance(files, list) else []
        seen = {item["file"] for item in out}
        out.extend(item for item in normalise(files) if item["file"] not in seen)
        nxt = [item for item in files if isinstance(item, dict) and _next_page(item)]
        current = _next_page_url(source, current, nxt[0]) if len(nxt) == 1 else None
        if not current or len(out) >= MAX_ITEMS:
            break
    return out[:MAX_ITEMS]


def _digest(files):
    return hashlib.sha1(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


class WidgetCache:
    def __init__(self, root):
        self.root = root
        self.entries = os.path.join(root, "entries")
        self.queue = os.path.join(root, "queue")
        self.queued_pages = {}

    def _write(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        os.replace(tmp, path)

    def entry_path(self, source):
        return os.path.join(self.entries, cache_key(source) + ".json")

    def load(self, source):
        try:
            with open(self.entry_path(source), encoding="utf-8") as fh:
                entry = json.load(fh)
        except (OSError, ValueError):
            return None
        return entry if isinstance(entry, dict) and entry.get("source") == source and isinstance(entry.get("files"), list) else None

    def save(self, source, files, now=None, pages=1):
        """Store a listing. Returns True when it differs from the previous one."""
        now = time.time() if now is None else now
        old = self.load(source)
        digest = _digest(files)
        self._write(self.entry_path(source), {"source": source, "fetched_at": now, "digest": digest,
                                              "pages": _clamp_pages(pages),
                                              "content": content_for(source, files), "files": files})
        return old is None or old.get("digest") != digest

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
            job = {"source": source, "priority": bool(priority), "at": time.time()}
            if pages:
                job["pages"] = _clamp_pages(pages)
            self._write(path, job)

    def pages_for(self, source):
        """Pages to read when refreshing: whatever a row asked for, at least the default."""
        entry = self.load(source) or {}
        return max(self.queued_pages.get(source, 1), _clamp_pages(entry.get("pages", 1)), default_pages(source))

    def take_queue(self):
        """Remove and return queued sources, priority (progress) rows first."""
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
                os.remove(path)
            except (OSError, ValueError):
                continue
            if isinstance(job, dict) and isinstance(job.get("source"), str):
                jobs.append(job)
        jobs.sort(key=lambda j: (not j.get("priority"), j.get("at", 0)))
        for job in jobs:
            if job.get("pages"):
                self.queued_pages[job["source"]] = max(self.queued_pages.get(job["source"], 1), _clamp_pages(job["pages"]))
        seen, out = set(), []
        for job in jobs:
            if job["source"] not in seen:
                seen.add(job["source"])
                out.append(job["source"])
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
                         "stale": self.is_stale(entry, now), "progress": is_progress(entry["source"])})
        try:
            queued = len([n for n in os.listdir(self.queue) if n.endswith(".json")])
        except OSError:
            queued = 0
        return {"root": self.root, "entries": rows, "queued": queued}


def _set_info(xbmc, li, item, kind):
    tag = li.getVideoInfoTag()
    simple = {"title": "setTitle", "year": "setYear", "mpaa": "setMpaa", "plot": "setPlot",
              "tagline": "setTagLine", "originaltitle": "setOriginalTitle", "imdbnumber": "setIMDBNumber",
              "premiered": "setPremiered", "firstaired": "setFirstAired", "trailer": "setTrailer",
              "lastplayed": "setLastPlayed", "dateadded": "setDateAdded", "playcount": "setPlaycount",
              "showtitle": "setTvShowTitle", "runtime": "setDuration"}
    lists = {"genre": "setGenres", "director": "setDirectors", "writer": "setWriters",
             "studio": "setStudios", "country": "setCountries", "tag": "setTags"}
    for key, name in simple.items():
        if key in item:
            try:
                getattr(tag, name)(item[key])
            except (TypeError, ValueError, AttributeError):
                pass
    for key, name in lists.items():
        if key in item:
            value = item[key] if isinstance(item[key], list) else [item[key]]
            try:
                getattr(tag, name)([str(v) for v in value if v])
            except (TypeError, AttributeError):
                pass
    for key, name in (("season", "setSeason"), ("episode", "setEpisode")):
        if isinstance(item.get(key), int) and item[key] >= 0:
            getattr(tag, name)(item[key])
    if kind:
        tag.setMediaType(kind)
    if item.get("rating"):
        try:
            tag.setRating(float(item["rating"]), int(str(item.get("votes", 0)).replace(",", "") or 0), "", True)
        except (TypeError, ValueError):
            pass
    if isinstance(item.get("uniqueid"), dict) and item["uniqueid"]:
        ids = {str(k): str(v) for k, v in item["uniqueid"].items() if v}
        tag.setUniqueIDs(ids, "tmdb" if "tmdb" in ids else next(iter(ids)))
    resume = item.get("resume") or {}
    if resume.get("position"):
        tag.setResumePoint(float(resume["position"]), float(resume.get("total") or 0))
    if item.get("cast") and hasattr(xbmc, "Actor"):
        try:
            tag.setCast([xbmc.Actor(c.get("name", ""), c.get("role", ""), int(c.get("order", i)), c.get("thumbnail", ""))
                         for i, c in enumerate(item["cast"])])
        except (TypeError, ValueError):
            pass


def render(xbmc, xbmcgui, xbmcplugin, handle, entry, today=None, helper_playable=True,
           hide_watched=False, view_more=None):
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
    if view_more:
        li = xbmcgui.ListItem(label="View more", path=view_more, offscreen=True)
        art = POV_NEXT_ART
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


def jsonrpc_via(xbmc):
    def call(method, params=None):
        return json.loads(xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})))
    return call


def cache_root(xbmcvfs):
    return xbmcvfs.translatePath("special://profile/addon_data/service.kodi.addonadmin/widget_cache")


def serve(argv, xbmc, xbmcgui, xbmcplugin, xbmcvfs):
    handle = int(argv[1])
    try:
        query = parse_qs(argv[2].lstrip("?"))
        source = validate_source(query.get("source", [""])[0])
        pages, hide_watched = row_options(query)
        cache = WidgetCache(cache_root(xbmcvfs))
        entry = cache.load(source)
        if entry is None:
            files = fetch(jsonrpc_via(xbmc), source, pages)
            entry = {"source": source, "files": files, "content": content_for(source, files)}
            try:
                cache.save(source, files, pages=pages)
            except OSError:
                pass
        else:
            if _clamp_pages(entry.get("pages", 1)) < pages:
                cache.request(source, priority=is_progress(source), pages=pages)
            elif cache.is_stale(entry):
                cache.request(source, priority=is_progress(source))
            cache.touch(source)
        render(xbmc, xbmcgui, xbmcplugin, handle, entry, helper_playable=helper_resolves(source),
               hide_watched=hide_watched, view_more=view_more_url(source))
    except Exception as exc:
        xbmc.log("Kodi Manager widget cache: %s" % type(exc).__name__, xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


class Refresher:
    """Background, one-at-a-time refresh of queued widget rows (service side)."""

    def __init__(self, cache, jsonrpc, is_playing, bump, log=lambda msg: None, clock=time.time,
                 external_reload=lambda: ""):
        self.cache, self.jsonrpc, self.is_playing, self.bump, self.log, self.clock = cache, jsonrpc, is_playing, bump, log, clock
        self.next_sweep = clock() + 20
        self.after_playback = []
        # Add-ons such as TMDb Helper bump their own reload property after a
        # Trakt sync; follow it so personal rows refresh at the same time.
        self.external_reload = external_reload
        self.last_external = None

    def playback_stopped(self):
        now = self.clock()
        # Progress rows first (POV updates its local state on stop), then
        # again plus everything else once Trakt has had time to sync.
        self.after_playback = [(now + 5, "progress"), (now + 120, "everything")]

    def tick(self, should_stop=lambda: False):
        now = self.clock()
        if self.is_playing():
            return 0
        token = self.external_reload()
        if token != self.last_external:
            if self.last_external is not None:
                self.cache.queue_stale(now, progress_only=True)
            self.last_external = token
        due = [kind for at, kind in self.after_playback if at <= now]
        self.after_playback = [(at, kind) for at, kind in self.after_playback if at > now]
        for kind in due:
            self.cache.queue_stale(now, progress_only=kind == "progress", everything=kind == "everything")
        if now >= self.next_sweep:
            self.next_sweep = now + 300
            self.cache.queue_stale(now)
            self.cache.prune(now)
        changed = done = 0
        for source in self.cache.take_queue():
            if should_stop() or self.is_playing():
                self.cache.request(source, priority=is_progress(source))
                continue
            try:
                validate_source(source)
                pages = self.cache.pages_for(source)
                changed += bool(self.cache.save(source, fetch(self.jsonrpc, source, pages), self.clock(), pages=pages))
                done += 1
            except Exception as exc:
                self.log("Widget refresh failed (%s)" % type(exc).__name__)
        if changed:
            self.bump(str(int(self.clock())))
            self.log("Widget cache refreshed %d rows, %d changed" % (done, changed))
        return done
