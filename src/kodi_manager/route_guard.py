"""One check for "is this add-on URL a read-only directory listing?".

Browsing, previews, cached rows and family rows all ask Kodi to run an
add-on route through ``Files.GetDirectory``. Add-ons route by query values
(``?mode=...``, ``?action=...``, ``?info=...``, ``?route=...``) or by path
segments (``/play/123``), so both are checked, for every parameter, against
one vocabulary of words that mark actions: playback, toggles, refreshes,
account sign-in, settings, maintenance, installs and so on.

Values are split into words (``playNextEpisode`` -> play next episode,
``toggle_language_invoker`` -> toggle language invoker). Free-text display
parameters (``name``, ``title``, icons, list slugs) are not routes and are
skipped. Known listing routes of the supported stack stay accepted: POV/Fen
``build_*`` and ``navigator`` menus, TMDb Helper ``info=`` lists.

Only stdlib imports: this runs in every widget invocation.
"""
import re
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


def words(value):
    """Lower-case words of a route value; camelCase and any punctuation separate words."""
    return [w for w in _SPLIT.split(_CAMEL.sub(r"\1_\2", unquote(str(value or ""))).lower()) if w]


_EXACT = frozenset(DENY_WORDS | {p + ending for p in DENY_PREFIXES for ending in _INFLECTIONS})


def action_word(value, route=True):
    """The first word of ``value`` that marks an action, or ''.

    ``route``: the value selects a route, so words are matched by prefix too.
    """
    for word in words(value):
        if word in _EXACT or (route and word.startswith(DENY_PREFIXES)):
            return word
    return ""


def blocked_reason(source):
    """'' when ``source`` looks like a read-only listing route, else why it is refused."""
    parsed = urlsplit(source)
    for segment in unquote(parsed.path).split("/"):
        word = action_word(segment)
        if word:
            return "path segment '%s'" % word
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in DISPLAY_KEYS:
            continue
        if key.lower() == "isfolder" and value.lower() == "false":
            return "not a folder"
        word = action_word(value, route=key.lower() in ROUTE_KEYS)
        if word:
            return "%s=%s" % (key, word)
    return ""


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
