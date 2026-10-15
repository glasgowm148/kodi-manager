"""One check for "is this add-on URL a read-only directory listing?".

Browsing, previews, cached rows and family rows all ask Kodi to run an
add-on route through ``Files.GetDirectory``. Running an action route that way
plays, opens a dialog or writes data, so every source is checked first.

Add-ons Kodi Manager knows (POV, Fen, Fen Light, TMDb Helper and its Bingie
fork, BBC iPlayer, Bingie Widgets and Kodi Manager itself) are checked against
an explicit allowlist of their listing routes, taken from their routers
(``KNOWN_ROUTES``): the routing parameter (``mode=``, ``info=``, ``action=``)
must name a listing, the path carries no route, and nested sources are
checked in turn. Anything else they route to, including routes added in later
versions, is refused until it is reviewed.

Other add-ons fall back to a vocabulary of words that mark actions (playback,
toggles, refreshes, account sign-in, settings, maintenance, installs and so
on), checked against every query value and path segment. Values are split
into words (``playNextEpisode`` -> play next episode,
``toggle_language_invoker`` -> toggle language invoker). Free-text display
parameters (``name``, ``title``, icons, list slugs) are not routes and are
skipped. The same check covers the other parameters of a known add-on's
listing (``action=delete_list`` is refused even on ``build_movie_list``).

Only stdlib imports: this runs in every widget invocation.
"""
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

# A word starting with one of these marks an action.
DENY_PREFIXES = (
    "play", "resolve", "toggle", "refresh", "rescan", "reset", "clear", "delete", "remove", "install",
    "uninstall", "setting", "setup", "auth", "sign", "logout", "logon", "login", "maintenance", "manage",
    "cache", "exec", "scrape", "download", "sync", "mark", "purge", "wipe", "restore", "backup",
    "search", "upload", "reboot", "restart", "shutdown", "rebuild", "reload",
)
# Whole words that mark an action.
DENY_WORDS = frozenset((
    "run", "tools", "tool", "set", "update", "updates", "account", "accounts", "link", "unlink", "pair",
    "revoke", "export", "import", "rename", "edit", "create", "add", "open", "dialog", "exit", "quit",
    "test", "debug", "log", "logs", "clean", "flush", "script", "trailer", "trailers",
))
# Words that open a dialog, picker or window, or write data, when they name the route
# (POV/Fen options_menu_choice, extras_menu_choice, watched_unwatched_erase_bookmark,
# show_text, choose_view, build_navigate_to_page, menu_editor.*, myservices). Matched only in
# DIALOG_KEYS: in URLs and free text they are ordinary words ("more-like-this").
DIALOG_PREFIXES = ("erase", "choice")
DIALOG_WORDS = frozenset((
    "options", "extras", "select", "input", "choose", "view", "text", "help", "navigate", "editor",
    "slideshow", "viewer", "bookmark", "bookmarks", "like", "unlike", "hide", "unhide",
    "services", "myservices",
))
DIALOG_KEYS = frozenset((
    "mode", "action", "info", "route", "do", "command", "cmd", "func", "function", "method", "op",
    "operation", "task", "call", "run", "exec", "menu",
))
# Parameters that only carry display text or identifiers, never a route.
DISPLAY_KEYS = frozenset((
    "name", "title", "label", "list_name", "iconimage", "icon", "thumb", "thumbnail", "poster", "fanart",
    "plot", "exit_list_params", "slug", "list_slug", "user_slug", "query", "year", "page", "new_page",
    "tmdb_id", "imdb_id", "tvdb_id", "trakt_id", "id", "season", "episode", "km_focus_episode",
    "user", "username", "user_id", "list_id", "list_user", "owner", "list_type",
    # Skin cache-busters such as reload=$INFO[Window(Home).Property(TMDbHelper.Widgets.Reload)].
    "reload",
))
# Parameters add-ons route by. Their words are matched by prefix (``playback``,
# ``settings``); other parameters only by whole word, so a value such as a
# user name that merely starts with "mark" or "play" is not mistaken for a route.
ROUTE_KEYS = frozenset((
    "mode", "action", "info", "route", "do", "command", "cmd", "func", "function", "method", "op",
    "operation", "task", "path", "url", "endpoint", "call", "run", "exec", "target", "menu", "page_type",
))
_INFLECTIONS = ("", "s", "ed", "ing", "er", "ers")

_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_SPLIT = re.compile(r"[^a-z0-9]+")
_ADDON = re.compile(r"plugin\.video\.[A-Za-z0-9_.-]+")
_PARAM_KEY = re.compile(r"[A-Za-z0-9_.-]+")


def words(value):
    """Lower-case words of a route value; camelCase and any punctuation separate words.

    Compatibility forms are folded first (NFKD), so full-width ``\uff50\uff4c\uff41\uff59`` and
    ligatures read as the ASCII words an add-on that normalises them would see.
    """
    text = unicodedata.normalize("NFKD", unquote(str(value or "")))
    return [w for w in _SPLIT.split(_CAMEL.sub(r"\1_\2", text).lower()) if w]


_EXACT = frozenset(DENY_WORDS | {p + ending for p in DENY_PREFIXES for ending in _INFLECTIONS})


def action_word(value, route=True, dialog=False):
    """The first word of ``value`` that marks an action, or ''.

    ``route``: the value selects a route, so words are matched by prefix too.
    ``dialog``: the value names the route itself (``mode=``), so dialog words count too.
    """
    for word in words(value):
        if word in _EXACT or (route and word.startswith(DENY_PREFIXES)):
            return word
        if dialog and (word in DIALOG_WORDS or word.startswith(DIALOG_PREFIXES)):
            return word
    return ""


class Routes(object):
    """Listing routes of one add-on, from its router.

    ``key``: the query parameter it routes by; ``default``: the route when that
    parameter is absent (``None``: no listing without it); ``exact``: listing
    routes; ``families``: prefixes of listing families that are matched like
    exact routes but must also pass the action-word check (``build_trakt_*``);
    ``data``: parameters this add-on treats as data, never as a route (the
    action-word check skips them); ``nested``: parameters that carry another
    source URL, checked in turn.
    """

    __slots__ = ("key", "default", "exact", "families", "data", "nested")

    def __init__(self, key, default, exact, families=(), data=(), nested=()):
        self.key = key
        self.default = default
        self.exact = frozenset(exact)
        self.families = tuple(families)
        self.data = frozenset(data)
        self.nested = frozenset(nested)

    def lists(self, route):
        """True when ``route`` (the routing value) names one of this add-on's listings."""
        if route in self.exact:
            return True
        return route.startswith(self.families) and not action_word(route, dialog=True)


# POV's router (resources/lib/entry.py, POV_ROUTES and routing()): ``mode`` selects the route,
# ``navigator.main`` without one. Listings are the build_* menus, the dynamic
# build_trakt_/build_mdbl_/build_tmdb_ menus and these Navigator/Discover folders. Everything
# else (manager_*, *_choice pickers, play_media, settings, caches, images, trakt./tmdb./mdblist.
# API calls, debrid cloud tools) acts. Fen and Fen Light share the router's vocabulary.
_POV_LISTINGS = (
    "build_movie_list", "build_tvshow_list", "build_season_list", "build_episode_list",
    "build_in_progress_episode", "build_continue_episode", "build_next_episode", "build_continue_movie",
    "build_my_calendar_trakt", "build_my_anime_calendar", "build_my_calendar_mdbl", "build_anime_calendar",
    "build_popular_people", "build_trakt_list", "build_my_calendar",
    "navigator.main", "navigator.discover_main", "navigator.premium", "navigator.downloads",
    "navigator.my_content", "navigator.favorites", "navigator.trakt_collections", "navigator.trakt_watchlists",
    "navigator.trakt_lists", "navigator.trakt_favorites", "navigator.trakt_recommendations",
    "navigator.because_you_watched", "navigator.genres", "navigator.multiselect_genres", "navigator.years",
    "navigator.decades", "navigator.languages", "navigator.certifications", "navigator.networks",
    "navigator.providers", "navigator.people", "navigator.mdbl_lists", "navigator.tmdb_lists",
    "discover.history",
)
_POV_FAMILIES = ("build_trakt_", "build_mdbl_", "build_tmdb_")
_POV = Routes("mode", "navigator.main", _POV_LISTINGS, _POV_FAMILIES)

# TMDb Helper (and its Bingie fork) route by ``info``; without one the add-on lists its root.
# play, textviewer, imageviewer and the sign-in, settings and search entry points act.
_TMDB_HELPER = Routes("info", "", (
    "popular", "top_rated", "upcoming", "now_playing", "airing_today", "on_the_air", "trending_day",
    "trending_week", "revenue_movies", "most_voted", "genres", "watch_providers", "all_items", "discover",
    "collection", "details", "seasons", "episodes", "episode_groups", "episode_group_seasons",
    "episode_group_episodes", "cast", "crew", "recommendations", "similar", "stars_in_movies",
    "stars_in_tvshows", "crew_in_movies", "crew_in_tvshows", "crew_in_both", "stars_in_both",
    "movie_keywords", "keywords_movies", "images", "posters", "fanart", "videos", "reviews", "related",
    "dir_movie", "dir_tv", "dir_person", "dir_random", "dir_discover", "dir_tmdb", "dir_tmdb_v4",
    "dir_trakt", "dir_tvdb", "dir_mdblist", "dir_calendar_trakt", "dir_custom_node", "dir_calendar_library",
    "library_nextaired",
), families=("trakt_", "mdblist_", "random_", "tmdb_v4_", "tvdb_"))

# BBC iPlayer (default.py): numeric ``mode``; without one it lists its root. 101-120 are its
# menus, 121-141 and 197/198 sub-folders. 1 toggles kids mode, 104/115 open a search keyboard,
# 118 a dialog, 119 signs out, 122/123/129/132/133 list streams to play, 142 marks an episode,
# 201-213 play and 301/302 remove. ``url``, ``name`` and artwork are data (programme slugs such
# as ``play-school`` are not routes).
_IPLAYER = Routes("mode", "", (
    "101", "102", "103", "105", "106", "107", "108", "109", "112", "113", "114", "116", "117", "120",
    "121", "124", "125", "126", "127", "128", "131", "134", "136", "137", "138", "139", "140", "141",
    "197", "198", "199",
), data=("url", "name", "iconimage", "description", "episode_id", "stream_id", "replay_chan_id"))

# Bingie Widgets routes by ``action``; ``play`` resolves an item.
_BINGIE_WIDGETS = Routes("action", None, (
    "recent", "popular", "random", "newrelease", "forgenre", "inprogress", "inprogressnextepisode",
    "mylist", "similar", "recommended", "nextepisodes",
))

# Kodi Manager's own plugin (widget_plugin.main): the root, the cached rows folder, cached and
# family rows (their ``source`` is checked too) and ``continue``, a private extension's
# listing (docs/extensions.md). ``dashboard`` opens a text viewer.
_SELF = Routes("mode", "", ("rows", "cached", "family", "continue"), nested=("source",))

KNOWN_ROUTES = {
    "plugin.video.pov": _POV,
    "plugin.video.fen": _POV,
    "plugin.video.fenlight": _POV,
    "plugin.video.themoviedb.helper": _TMDB_HELPER,
    "plugin.video.tmdb.bingie.helper": _TMDB_HELPER,
    "plugin.video.iplayerwww": _IPLAYER,
    "script.bingie.widgets": _BINGIE_WIDGETS,
    "service.kodi.addonadmin": _SELF,
}


def _word_reason(key, value):
    if key.lower() == "isfolder" and value.lower() == "false":
        return "not a folder"
    word = action_word(value, route=key.lower() in ROUTE_KEYS, dialog=key.lower() in DIALOG_KEYS)
    return "%s=%s" % (key, word) if word else ""


def _normalised_key(raw):
    """A raw query key as a naive add-on parser could read it: BBC iPlayer's get_params strips
    every '?' and splits on '&' and '='; others unquote, or keep an HTML-escaped ``&amp;``."""
    key = raw.replace("?", "").replace("%", "").replace("+", "").lower()
    while key.startswith("amp;"):
        key = key[4:]
    return key


def _query_reason(query, routes):
    """Why the query of a known add-on could be read differently by the add-on than by
    parse_qsl, or ''. Such a query could name a second, unchecked route."""
    if "?" in query:
        return "unexpected '?' in query"
    routing = 0
    for piece in query.split("&"):
        if not piece:
            continue
        raw = piece.split("=", 1)[0]
        parsed_key = unquote(raw.replace("+", " "))
        if not _PARAM_KEY.fullmatch(parsed_key):
            return "parameter name '%s'" % parsed_key[:40]
        if _normalised_key(raw) == routes.key.lower() or parsed_key.lower() == routes.key.lower():
            if parsed_key != routes.key:
                return "ambiguous %s=" % routes.key
            routing += 1
    if routing > 1:
        return "repeated %s=" % routes.key
    return ""


def _known_reason(parsed, routes, depth):
    path = unquote(parsed.path)
    if path not in ("", "/"):
        return "path '%s'" % path.strip("/").split("/")[0][:40]
    reason = _query_reason(parsed.query, routes)
    if reason:
        return reason
    params = parse_qsl(parsed.query, keep_blank_values=True)
    values = [value for key, value in params if key == routes.key]
    if len(values) > 1:
        return "repeated %s=" % routes.key
    route = values[0] if values else routes.default
    if route is None or (not route and routes.default is None):
        return "no %s=" % routes.key
    if not route.isascii():
        return "%s is not plain text" % routes.key
    if route and not routes.lists(route):
        return "%s=%s" % (routes.key, (action_word(route, dialog=True) or route)[:40])
    for key, value in params:
        lower = key.lower()
        if key == routes.key or lower in DISPLAY_KEYS or lower in routes.data:
            continue
        if lower in routes.nested:
            if depth >= 2 or not value.startswith("plugin://"):
                return "%s is not an add-on folder" % key
            reason = _reason(value, depth + 1)
            if reason:
                return "%s: %s" % (key, reason)
            continue
        reason = _word_reason(key, value)
        if reason:
            return reason
    return ""


def _reason(source, depth):
    parsed = urlsplit(source)
    routes = KNOWN_ROUTES.get((parsed.netloc or "").lower())
    if routes is not None:
        return _known_reason(parsed, routes, depth)
    for segment in unquote(parsed.path).split("/"):
        word = action_word(segment)
        if word:
            return "path segment '%s'" % word
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in DISPLAY_KEYS:
            continue
        reason = _word_reason(key, value)
        if reason:
            return reason
    return ""


def blocked_reason(source):
    """'' when ``source`` is a read-only listing route, else why it is refused.

    Known add-ons (``KNOWN_ROUTES``) must name one of their listing routes; others are checked
    word by word for actions.
    """
    return _reason(source, 0)


def check_directory(source, message="Playback or action endpoints cannot be directory sources"):
    """Validate a ``plugin://plugin.video.*`` directory URL; raises ValueError(message) for actions."""
    if not isinstance(source, str) or not source or len(source) > 12000 or any(ord(c) < 32 for c in source):
        raise ValueError("Invalid source directory URL")
    parsed = urlsplit(source)
    if (parsed.scheme != "plugin" or not _ADDON.fullmatch(parsed.netloc or "") or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("Source must be a video add-on directory URL")
    reason = blocked_reason(source)
    if reason == "not a folder":
        raise ValueError("This item is not a browseable folder")
    if reason:
        raise ValueError(message)
    return source
