import os
import sys
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "kodi_manager"))
from widget_catalog import browse_directory, list_sources, folder_usefulness


class Index:
    def get(self, aid):
        return {"addon_id": aid, "name": "POV", "installed": True, "enabled": aid == "plugin.video.pov"} if aid in ("plugin.video.pov", "plugin.video.off") else None
    def refresh(self): pass
    def list(self): return [self.get("plugin.video.pov"), self.get("plugin.video.off")]


class Kodi:
    def __init__(self): self.calls = []
    def jsonrpc(self, method, params):
        self.calls.append((method, params))
        return {"result": {"files": [{"label": "[B]Family[/B]", "file": "plugin://plugin.video.pov/?mode=build_movie_list&action=family", "filetype": "directory"}, {"title": "Example", "label": "Example", "file": "plugin://plugin.video.pov/?mode=play", "filetype": "file", "year": 2024, "mpaa": "PG", "genre": ["Family"]}], "limits": {"start": 0, "end": 2, "total": 2}}}


class CatalogTests(unittest.TestCase):
    def test_usefulness_prioritizes_general_pov_discovery_with_modest_current_boost(self):
        path = 'plugin://plugin.video.pov/?mode=build_movie_list&action=popular'
        current = folder_usefulness('Languages', path, 'plugin.video.pov', current_paths=[path])
        popular = folder_usefulness('Popular', path, 'plugin.video.pov')
        latest = folder_usefulness('Latest Releases', path, 'plugin.video.pov')
        watchlist = folder_usefulness('Watchlist', path, 'plugin.video.pov')
        recommendation = folder_usefulness('Because You Watched...', path, 'plugin.video.pov')
        taxonomy = folder_usefulness('Languages', path, 'plugin.video.pov')
        self.assertLess(current['score'], popular['score'])
        self.assertGreater(current['score'], taxonomy['score'])
        self.assertGreater(popular['score'], watchlist['score'])
        self.assertGreater(latest['score'], watchlist['score'])
        self.assertGreater(watchlist['score'], recommendation['score'])
        self.assertGreater(recommendation['score'], taxonomy['score'])
        self.assertTrue(popular['inferred'])
        self.assertIn('Popular', popular['reason'])

    def test_usefulness_explains_known_media_family_genres_and_utility_penalties(self):
        path = 'plugin://plugin.video.pov/?mode=build_movie_list'
        menu = folder_usefulness('Drama', path, 'plugin.video.pov', breadcrumb=['POV', 'Movies', 'Genres'])
        family = folder_usefulness('Family', path, 'plugin.video.pov', breadcrumb=['POV', 'Movies', 'Genres'])
        media = folder_usefulness('Drama', path, 'plugin.video.pov', classification='media_list')
        utility = folder_usefulness('Settings', path, 'plugin.video.pov')
        self.assertGreater(family['score'], menu['score'])
        self.assertGreater(media['score'], menu['score'])
        self.assertEqual(utility['score'],0)
        self.assertIn('POV route', media['reason'])
        self.assertEqual(media['score'], folder_usefulness('Drama', path, 'plugin.video.pov')['score'])
        self.assertGreater(folder_usefulness('Popular', path, 'plugin.video.pov')['score'], folder_usefulness('Popular', path, 'plugin.video.other')['score'])

    def test_direct_title_lists_rank_above_popular_user_list_catalogues(self):
        direct = 'plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_latest_releases'
        users = 'plugin://plugin.video.pov/?mode=trakt_lists&action=popular'
        latest = folder_usefulness('Latest Releases', direct, 'plugin.video.pov')
        catalogue = folder_usefulness('TRAKT: Popular User Lists', users, 'plugin.video.pov')
        self.assertGreater(latest['score'], catalogue['score'])
        self.assertIn('another folder selection', catalogue['reason'])
        progress = folder_usefulness('In Progress', direct, 'plugin.video.pov')
        watchlist = folder_usefulness('Watchlist', direct, 'plugin.video.pov')
        self.assertGreater(progress['score'], watchlist['score'])
        self.assertEqual(latest, folder_usefulness('Latest Releases', direct, 'plugin.video.pov', classification='media_list'))

    def test_overlapping_discovery_labels_do_not_accumulate_primary_bonuses(self):
        other_path = 'plugin://plugin.video.other/?mode=list&category=trending_recent'
        generic = folder_usefulness('Trending Recent', other_path, 'plugin.video.other')
        self.assertEqual(generic['score'], folder_usefulness('Trending', other_path, 'plugin.video.other')['score'])
        for label in ('Popular', 'Latest Releases'):
            direct = 'plugin://plugin.video.pov/?mode=build_movie_list&action=' + label.lower().replace(' ', '_')
            self.assertGreater(folder_usefulness(label, direct, 'plugin.video.pov')['score'], generic['score'])

    def listing(self, files, total=None):
        kodi = Kodi()
        def request(method, params):
            kodi.calls.append((method, params))
            return {'result': {'files': files, 'limits': {'start': 0, 'end': len(files), 'total': len(files) if total is None else total}}}
        kodi.jsonrpc = request
        return kodi

    def folder(self, label, route='navigator', **metadata):
        return dict({'label': label, 'filetype': 'directory', 'file': 'plugin://plugin.video.pov/?mode=' + route}, **metadata)

    def test_automatic_children_are_safe_menu_routes_only(self):
        kodi = self.listing([
            self.folder('Movies', 'navigator_movies'), self.folder('TV Shows', 'navigator_tvshows'),
            self.folder('A show', 'build_season_list', type='tvshow', year=2025),
            self.folder('Season 1', 'build_episode_list', type='season', season=1),
            self.folder('Settings', 'navigator_settings'), self.folder('Search', 'navigator_search'),
            self.folder('My Services', 'navigator'), self.folder('Next page', 'build_movie_list&page=2'),
            self.folder('Malformed', file={'invalid': 'url'}),
        ])
        result = browse_directory(kodi, Index(), 'plugin://plugin.video.pov/')
        self.assertEqual([child['label'] for child in result['children']], ['Movies', 'TV Shows'])
        self.assertEqual(result['classification'], 'mixed')
        self.assertTrue(result['traversable'])
        self.assertTrue(result['can_use_as_widget'])
        self.assertEqual(len(result['skips']), 7)
        self.assertEqual(next(item for item in result['items'] if item['label'] == 'Malformed')['classification'], 'blocked')
        self.assertEqual(len(kodi.calls), 1)

    def test_media_list_does_not_expand_shows_seasons_or_filter_other_genres(self):
        kodi = self.listing([self.folder('Show one', 'build_season_list', type='tvshow', genre=['Horror']),
                             self.folder('Specials', 'build_episode_list', type='season', season=0),
                             self.folder('Next page', 'build_tvshow_list&page=2')])
        result = browse_directory(kodi, Index(), 'plugin://plugin.video.pov/?mode=build_tvshow_list')
        self.assertEqual(result['classification'], 'media_list')
        self.assertFalse(result['traversable'])
        self.assertTrue(result['can_use_as_widget'])
        self.assertEqual(result['children'], [])
        self.assertEqual(result['items'][0]['genre'], ['Horror'])
        self.assertEqual(result['sample']['returned'], 2)
        self.assertEqual(result['sample']['pagination_count'], 1)
        self.assertTrue(result['sample']['truncated'])
        self.assertIn('Truncated', result['sample']['message'])

    def test_remote_limit_and_local_bounds_are_explicit_samples(self):
        kodi = self.listing([self.folder('Movies')], total=500)
        result = browse_directory(kodi, Index(), 'plugin://plugin.video.pov/')
        self.assertTrue(result['sample']['truncated'])
        self.assertEqual(result['sample']['total'], 500)
        self.assertEqual(result['sample']['returned'], 0)
        self.assertEqual(result['sample']['menu_count'], 1)
        kodi = self.listing([self.folder('Movies'), self.folder('TV Shows')])
        result = browse_directory(kodi, Index(), 'plugin://plugin.video.pov/', limit=1)
        self.assertEqual(len(result['items']), 1)
        self.assertTrue(result['sample']['truncated'])

    def test_cache_returns_copies_refreshes_all_path_pages_and_expires(self):
        kodi = self.listing([self.folder('Movies')])
        index = Index()
        first = browse_directory(kodi, index, 'plugin://plugin.video.pov/')
        first['items'][0]['label'] = 'Changed by UI'
        cached = browse_directory(kodi, index, 'plugin://plugin.video.pov/')
        self.assertTrue(cached['cache']['hit'])
        self.assertEqual(cached['items'][0]['label'], 'Movies')
        self.assertEqual(len(kodi.calls), 1)
        browse_directory(kodi, index, 'plugin://plugin.video.pov/', start=48)
        fresh = browse_directory(kodi, index, 'plugin://plugin.video.pov/', refresh=True)
        self.assertFalse(fresh['cache']['hit'])
        browse_directory(kodi, index, 'plugin://plugin.video.pov/', start=48)
        self.assertEqual(len(kodi.calls), 4)
        with patch('widget_catalog._CACHE_TTL', 0):
            expired = browse_directory(kodi, index, 'plugin://plugin.video.pov/')
        self.assertFalse(expired['cache']['hit'])
        self.assertEqual(len(kodi.calls), 5)

    def test_cached_directory_still_revalidates_source_enablement(self):
        kodi = self.listing([self.folder('Movies')])
        index = Index()
        browse_directory(kodi, index, 'plugin://plugin.video.pov/')
        index.get = lambda aid: {'installed': True, 'enabled': False}
        with self.assertRaises(ValueError):
            browse_directory(kodi, index, 'plugin://plugin.video.pov/')
        self.assertEqual(len(kodi.calls), 1)

    def test_concurrent_catalog_requests_bound_rpc_concurrency(self):
        kodi = Kodi()
        lock = threading.Lock()
        current = maximum = 0
        def request(method, params):
            nonlocal current, maximum
            with lock:
                current += 1
                maximum = max(maximum, current)
            time.sleep(0.005)
            with lock:
                current -= 1
            return {'result': {'files': []}}
        kodi.jsonrpc = request
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: browse_directory(kodi, Index(), 'plugin://plugin.video.pov/?mode=navigator&menu=' + str(n)), range(8)))
        self.assertLessEqual(maximum, 2)
        self.assertTrue(all(result['classification'] == 'empty' for result in results))

    def test_real_directory_metadata_and_paths_preserved(self):
        kodi = Kodi()
        result = browse_directory(kodi, Index(), "plugin://plugin.video.pov/")
        self.assertEqual(kodi.calls[0][0], "Files.GetDirectory")
        self.assertEqual(result["items"][0]["label"], "Family")
        self.assertTrue(result["items"][0]["browseable"])
        self.assertFalse(result["items"][1]["browseable"])
        self.assertEqual(result["items"][1]["mpaa"], "PG")
        self.assertTrue(result["contains_media"])

    def test_refuses_nonfolders_actions_and_disabled_addons_without_rpc(self):
        for path in ["file:///etc/passwd", "plugin://plugin.video.unknown/", "plugin://plugin.video.off/", "plugin://plugin.video.pov/?mode=play", "plugin://plugin.video.pov/?mode=navigator.settings", "plugin://plugin.video.pov/?isFolder=false", "plugin://plugin.video.pov/play/123", "plugin://plugin.video.pov/?info=play", "plugin://plugin.video.pov/?command=reset_cache"]:
            with self.subTest(path=path):
                kodi = Kodi()
                with self.assertRaises(ValueError): browse_directory(kodi, Index(), path)
                self.assertEqual(kodi.calls, [])

    def test_sources_preserve_enablement(self):
        result = list_sources(Kodi(), Index())
        self.assertEqual(result["sources"][0]["addon_id"], "plugin.video.pov")
        self.assertFalse(result["sources"][1]["enabled"])

    def test_errors_not_reported_as_empty_folders(self):
        kodi = Kodi()
        kodi.jsonrpc = lambda *a: {"error": {"message": "Provider unavailable"}}
        with self.assertRaisesRegex(ValueError, "Provider unavailable"):
            browse_directory(kodi, Index(), "plugin://plugin.video.pov/")


if __name__ == "__main__": unittest.main()
