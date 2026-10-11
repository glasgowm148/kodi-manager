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
