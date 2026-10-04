"""Kodi plugin entry point for a family-filtered, observed source directory.

URL: plugin://service.kodi.addonadmin/?mode=family&source=<encoded URL>
     &max_rating=12A&family_only=true
No providers are fabricated; results keep the source add-on's original URLs.
"""
import json
import re
import sys
from datetime import datetime
from urllib.parse import parse_qs, urlsplit, unquote, urlencode

try:
    from .widget_filters import filter_items
except ImportError:
    from widget_filters import filter_items

_ACTION_RE = re.compile(r"(?:^|[./_ -])(?:play\w*|resolve\w*|execute\w*|run|auth\w*|logout|delete\w*|remove\w*|set\w*|tools|search\w*|scrape\w*|clear\w*|download\w*|install\w*|uninstall\w*|reset\w*|sync\w*|update\w*)(?:$|[./_ -])", re.I)
_PROGRESS_ROUTES = {('build_tvshow_list', 'in_progress_tvshows'),
                    ('build_continue_episode', ''), ('build_next_episode', ''), ('build_in_progress_episode', '')}
_MAX_PROGRESS_PAGES = 6
_MAX_PROGRESS_ITEMS = 600


def _progress_route(source):
    parsed = urlsplit(source)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if parsed.netloc != 'plugin.video.pov' or parsed.path not in ('', '/') or len(query.get('mode', [])) != 1 or len(query.get('action', [''])) != 1:
        return None
    route = (query['mode'][0], query.get('action', [''])[0])
    return route if route in _PROGRESS_ROUTES else None


def _next_page_item(item):
    if not isinstance(item, dict) or item.get('filetype') != 'directory':
        return False
    label = re.sub(r'\[/?(?:COLOR[^\]]*|B|I)\]', '', str(item.get('label', '')), flags=re.I).strip()
    return bool(re.fullmatch(r'next\s+page(?:\s*[>»→]+(?:\s*\d+\s*[<«←]+)?)?', label, re.I))


def _next_progress_page(index, original, current, candidate, visited):
    path = candidate.get('file', '')
    if not isinstance(path, str):
        return None, 'unsafe_next_page'
    if path in visited:
        return None, 'pagination_loop'
    try:
        validate_source(index, path)
        if _progress_route(path) != _progress_route(original):
            return None, 'unsafe_next_page'
        query = parse_qs(urlsplit(path).query, keep_blank_values=True)
        original_query = parse_qs(urlsplit(original).query, keep_blank_values=True)
        current_query = parse_qs(urlsplit(current).query, keep_blank_values=True)
        if set(query) - (set(original_query) | {'new_page', 'exit_list_params', 'name'}):
            return None, 'unsafe_next_page'
        page = query.get('new_page', [])
        if len(page) != 1 or not page[0].isdigit() or int(page[0]) != int(current_query.get('new_page', ['1'])[0]) + 1:
            return None, 'unsafe_next_page'
    except (ValueError, TypeError, IndexError):
        return None, 'unsafe_next_page'
    return path, ''


def validate_source(index, source):
    if not isinstance(source, str) or not source or len(source) > 12000 or any(ord(c) < 32 for c in source):
        raise ValueError("Invalid source directory URL")
    parsed = urlsplit(source)
    aid = parsed.netloc
    if parsed.scheme != "plugin" or not re.fullmatch(r"plugin\.video\.[A-Za-z0-9_.-]+", aid) or parsed.fragment:
        raise ValueError("Source must be an installed video add-on directory URL")
    if parsed.path not in ("", "/") and _ACTION_RE.search(unquote(parsed.path).strip("/")):
        raise ValueError("Playback or action endpoints cannot be directory sources")
    for key, values in parse_qs(parsed.query).items():
        if key.lower() in ("mode", "action", "info", "do", "command") and any(_ACTION_RE.search(unquote(value)) for value in values):
            raise ValueError("Playback or action endpoints cannot be directory sources")
        if key.casefold() == "isfolder" and any(value.casefold() == "false" for value in values):
            raise ValueError("This item is not a browseable folder")
    addon = index.get(aid)
    if not addon or addon.get("installed") is not True or addon.get("enabled") is not True:
        raise ValueError("Source video add-on must be installed and enabled")
    return source


def collect_family_directory(kodi, index, source, max_rating="12A", family_only=True):
    source = validate_source(index, source)
    # Validate filter inputs before invoking a source add-on.
    filter_items([], max_rating, family_only)
    eligible = _progress_route(source) is not None
    current, visited, files, seen_paths, pages, truncated, reason = source, set(), [], set(), 0, False, ''
    while True:
        visited.add(current)
        reply = kodi.jsonrpc("Files.GetDirectory", {
            "directory": current, "media": "video",
            "properties": ["title", "genre", "year", "mpaa", "plot", "thumbnail", "fanart", "art", "showtitle", "season", "episode", "playcount", "lastplayed", "resume"],
        })
        if not isinstance(reply, dict) or reply.get("error"):
            raise ValueError("Source directory could not be read")
        directory = reply.get("result")
        if not isinstance(directory, dict) or not isinstance(directory.get("files"), list):
            raise ValueError("Source returned no directory listing")
        pages += 1
        controls = [item for item in directory['files'] if _next_page_item(item)]
        data = [item for item in directory['files'] if not _next_page_item(item)]
        for item in data:
            path = item.get('file') if isinstance(item, dict) else None
            path = path if isinstance(path, str) else None
            if eligible and path and path in seen_paths:
                continue
            if eligible and len(files) >= _MAX_PROGRESS_ITEMS:
                truncated, reason = True, 'item_limit'
                break
            if path:
                seen_paths.add(path)
            files.append(item)
        if truncated or not controls:
            break
        if not eligible:
            break
        if pages >= _MAX_PROGRESS_PAGES or len(files) >= _MAX_PROGRESS_ITEMS:
            truncated, reason = True, 'page_limit' if pages >= _MAX_PROGRESS_PAGES else 'item_limit'
            break
        if len(controls) != 1:
            truncated, reason = True, 'ambiguous_next_page'
            break
        next_path, reason = _next_progress_page(index, source, current, controls[0], visited)
        if next_path is None:
            truncated = True
            break
        current = next_path
    result = filter_items(files, max_rating, family_only)
    result["source"] = source
    result['pagination'] = {'eligible': eligible, 'pages_read': pages, 'items_read': len(files),
                            'truncated': truncated, 'reason': reason,
                            'max_pages': _MAX_PROGRESS_PAGES if eligible else 1,
                            'max_items': _MAX_PROGRESS_ITEMS if eligible else None}
    return result


def family_directory_url(source, max_rating="12A", family_only=True):
    """Retain the filter when entering a TV show/season folder."""
    filter_items([], max_rating, family_only)
    return "plugin://service.kodi.addonadmin/?" + urlencode({
        "mode": "family", "source": source, "max_rating": max_rating,
        "family_only": "true" if family_only else "false"})


def _media_type(item):
    metadata = item.get("info") or {}
    metadata = metadata.get("video", metadata) if isinstance(metadata, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    kind = item.get("mediatype") or metadata.get("mediatype") or item.get("type")
    if kind in ("movie", "tvshow", "season", "episode", "musicvideo"):
        return kind
    # JSON-RPC reports plugin seasons as 'unknown'. Negative episode numbers
    # are also used for movies, so they must not classify those as episodes.
    season, episode = item.get("season", -1), item.get("episode", -1)
    if isinstance(episode, int) and episode >= 0:
        return "episode"
    if isinstance(season, int) and season >= 0 and item.get("filetype") == "directory":
        return "season"
    return None


def directory_content(result):
    """Preserve the media content Kodi needs to select Bingie's TV views."""
    parsed = urlsplit(result.get("source", ""))
    query = parse_qs(parsed.query)
    if parsed.netloc == "plugin.video.pov":
        content = {"build_season_list": "seasons", "build_episode_list": "episodes",
                   "build_continue_episode": "episodes", "build_next_episode": "episodes", "build_in_progress_episode": "episodes",
                   "build_movie_list": "movies", "build_tvshow_list": "tvshows"}.get(query.get("mode", [""])[0])
        if content:
            return content
    kinds = {_media_type(item) for item in result["files"]}
    if len(kinds) == 1:
        return {"movie": "movies", "tvshow": "tvshows", "season": "seasons",
                "episode": "episodes", "musicvideo": "musicvideos"}.get(kinds.pop(), "videos")
    return "videos"


def _set_video_info(li, info, resume):
    # Kodi 20+ has native metadata/resume setters. Keep compatibility with
    # older Kodi and lightweight clients without emitting deprecated calls.
    setters = {"title": "setTitle", "genre": "setGenres", "year": "setYear",
               "mpaa": "setMpaa", "plot": "setPlot", "tvshowtitle": "setTvShowTitle",
               "season": "setSeason", "episode": "setEpisode", "playcount": "setPlaycount",
               "mediatype": "setMediaType", "imdbnumber": "setIMDBNumber",
               "originaltitle": "setOriginalTitle", "duration": "setDuration", "lastplayed": "setLastPlayed",
               "studio": "setStudios", "director": "setDirectors", "tagline": "setTagLine"}
    tag = li.getVideoInfoTag() if hasattr(li, "getVideoInfoTag") else None
    remaining = {}
    for key, value in info.items():
        setter = getattr(tag, setters.get(key, ""), None)
        if setter is None:
            remaining[key] = value
            continue
        if key in ("genre", "studio", "director") and isinstance(value, str):
            value = [value]
        setter(value)
    if remaining:
        li.setInfo("video", remaining)
    if resume.get("position"):
        if tag is not None and hasattr(tag, "setResumePoint"):
            tag.setResumePoint(float(resume["position"]), float(resume.get("total", 0)))
        else:
            li.setProperty("ResumeTime", str(resume["position"]))
            li.setProperty("TotalTime", str(resume.get("total", 0)))


def render_directory(xbmcgui, xbmcplugin, handle, result):
    content = directory_content(result)
    xbmcplugin.setContent(handle, content)
    for item in result["files"]:
        url = item.get("file") or item.get("url") or ""
        if not url:
            continue
        folder = item.get("filetype") == "directory" or item.get("isfolder") is True
        if folder:
            # Only playable leaf URLs may leave the wrapper. Each nested directory
            # is independently validated and filtered when Kodi loads it.
            parsed = urlsplit(url)
            if parsed.scheme != "plugin" or not re.fullmatch(r"plugin\.video\.[A-Za-z0-9_.-]+", parsed.netloc):
                continue
            url = family_directory_url(url, result["max_rating"], result["family_only"])
        li = xbmcgui.ListItem(label=item.get("label") or item.get("title") or "", path=url)
        metadata = item.get("info") if isinstance(item.get("info"), dict) else {}
        info = dict(metadata.get("video", metadata)) if isinstance(metadata.get("video", metadata), dict) else {}
        for key in ("title", "genre", "year", "mpaa", "plot", "showtitle", "tvshowtitle", "season", "episode", "playcount", "lastplayed", "mediatype", "imdbnumber", "originaltitle", "duration", "studio", "director", "tagline"):
            if key in item:
                info[key] = item[key]
        # JSON-RPC uses showtitle; Python ListItem.setInfo expects tvshowtitle.
        if "showtitle" in info:
            show_title = info.pop("showtitle")
            info.setdefault("tvshowtitle", show_title)
        media_type = _media_type(item) or {"movies": "movie", "tvshows": "tvshow",
                                         "seasons": "season", "episodes": "episode"}.get(content)
        if "mediatype" not in info and media_type:
            info["mediatype"] = media_type
        _set_video_info(li, info, item.get("resume") or {})
        if item.get("uniqueid") and hasattr(li, "setUniqueIDs"):
            li.setUniqueIDs(item["uniqueid"])
        art = dict(item.get("art") or {})
        if item.get("thumbnail"):
            art.setdefault("thumb", item["thumbnail"])
        if item.get("fanart"):
            art.setdefault("fanart", item["fanart"])
        li.setArt(art)
        for key, value in (item.get("properties") or {}).items():
            li.setProperty(str(key), str(value))
        if info.get('lastplayed'):
            li.setProperty('km_watched_today', 'true' if str(info['lastplayed'])[:10] == datetime.now().strftime('%Y-%m-%d') else 'false')
        if not folder:
            li.setProperty("IsPlayable", "true")
        try:
            from .item_actions import item_actions
        except ImportError:
            from item_actions import item_actions
        action_props, primary_actions = item_actions(item, media_type, result.get('source', ''))
        for key, value in action_props.items():
            li.setProperty(key, value)
        context = primary_actions + list(item.get("contextmenu") or item.get("context_menu") or [])
        if context:
            li.addContextMenuItems(context)
        xbmcplugin.addDirectoryItem(handle, url, li, isFolder=folder)
    # Pagination/control rows lack explicit ratings/genres and are filtered out.
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
    focus_episode(result)


def focus_episode(result):
    query = parse_qs(urlsplit(result.get('source', '')).query)
    if not query.get('km_focus_episode'):
        return
    try:
        import xbmc, xbmcgui
        wanted = int(query['km_focus_episode'][0])
        season = int(query['season'][0])
        for _ in range(80):
            current = parse_qs(urlsplit(xbmc.getInfoLabel('Container.FolderPath')).query)
            if (current.get('source') == [result['source']] and
                xbmc.getCondVisibility('Window.IsActive(videos)') and
                not xbmc.getCondVisibility('Container.IsUpdating')):
                try:
                    window = xbmcgui.Window(10025)
                    control = window.getControl(525)
                    # Inspect rendered items: Kodi can insert a parent folder and
                    # the list becomes ready after endOfDirectory returns.
                    count = min(int(xbmc.getInfoLabel('Container(525).NumAllItems') or 0), 1000)
                    index = next((i for i in range(count)
                                  if xbmc.getInfoLabel('Container(525).ListItemAbsolute(%d).Episode' % i) == str(wanted)
                                  and xbmc.getInfoLabel('Container(525).ListItemAbsolute(%d).Season' % i) == str(season)), None)
                    if index is not None:
                        window.setFocus(control)
                        control.selectItem(index)
                        return
                except RuntimeError:
                    pass
            xbmc.sleep(100)
    except (ImportError, ValueError, KeyError, RuntimeError):
        pass


def main(argv=None):
    import xbmc
    import xbmcgui
    import xbmcplugin
    try:
        from .addon_index import AddonIndex
    except ImportError:
        from addon_index import AddonIndex
    argv = sys.argv if argv is None else argv
    handle = int(argv[1])
    try:
        query = parse_qs(argv[2].lstrip("?"))
        if query.get("mode", [""])[0] != "family":
            raise ValueError("Unsupported directory mode")
        family_value = query.get("family_only", ["true"])[0].lower()
        if family_value not in ("true", "false"):
            raise ValueError("family_only must be true or false")

        class KodiDirectoryAPI:
            def jsonrpc(self, method, params=None):
                return json.loads(xbmc.executeJSONRPC(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})))

        # The existing KodiAPI supplies add-on discovery, not playback requests.
        try:
            from .kodi_api import KodiAPI
        except ImportError:
            from kodi_api import KodiAPI
        kodi = KodiAPI()
        result = collect_family_directory(KodiDirectoryAPI(), AddonIndex(kodi), query.get("source", [""])[0], query.get("max_rating", ["12A"])[0], family_value == "true")
        render_directory(xbmcgui, xbmcplugin, handle, result)
    except Exception as exc:
        xbmc.log("Kodi Manager family directory: %s" % type(exc).__name__, xbmc.LOGWARNING)
        xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)


if __name__ == "__main__":
    main()
