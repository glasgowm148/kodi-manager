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
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

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
_PROGRESS_ACTIONS = {"in_progress_movies", "in_progress_tvshows", "trakt_recommendations"}
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


def cache_url(source, reload=True):
    params = {"mode": "cached", "source": validate_source(source)}
    url = PLUGIN_URL + "?" + urlencode(params)
    return url + "&reload=" + RELOAD_INFO if reload else url


def source_from_cache_url(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if parsed.netloc != "service.kodi.addonadmin" or query.get("mode") != ["cached"]:
        return None
    return query.get("source", [None])[0]


def _route(source):
    query = parse_qs(urlsplit(source).query)
    return query.get("mode", [""])[0], query.get("action", [""])[0]


def is_progress(source):
    mode, action = _route(source)
    return mode in _PROGRESS_MODES or action in _PROGRESS_ACTIONS


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


def fetch(jsonrpc, source):
    """Read the source directory through Kodi JSON-RPC. Raises on any failure."""
    reply = jsonrpc("Files.GetDirectory", {"directory": validate_source(source), "media": "video", "properties": FIELDS})
    if not isinstance(reply, dict) or reply.get("error") or not isinstance(reply.get("result"), dict):
        raise ValueError("Source directory could not be read")
    files = reply["result"].get("files")
    return normalise(files if isinstance(files, list) else [])


def _digest(files):
    return hashlib.sha1(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


class WidgetCache:
    def __init__(self, root):
        self.root = root
        self.entries = os.path.join(root, "entries")
        self.queue = os.path.join(root, "queue")

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

    def save(self, source, files, now=None):
        """Store a listing. Returns True when it differs from the previous one."""
        now = time.time() if now is None else now
        old = self.load(source)
        digest = _digest(files)
        self._write(self.entry_path(source), {"source": source, "fetched_at": now, "digest": digest,
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

    def request(self, source, priority=False):
        path = os.path.join(self.queue, cache_key(source) + ".json")
        if priority or not os.path.exists(path):
            self._write(path, {"source": source, "priority": bool(priority), "at": time.time()})

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


def render(xbmc, xbmcgui, xbmcplugin, handle, entry, today=None):
    content = entry.get("content") or content_for(entry["source"], entry["files"])
    xbmcplugin.setContent(handle, content)
    today = today or time.strftime("%Y-%m-%d")
    try:
        from .item_actions import item_actions
    except ImportError:
        from item_actions import item_actions
    items = []
    for item in entry["files"]:
        url = item["file"]
        folder = item.get("filetype") == "directory"
        kind = media_type(item, content)
        li = xbmcgui.ListItem(label=item.get("label") or item.get("title") or "", path=url, offscreen=True)
        _set_info(xbmc, li, item, kind)
        li.setArt(item.get("art") or {})
        props, context = item_actions(item, kind, entry["source"])
        resume = item.get("resume") or {}
        if resume.get("position") and resume.get("total"):
            props["watchedprogress"] = str(int(100 * float(resume["position"]) / float(resume["total"])))
        if str(item.get("lastplayed", ""))[:10] == today:
            props["km_watched_today"] = "true"
        if props:
            li.setProperties(props)
        if context:
            li.addContextMenuItems(context)
        # Like the source add-on: folders browse, leaf items run the add-on's
        # own play route. Never mark them playable (they don't resolve URLs).
        items.append((url, li, folder))
    xbmcplugin.addDirectoryItems(handle, items, len(items))
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


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
        cache = WidgetCache(cache_root(xbmcvfs))
        entry = cache.load(source)
        if entry is None:
            files = fetch(jsonrpc_via(xbmc), source)
            entry = {"source": source, "files": files, "content": content_for(source, files)}
            try:
                cache.save(source, files)
            except OSError:
                pass
        else:
            if cache.is_stale(entry):
                cache.request(source, priority=is_progress(source))
            cache.touch(source)
        render(xbmc, xbmcgui, xbmcplugin, handle, entry)
    except Exception as exc:
        xbmc.log("Kodi Manager widget cache: %s" % type(exc).__name__, xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


class Refresher:
    """Background, one-at-a-time refresh of queued widget rows (service side)."""

    def __init__(self, cache, jsonrpc, is_playing, bump, log=lambda msg: None, clock=time.time):
        self.cache, self.jsonrpc, self.is_playing, self.bump, self.log, self.clock = cache, jsonrpc, is_playing, bump, log, clock
        self.next_sweep = clock() + 20
        self.after_playback = []

    def playback_stopped(self):
        now = self.clock()
        # Progress rows first (POV updates its local state on stop), then
        # again plus everything else once Trakt has had time to sync.
        self.after_playback = [(now + 5, "progress"), (now + 120, "everything")]

    def tick(self, should_stop=lambda: False):
        now = self.clock()
        if self.is_playing():
            return 0
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
                changed += bool(self.cache.save(source, fetch(self.jsonrpc, source), self.clock()))
                done += 1
            except Exception as exc:
                self.log("Widget refresh failed (%s)" % type(exc).__name__)
        if changed:
            self.bump(str(int(self.clock())))
            self.log("Widget cache refreshed %d rows, %d changed" % (done, changed))
        return done
