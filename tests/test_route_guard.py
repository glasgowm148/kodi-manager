"""Routes that act (dialogs, writes, sign-in) must never be run as a directory listing."""
import pytest

from kodi_manager import route_guard
from kodi_manager.item_actions import item_actions

POV = "plugin://plugin.video.pov/?mode="

# POV/Fen router modes that open dialogs or windows, or write data, when run.
ACTION_MODES = [
    "manager_rating", "manager_rating_status", "manager_watchlist", "manager_watchlist_status", "manager_seen",
    "manager_show", "smart_play_media", "play_media", "media_play", "downloader", "scraper_color_choice",
    "scraper_dialog_color_choice", "scraper_quality_color_choice", "set_quality_choice", "results_sorting_choice",
    "options_menu_choice", "meta_language_choice", "favorites_choice", "dropped_choice",
    "set_language_filter_choice", "extras_lists_choice", "random_choice", "extras_menu_choice",
    "trakt_manager_choice", "mdbl_manager_choice", "tmdb_manager_choice", "build_navigate_to_page",
    "open_settings", "clean_settings", "clean_settings_window_properties", "clear_all_cache", "clear_cache",
    "clean_databases", "clear_streams", "clear_thumbnails", "search_history", "clear_search_history",
    "remove_from_history", "discover_remove_from_history", "discover_remove_all_history", "get_search_term",
    "person_search", "person_data_dialog", "mark_as_watched_unwatched_episode", "mark_as_watched_unwatched_season",
    "mark_as_watched_unwatched_tvshow", "mark_as_watched_unwatched_movie", "watched_unwatched_erase_bookmark",
    "choose_view", "set_view", "clear_view_modes", "show_text", "toggle_provider", "toggle_language_invoker",
    "upload_logfile", "myservices", "refer_link", "undesirablesSelect", "undesirablesInput",
    "undesirablesUserRemove", "speedTest", "aioHelp",
    # Prefix-routed families.
    "trakt.trakt_account_info", "mdblist.mdbl_account_info", "tmdb.edit_tmdb_list", "tmdb.update_tmdb_list",
    "trakt.hide_unhide_progress_items", "trakt.trakt_like_a_list", "trakt.trakt_unlike_a_list",
    "menu_editor.move", "menu_editor.shortcut_folder_make", "discover.remove_from_history",
    "slideshow_image", "delete_image",
]
LISTING_MODES = [
    "build_movie_list", "build_tvshow_list", "build_season_list", "build_episode_list",
    "build_in_progress_episode", "build_continue_episode", "build_next_episode", "build_my_calendar_trakt",
    "build_my_anime_calendar", "build_my_calendar_mdbl", "build_anime_calendar", "build_popular_people",
    "build_trakt_list", "navigator.main", "navigator.favorites", "navigator.trakt_favorites",
    "navigator.because_you_watched", "navigator.multiselect_genres", "navigator.genres", "discover.history",
]


@pytest.mark.parametrize("mode", ACTION_MODES)
def test_pov_action_modes_are_refused(mode):
    with pytest.raises(ValueError):
        route_guard.check_directory(POV + mode + "&mediatype=movie&tmdb_id=603")
    with pytest.raises(ValueError):
        route_guard.check_directory("plugin://plugin.video.fenlight/?mode=" + mode)


@pytest.mark.parametrize("mode", LISTING_MODES)
def test_pov_listing_modes_stay_accepted(mode):
    source = POV + mode + "&tmdb_id=603"
    assert route_guard.check_directory(source) == source


def _item_action_targets():
    items = [
        ({"file": POV + "play_media&mediatype=movie&tmdb_id=603"}, "movie"),
        ({"file": POV + "play_media&mediatype=episode&tmdb_id=1399&season=1&episode=2"}, "episode"),
        ({"file": POV + "build_season_list&tmdb_id=1399"}, "tvshow"),
        ({"file": POV + "build_episode_list&tmdb_id=1399&season=1"}, "season"),
    ]
    targets = []
    for source in ("", POV + "build_movie_list&action=trakt_watchlist"):
        for item, media_type in items:
            for _label, action in item_actions(item, media_type, source)[1]:
                assert action.startswith("RunPlugin(") and action.endswith(")")
                targets.append(action[len("RunPlugin("):-1])
    return sorted(set(targets))


def test_every_item_action_target_is_seen():
    modes = {t.split("mode=")[1].split("&")[0] for t in _item_action_targets()}
    assert modes == {"manager_watchlist", "manager_show", "manager_seen", "play_media",
                     "options_menu_choice", "extras_menu_choice"}


@pytest.mark.parametrize("target", _item_action_targets())
def test_item_action_targets_are_never_browsable(target):
    with pytest.raises(ValueError):
        route_guard.check_directory(target)


# --- Explicit listing allowlists for known add-ons ---------------------------------------

from urllib.parse import quote  # noqa: E402

HELPER = "plugin://plugin.video.tmdb.bingie.helper/?info="
IPLAYER = "plugin://plugin.video.iplayerwww/?mode="
SELF = "plugin://service.kodi.addonadmin/?mode="

# Listing routes as the household skin, its widget groups and the widget cache use them
# (route names from the add-ons' routers; ids and slugs are synthetic).
SKIN_AND_CACHE_LISTINGS = [
    "plugin://plugin.video.pov/",
    "plugin://plugin.video.pov/?name=32107&iconImage=downloads.png&mode=navigator.downloads",
    POV + "navigator.main&action=MovieList",
    POV + "navigator.main&action=TVShowList",
    POV + "navigator.because_you_watched",
    POV + "navigator.trakt_watchlists",
    POV + "build_movie_list&action=tmdb_movies_blockbusters",
    POV + "build_movie_list&action=tmdb_movies_collection&key_id=10",
    POV + "build_movie_list&action=tmdb_media_discover&name=Hidden+gems&url=https%3A%2F%2Fapi.example.invalid%2Fdiscover",
    POV + "build_movie_list&action=trakt_movies_most_watched&reload=$INFO[Window(Home).Property(km_widgets)]",
    POV + "build_movie_list&action=in_progress_movies",
    POV + "build_tvshow_list&action=tmdb_tv_networks&key_id=49",
    POV + "build_tvshow_list&action=trakt_watchlist_lists",
    POV + "build_trakt_list.get_trakt_lists&list_type=my_lists",
    POV + "build_trakt_list.get_trakt_trending_popular_lists&list_type=trending",
    POV + "build_tmdb_list.get_tmdb_lists",
    POV + "build_next_episode",
    POV + "build_in_progress_episode",
    "plugin://plugin.video.fenlight/?mode=navigator.main",
    "plugin://plugin.video.fen/?mode=build_tvshow_list&action=trakt_tv_trending",
    HELPER + "now_playing&tmdb_type=movie",
    HELPER + "trakt_upnext&tmdb_type=tv&widget=true",
    HELPER + "trakt_inprogress&tmdb_type=tv",
    HELPER + "trakt_userlist&list_slug=play-time&user_slug=me",
    HELPER + "trakt_watchlist_released&tmdb_type=movie",
    HELPER + "discover&tmdb_type=movie&with_genres=16",
    HELPER + "seasons&tmdb_type=tv&tmdb_id=1",
    HELPER + "dir_calendar_trakt",
    HELPER + "random_trending&tmdb_type=movie",
    HELPER + "mdblist_userlist&list_id=1",
    "plugin://plugin.video.themoviedb.helper/",
    IPLAYER + "107&url=watching",
    IPLAYER + "141&url=next",
    IPLAYER + "128&url=https%3A%2F%2Fwww.bbc.co.uk%2Fiplayer%2Fepisodes%2Fplay-school&name=Play+School"
              "&description=Songs+to+sing+and+play+along",
    IPLAYER + "140&url=https%3A%2F%2Fwww.bbc.co.uk%2Fiplayer%2Fepisodes%2Fexample",
    "plugin://plugin.video.iplayerwww/",
]


@pytest.mark.parametrize("source", SKIN_AND_CACHE_LISTINGS)
def test_real_listing_routes_pass(source):
    assert route_guard.blocked_reason(source) == ""
    assert route_guard.check_directory(source) == source


@pytest.mark.parametrize("source", [
    # Routes outside the allowlists, even without an action word.
    POV + "navigator", POV + "tmdb_movies", POV + "discover.router", POV + "discover.help",
    POV + "build_navigate_to_page", POV + "build_trakt_list.search_trakt_lists", POV + "trakt.list_items",
    POV + "torbox.browse_cloud", POV + "navigator.settings", POV + "navigator.search",
    POV + "build_movie_list&mode=play_media",                    # a second mode= is ambiguous
    "plugin://plugin.video.pov/build_movie_list",                 # POV never routes by path
    HELPER + "play&tmdb_type=movie&tmdb_id=1", HELPER + "textviewer", HELPER + "imageviewer",
    HELPER + "authenticate_trakt", HELPER + "dir_settings", HELPER + "dir_search", HELPER + "dir_multisearch",
    HELPER + "user_discover&method=edit", HELPER + "trakt_sync",
    IPLAYER + "1", IPLAYER + "104&keyword=x", IPLAYER + "118", IPLAYER + "119", IPLAYER + "122&url=x",
    IPLAYER + "142&url=x&state=watched", IPLAYER + "201&url=x", IPLAYER + "202&url=x", IPLAYER + "203&url=x",
    IPLAYER + "301&episode_id=x", IPLAYER + "302&episode_id=x",
])
def test_known_addon_routes_outside_the_allowlist_are_refused(source):
    assert route_guard.blocked_reason(source)
    with pytest.raises(ValueError):
        route_guard.check_directory(source)


def test_previous_false_positives_now_pass():
    # The action-word check read "now_playing", "playing" in a description and "play-school"
    # in an iPlayer programme URL as playback routes.
    for source in (HELPER + "now_playing&tmdb_type=movie",
                   IPLAYER + "128&url=x&description=Now+playing+on+BBC+One",
                   IPLAYER + "128&url=https%3A%2F%2Fwww.bbc.co.uk%2Fiplayer%2Fepisodes%2Fplay-school"):
        assert route_guard.blocked_reason(source) == "", source


def test_other_parameters_of_a_known_listing_are_still_checked():
    assert route_guard.blocked_reason(POV + "build_movie_list&action=delete_list") == "action=delete"
    assert route_guard.blocked_reason(POV + "build_movie_list&isFolder=false") == "not a folder"
    assert route_guard.blocked_reason(HELPER + "popular&tmdb_type=movie&command=clear_cache")


def test_bingie_widgets_lists_but_never_plays():
    widgets = "plugin://script.bingie.widgets/?action="
    for action in ("recent", "popular", "random", "newrelease", "forgenre", "inprogress", "inprogressnextepisode", "mylist", "similar"):
        assert route_guard.blocked_reason(widgets + action + "&mediatype=movies") == "", action
    assert route_guard.blocked_reason(widgets + "play&dbid=1")
    assert route_guard.blocked_reason("plugin://script.bingie.widgets/")
    assert route_guard.blocked_reason("plugin://script.bingie.widgets/?action=")


def test_kodi_manager_rows_check_their_source_too():
    listing = POV + "build_movie_list&action=trakt_watchlist"
    for mode in ("cached", "family"):
        assert route_guard.blocked_reason(SELF + mode + "&source=" + quote(listing, safe="") + "&pages=2") == ""
        assert route_guard.blocked_reason(SELF + mode + "&source=" + quote(POV + "play_media&tmdb_id=1", safe=""))
        assert route_guard.blocked_reason(SELF + mode + "&source=https%3A%2F%2Fexample.invalid%2F")
    assert route_guard.blocked_reason(SELF + "continue") == ""
    assert route_guard.blocked_reason(SELF + "rows") == ""
    assert route_guard.blocked_reason("plugin://service.kodi.addonadmin/") == ""
    assert route_guard.blocked_reason(SELF + "dashboard")
    nested = SELF + "cached&source=" + quote(SELF + "cached&source=" + quote(listing, safe=""), safe="")
    assert route_guard.blocked_reason(nested) == ""
    deeper = SELF + "cached&source=" + quote(nested, safe="")
    assert route_guard.blocked_reason(deeper)


def test_unknown_addons_fall_back_to_action_words():
    assert route_guard.blocked_reason("plugin://plugin.video.example/?mode=list&genre=playful") == ""
    assert route_guard.blocked_reason("plugin://plugin.video.example/?mode=tmdb_movies") == ""
    assert route_guard.blocked_reason("plugin://plugin.video.example/?route=play") == "route=play"
    assert route_guard.blocked_reason("plugin://plugin.video.example/play/1") == "path segment 'play'"


def test_item_actions_of_tmdb_helper_items_are_refused():
    helper_item = {"file": "plugin://plugin.video.tmdb.bingie.helper/?info=play&tmdb_type=movie&tmdb_id=603"}
    _props, actions = item_actions(helper_item, "movie", HELPER + "trakt_watchlist&tmdb_type=movie")
    assert actions
    for _label, action in actions:
        target = action[len("RunPlugin("):-1]
        with pytest.raises(ValueError):
            route_guard.check_directory(target)
    with pytest.raises(ValueError):
        route_guard.check_directory(helper_item["file"])


def test_every_allowlisted_route_is_accepted_on_its_own():
    for host, routes in route_guard.KNOWN_ROUTES.items():
        for route in routes.exact:
            source = "plugin://%s/?%s=%s" % (host, routes.key, route)
            if routes.nested:
                continue
            assert route_guard.blocked_reason(source) == "", source


# --- Queries an add-on's own parser reads differently ------------------------------------

@pytest.mark.parametrize("source", [
    # BBC iPlayer's get_params strips every '?', so "mo?de" is a second mode= (119 signs out).
    IPLAYER + "101&url=x&mo?de=119",
    IPLAYER + "101&url=x?&mode=119",
    IPLAYER + "101&url=x&?mode=119",
    POV + "build_movie_list&mo?de=play_media",
    # Parameter names outside [A-Za-z0-9_.-] (HTML-escaped '&', '+', spaces, percent signs).
    IPLAYER + "101&amp;mode=119",
    IPLAYER + "101&mo+de=119",
    IPLAYER + "101&mo%3Fde=119",
    IPLAYER + "101&%mode=119",
    IPLAYER + "101&=119",
    # Another spelling of the routing key.
    IPLAYER + "101&MODE=119",
    HELPER + "popular&Info=play",
    # A percent-encoded routing key is the same key, so it is a repeat.
    IPLAYER + "101&m%6Fde=119",
])
def test_queries_parsed_differently_by_the_addon_are_refused(source):
    assert route_guard.blocked_reason(source)
    with pytest.raises(ValueError):
        route_guard.check_directory(source)


def test_full_width_and_non_ascii_routes_are_refused():
    full_width_play = "ｐｌａｙ"
    assert route_guard.words(full_width_play) == ["play"]
    assert route_guard.action_word(full_width_play + "_media") == "play"
    # Unknown add-ons: the action-word fallback sees the folded word.
    assert route_guard.blocked_reason("plugin://plugin.video.example/?mode=" + full_width_play)
    assert route_guard.blocked_reason("plugin://plugin.video.example/?mode=" + quote(full_width_play))
    # Known add-ons: a routing value must be plain ASCII, even inside a listing family.
    assert route_guard.blocked_reason(POV + "build_trakt_" + full_width_play)
    assert route_guard.blocked_reason(HELPER + "trakt_é")
    assert route_guard.blocked_reason(IPLAYER + "１０１")  # full-width 101
    # Other parameters of a known listing are folded too.
    assert route_guard.blocked_reason(POV + "build_movie_list&action=" + full_width_play + "_media")


def test_listing_routes_with_plain_keys_still_pass_after_query_checks():
    for source in SKIN_AND_CACHE_LISTINGS + [
            IPLAYER + "101&url=x", IPLAYER + "101&url=x&", IPLAYER + "101&&url=x",
            HELPER + "popular&tmdb_type=movie&with_genres=16&page=2",
            POV + "build_movie_list&action=tmdb_movies_collection&key_id=10&iconImage=x.png"]:
        assert route_guard.blocked_reason(source) == "", source
    # Non-ASCII display text is still fine.
    assert route_guard.blocked_reason(IPLAYER + "128&url=x&name=Caf%C3%A9") == ""
