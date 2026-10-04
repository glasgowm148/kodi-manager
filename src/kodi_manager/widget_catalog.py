"""Browse actual Kodi directories without executing media or utility actions."""
import re
import copy
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qs, urlparse, unquote

try:
    from .widget_plugin import validate_source
except ImportError:
    from widget_plugin import validate_source


PROPERTIES = ["title", "thumbnail", "art", "year", "genre", "plot", "mpaa", "showtitle", "season", "episode"]
UTILITY = re.compile(r"(?:^|[._ /-])(settings|setup|tools|accounts?|login|authorize|auth|logout|delete|remove|clear|reset|download|play|playback|resolve|scrape|search)(?:$|[._ /-])", re.I)
_PAGINATION = re.compile(r"^(?:next page|previous page|load more|more results|next|previous)(?:\s*[<>»«→←]*|\s*\(\d+\))$", re.I)
_MEDIA_TYPES = {"movie", "tvshow", "season", "episode", "musicvideo"}
_SERIES_ROUTE = re.compile(r"(?:^|[._ /-])(?:seasons?|episodes?)(?:$|[._ /-])", re.I)
_CACHE_TTL = 300
_CACHE_MAX = 256
_CACHE = OrderedDict()
_CACHE_LOCK = threading.RLock()
_RPC_SLOTS = threading.BoundedSemaphore(2)


def clean_label(value):
    return re.sub(r"\[/?(?:B|I|COLOR(?: [^\]]*)?)\]", "", str(value or ""), flags=re.I).strip()


def folder_usefulness(label, path, addon_id, breadcrumb=(), current_paths=(), classification=None):
    """Transparent ordering hint, inferred from observed labels/configuration.

    Stored/current paths get +35, observed POV title-list routes +25, POV +10.
    Highest matching primary label bonus: continue/next episode +65,
    watchlist +55, popular/trending
    +85, recommendation +45, latest/premieres +80, top-rated +50, family +18,
    genres/movie/TV categories +15. User-list menus lose 50, taxonomy menus 35,
    utilities 100. Loading a preview never changes its ranking.
    No provider route is created and no account/source request is performed.
    """
    score, reasons = 20, []
    text = clean_label(label).casefold()
    if path in current_paths:
        score += 35
        reasons.append("Used by a current widget row (+35).")
    if addon_id == "plugin.video.pov":
        score += 10
        reasons.append("POV is the selected playback add-on (+10).")
        try:
            modes = parse_qs(urlparse(path if isinstance(path, str) else "").query).get("mode", [])
        except (TypeError, ValueError):
            modes = []
        if any(mode in ("build_movie_list", "build_tvshow_list") for mode in modes):
            score += 25
            reasons.append("Observed POV route returns a title list (+25).")
    bonuses = (
        (r"\b(?:continue watching|in progress|resume|next episodes?)\b", 65, "Continue-watching list"),
        (r"\bwatchlist\b", 55, "Watchlist"),
        (r"\b(?:popular|trending|most watched)\b", 85, "Popular or trending list"),
        (r"\b(?:recommendations?|recommended|because you watched)\b", 45, "Recommendation source"),
        (r"\b(?:latest|recent|premieres?|new releases?)\b", 80, "Recent-release list"),
        (r"\b(?:top rated|highly rated)\b", 50, "Highly rated list"),
        (r"\b(?:family|kids|children)\b", 18, "Family category"),
        (r"\bgenres?\b|^(?:movies|tv shows|shows)$", 15, "Useful content category"),
    )
    primary = [rule for rule in bonuses[:6] if re.search(rule[0], text)]
    if primary:
        _, bonus, reason = max(primary, key=lambda rule: rule[1])
        score += bonus
        reasons.append("%s (+%s)." % (reason, bonus))
    for pattern, bonus, reason in bonuses[6:]:
        if re.search(pattern, text):
            score += bonus
            reasons.append("%s (+%s)." % (reason, bonus))
    if re.search(r"\buser lists?\b", text):
        score -= 50
        reasons.append("User-list catalogue needs another folder selection (-50).")
    if re.search(r"\b(?:languages?|years?|decades?|people|actors?|directors?|studios?|networks?|countries|alphabetical)\b", text):
        score -= 35
        reasons.append("Taxonomy menu usually needs further selection (-35).")
    if any("genre" in clean_label(part).casefold() for part in breadcrumb) and not re.search(r"\b(?:family|kids|children)\b", text):
        score -= 20
        reasons.append("Specific genre is narrower than general discovery lists (-20).")
    if UTILITY.search(text) or text in ("my services", "add source", "add sources"):
        score -= 100
        reasons.append("Interactive or utility folder is unsuitable for automatic widgets (-100).")
    if not reasons:
        reasons.append("No strong list signal in the observed folder label.")
    return {"score": max(0, score), "reason": " ".join(reasons), "reasons": reasons, "inferred": True,
            "basis": "Observed folder labels, POV routes and current widget paths; usefulness is not a content or account verification."}


def listing_path(path, index):
    if not isinstance(path, str) or len(path) > 12000 or any(ord(c) < 32 for c in path):
        raise ValueError("Invalid folder path")
    parsed = urlparse(path)
    if parsed.scheme != "plugin" or not parsed.netloc.startswith("plugin.video.") or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Choose a folder from an installed video add-on")
    addon = index.get(parsed.netloc)
    if not addon or addon.get("installed") is not True or addon.get("enabled") is not True:
        raise ValueError("This video add-on is not confirmed installed and enabled")
    params = parse_qs(parsed.query)
    if any(UTILITY.search(unquote(value)) for key in ("mode", "action", "info", "do", "command") for value in params.get(key, [])):
        raise ValueError("This is an interactive action. Use its native Kodi screen instead.")
    if any(value.lower() == "false" for value in params.get("isFolder", [])):
        raise ValueError("This item is not a browseable folder")
    return validate_source(index, path)


def _navigation_reason(label, path):
    if _PAGINATION.search(label):
        return "Pagination is not traversed automatically."
    if UTILITY.search(label) or label.casefold() in ("my services", "my accounts", "add source", "add sources"):
        return "Interactive, account, or utility menu is not traversed automatically."
    if not isinstance(path, str):
        return "Invalid folder path."
    try:
        params = parse_qs(urlparse(path).query)
    except ValueError:
        return "Invalid folder path."
    for key in ("page", "page_no", "pagenumber", "offset", "start"):
        for value in params.get(key, []):
            try:
                if int(value) > (1 if key.startswith("page") else 0):
                    return "Pagination is not traversed automatically."
            except ValueError:
                return "Unbounded pagination route is not traversed automatically."
    if any(key in params for key in ("cursor", "nextpage", "next_page")):
        return "Pagination is not traversed automatically."
    return ""


def _media_item(raw):
    if any(isinstance(raw.get(key), str) and raw[key] in _MEDIA_TYPES for key in ("type", "mediatype")):
        return True
    if any(raw.get(key) not in (None, "", [], 0, -1) for key in ("year", "mpaa", "showtitle", "season", "episode")):
        return True
    if any(isinstance(raw.get(key), int) and raw[key] >= 0 for key in ("season", "episode")):
        return True
    path = raw.get("file", "")
    try:
        params = parse_qs(urlparse(path if isinstance(path, str) else "").query)
    except ValueError:
        params = {}
    route = " ".join(value for key in ("mode", "action", "info") for value in params.get(key, []))
    if any(key in params for key in ("tvshow_id", "tvshowid", "show_id", "showid", "season", "episode")):
        return True
    if "tvshow" in route.casefold() and "tmdb_id" in params:
        return True
    return bool(_SERIES_ROUTE.search(route)) or (raw.get("filetype") == "file" and bool(raw.get("title")))


def _catalog_metadata(items, limits, path):
    media = [item for item in items if item["classification"] == "media"]
    menus = [item for item in items if item["classification"] == "menu"]
    classification = "mixed" if media and menus else "media_list" if media else "menu" if menus else "empty"
    # A content row can include navigation controls, but individual media folders
    # (TV shows/seasons) must never become automatic traversal destinations.
    children = [copy.deepcopy(item) for item in menus if item["traversable"]]
    skipped = [{"label": item["label"], "path": item["path"], "reason": item["skip_reason"],
                "classification": item["classification"], "browseable": item["browseable"]}
               for item in items if not item["traversable"] and item["skip_reason"]]
    total = limits.get("total")
    end = limits.get("end")
    truncated = (isinstance(total, int) and isinstance(end, int) and end < total) or bool(limits.get("start", 0))
    pagination = sum("Pagination" in item["skip_reason"] for item in items)
    truncated = truncated or pagination > 0
    sample = {"truncated": truncated, "returned": len(media), "menu_count": len(menus),
              "pagination_count": pagination, "total": total,
              "message": "Truncated preview; more source items are available." if truncated else "Preview of the returned directory; navigation controls are not counted as titles."}
    return {"classification": classification, "traversable": bool(children), "can_use_as_widget": bool(media),
            "children": children, "skips": skipped, "sample": sample}


def list_sources(kodi, index):
    index.refresh()
    sources = []
    for addon in index.list():
        aid = addon.get("addon_id", "")
        if not aid.startswith("plugin.video.") or addon.get("installed") is not True:
            continue
        sources.append({"addon_id": aid, "label": addon.get("name") or aid,
                        "version": addon.get("version", ""), "enabled": addon.get("enabled"),
                        "path": "plugin://%s/" % aid, "classification": "menu",
                        "traversable": addon.get("enabled") is True, "can_use_as_widget": False,
                        "skip_reason": "" if addon.get("enabled") is True else "Add-on is not confirmed enabled.",
                        "usefulness": folder_usefulness(addon.get("name") or aid, "plugin://%s/" % aid, aid)})
    sources.sort(key=lambda a: (a["addon_id"] != "plugin.video.pov", a["label"].lower()))
    return {"sources": sources, "note": "Folders come directly from your installed add-ons. Browsing does not start playback."}


def browse_directory(kodi, index, path, start=0, limit=48, refresh=False):
    """List one observed directory for a progressive, bounded UI traversal.

    Additive contract: classification/menu|media_list|mixed|empty, traversable,
    can_use_as_widget, children (only safe menu folders), skips with reasons, and
    sample.truncated. Existing path/items/limits/contains_media remain available.
    Each item also carries classification/traversable/can_use_as_widget/skip_reason.
    Cache TTL is five minutes, maximum 256 pages, at most two concurrent RPCs.
    refresh=True evicts all cached pages of this source path before reading it.
    """
    path = listing_path(path, index)
    start = max(0, min(int(start), 10000))
    limit = max(1, min(int(limit), 100))
    key = (id(kodi), path, start, limit)
    now = time.monotonic()
    with _CACHE_LOCK:
        for cached_key, entry in list(_CACHE.items()):
            if now - entry["time"] >= _CACHE_TTL or (refresh and cached_key[:2] == key[:2]):
                del _CACHE[cached_key]
        if key in _CACHE:
            _CACHE.move_to_end(key)
            cached = copy.deepcopy(_CACHE[key]["result"])
            cached["cache"] = {"hit": True, "age_seconds": round(now - _CACHE[key]["time"], 1), "ttl_seconds": _CACHE_TTL}
            return cached
    with _RPC_SLOTS:
        response = kodi.jsonrpc("Files.GetDirectory", {"directory": path, "media": "files", "properties": PROPERTIES,
                                                       "limits": {"start": start, "end": start + limit}})
    if not isinstance(response, dict):
        raise ValueError("Kodi returned an invalid directory response")
    if response.get("error"):
        raise ValueError(response["error"].get("message", "Kodi could not list this folder"))
    result = response.get("result") or {}
    if not isinstance(result, dict) or not isinstance(result.get("files"), list):
        raise ValueError("Kodi returned no directory result")
    items = []
    for raw in result["files"][:limit]:
        if not isinstance(raw, dict):
            continue
        item_path = raw.get("file", "")
        folder = raw.get("filetype") == "directory"
        reason = ""
        if folder:
            try:
                listing_path(item_path, index)
            except ValueError as exc:
                reason = str(exc)
        title = clean_label(raw.get("title") or raw.get("label"))
        label = clean_label(raw.get("label")) or title
        skip_reason = _navigation_reason(label, item_path)
        media_item = _media_item(raw)
        item_classification = "blocked" if reason else "navigation" if skip_reason else "media" if media_item else "menu" if folder else "unknown"
        if not skip_reason:
            skip_reason = reason or ("Media/show/season/episode items are previewed without automatic traversal." if media_item else ("Not a confirmed menu folder." if not folder else ""))
        items.append({"label": clean_label(raw.get("label")) or title, "title": title,
                      "path": item_path, "filetype": raw.get("filetype", "file"),
                      "browseable": folder and not reason, "reason": reason,
                      "thumbnail": raw.get("thumbnail", ""), "art": raw.get("art") or {},
                      "year": raw.get("year"), "genre": raw.get("genre") or [],
                      "plot": raw.get("plot", ""), "mpaa": raw.get("mpaa", ""),
                      "type": raw.get("type", "unknown"), "classification": item_classification,
                      "traversable": folder and not reason and not skip_reason,
                      "can_use_as_widget": folder and media_item and not reason and not _navigation_reason(label, item_path),
                      "skip_reason": skip_reason,
                      "usefulness": folder_usefulness(label, item_path, urlparse(path).netloc)})
    limits = result.get("limits")
    if not isinstance(limits, dict):
        limits = {"start": start, "end": start + len(items), "total": start + len(result["files"])}
    out = {"path": path, "addon_id": urlparse(path).netloc, "items": items, "limits": limits,
           "contains_media": any(i["classification"] == "media" for i in items)}
    out.update(_catalog_metadata(items, limits, path))
    out["usefulness"] = folder_usefulness("", path, out["addon_id"], classification=out["classification"])
    if len(result["files"]) > limit:
        out["sample"]["truncated"] = True
        out["sample"]["message"] = "Truncated preview; more source items are available."
    out["cache"] = {"hit": False, "age_seconds": 0, "ttl_seconds": _CACHE_TTL}
    with _CACHE_LOCK:
        _CACHE[key] = {"time": time.monotonic(), "result": copy.deepcopy(out), "owner": kodi}
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return out


def suggest_kids_rows(kodi, index):
    """Select existing menu destinations; never synthesize provider query routes."""
    root = browse_directory(kodi, index, "plugin://plugin.video.pov/", limit=100)
    rows = []
    recommendations = []
    for folder, media in (("Movies", "Movies"), ("TV Shows", "TV Shows")):
        parent = next((x for x in root["items"] if x["label"].casefold() == folder.casefold() and x["browseable"]), None)
        if not parent:
            continue
        listing = browse_directory(kodi, index, parent["path"], limit=100)
        for prefix, candidates in (("Latest", ("Latest Releases", "Premieres")), ("Popular", ("Popular",)), ("Trending", ("Trending",))):
            item = next((x for label in candidates for x in listing["items"] if x["label"].casefold() == label.casefold() and x["browseable"]), None)
            if item:
                rows.append({"label": "%s Kids %s" % (prefix, media), "path": item["path"], "filtered": True,
                             "breadcrumb": ["POV", folder, item["label"]]})
        item = next((x for x in listing["items"] if x["label"].startswith("Because You Watched") and x["browseable"]), None)
        if item:
            recommendations.append({"label": "%s recommendations" % media, "path": item["path"], "breadcrumb": ["POV", folder, item["label"]]})
    return {"rows": rows, "recommendation_sources": recommendations,
            "note": "Sources were found in your POV menus. Family and rating filters run when Kodi loads each saved row. For recommendations, choose a watched family title first, then its recommendation list. Latest TV uses the provider's Premieres list when no Latest Releases folder exists."}
