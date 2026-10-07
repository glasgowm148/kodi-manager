import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'kodi_manager'))
from widget_filters import filter_items, certification_age, MAX_RATING_OPTIONS
from widget_plugin import collect_family_directory, validate_source, render_directory, family_directory_url, directory_content, _set_video_info
from urllib.parse import urlsplit, parse_qs


def movie(mpaa, genre=None, **extra):
    return dict({'file': 'plugin://plugin.video.pov/?mode=play_media&tmdb_id=123', 'label': 'Example', 'filetype': 'file', 'mpaa': mpaa, 'genre': ['Family'] if genre is None else genre}, **extra)


class Index:
    def __init__(self, installed=True, enabled=True):
        self.addon = {'installed': installed, 'enabled': enabled}

    def get(self, aid):
        return self.addon if aid == 'plugin.video.pov' else None


class MediaViewTests(unittest.TestCase):
    def test_seasons_and_episodes_select_their_skin_views_including_empty_folders(self):
        for mode, content in [('build_season_list', 'seasons'), ('build_episode_list', 'episodes')]:
            self.assertEqual(directory_content({'source': 'plugin://plugin.video.pov/?mode=' + mode, 'files': []}), content)
        self.assertEqual(directory_content({'files': [{'type': 'unknown', 'season': 1, 'episode': -1, 'filetype': 'directory'}]}), 'seasons')
        self.assertEqual(directory_content({'files': [{'type': 'unknown', 'season': 1, 'episode': 2, 'filetype': 'file'}]}), 'episodes')
        self.assertEqual(directory_content({'files': [{'type': 'movie', 'season': -1, 'episode': -1}]}), 'movies')
        self.assertEqual(directory_content({'files': [{'type': 'movie'}, {'type': 'tvshow'}]}), 'videos')

    def test_native_metadata_and_resume_keep_episode_details_without_deprecated_calls(self):
        class Tag:
            def __getattr__(self, key):
                return lambda *args: calls.append((key, args))
        class Item:
            def getVideoInfoTag(self): return Tag()
            def setInfo(self, *args): self.fail()
            def setProperty(self, *args): self.fail()
            def fail(self): raise AssertionError('deprecated metadata method called')
        calls = []
        _set_video_info(Item(), {'title': 'Episode', 'tvshowtitle': 'Bluey', 'season': 3, 'episode': 2,
                                'genre': ['Kids'], 'mediatype': 'episode',
                                'lastplayed': '2026-10-03 09:26:00'}, {'position': 95, 'total': 420})
        self.assertIn(('setTvShowTitle', ('Bluey',)), calls)
        self.assertIn(('setEpisode', (2,)), calls)
        self.assertIn(('setGenres', (['Kids'],)), calls)
        self.assertIn(('setResumePoint', (95.0, 420.0)), calls)
        self.assertIn(('setLastPlayed', ('2026-10-03 09:26:00',)), calls)


class Kodi:
    def __init__(self, files):
        self.files, self.calls = files, []

    def jsonrpc(self, method, params):
        self.calls.append((method, params))
        return {'result': {'files': self.files}}


class WidgetFilterTests(unittest.TestCase):
    def paginated_kodi(self, pages):
        class Pages(Kodi):
            def jsonrpc(self, method, params):
                self.calls.append((method, params))
                return {'result': {'files': pages[params['directory']]}}
        return Pages([])

    def progress_page(self, number, mode='build_tvshow_list', action='in_progress_tvshows'):
        return 'plugin://plugin.video.pov/?mode=%s%s&new_page=%s' % (mode, '&action='+action if action else '', number)

    def next_page(self, path, **extra):
        number=parse_qs(urlsplit(path).query).get('new_page',['2'])[0]
        return dict(file=path, label='[B][COLOR aqua]Next Page >> %s <<[/COLOR][/B]' % number, filetype='directory', **extra)

    def test_only_explicit_family_with_ratings_at_or_below_limit(self):
        safe = [movie(rating) for rating in ('UK: U', 'Rated PG', '12', '12A', 'PG-13', 'TV-Y', 'TV-Y7', 'TV-Y7-FV', 'TV-G', 'TV-PG')]
        rejected = [movie('15'), movie('R'), movie('TV-14'), movie('Unrated'), movie(''), movie('PG', ['Animation']), movie('PG', ['Comedy'])]
        result = filter_items(safe + rejected)
        self.assertEqual(result['files'], safe)
        self.assertEqual(result['excluded_counts']['above_rating'], 3)
        self.assertEqual(result['excluded_counts']['unknown_rating'], 2)
        self.assertEqual(result['excluded_counts']['non_family_genre'], 2)

    def test_preserves_original_items_urls_art_resume_and_context(self):
        item = movie('PG', art={'poster': 'source-poster'}, resume={'position': 35, 'total': 100}, properties={'source': 'pov'}, contextmenu=[('Source options', 'source command')])
        result = filter_items([item])
        self.assertIs(result['files'][0], item)
        self.assertEqual(result['files'][0]['file'], item['file'])

    def test_unknown_unrated_and_review_scores_never_qualify(self):
        items = [movie('NR'), movie('Not Rated (PG-13)'), movie('not yet rated'), movie('TBC'), movie(''), movie('FSK 16'), movie('AU: M / US: G')]
        items.append({'label': 'Review rating only', 'rating': 7.9, 'genre': ['Family']})
        result = filter_items(items)
        self.assertEqual(result['included_count'], 0)
        self.assertEqual(result['excluded_counts']['unknown_rating'], len(items))

    def test_options_and_family_toggle(self):
        self.assertEqual(MAX_RATING_OPTIONS, ('U', 'PG', '12A', '15'))
        self.assertEqual(filter_items([movie('PG')], 'U')['included_count'], 0)
        self.assertEqual(filter_items([movie('12A')], 'PG')['included_count'], 0)
        self.assertEqual(filter_items([movie('TV-14')], '15')['included_count'], 1)
        self.assertEqual(filter_items([movie('PG', ['Animation'])], family_only=False)['included_count'], 1)
        with self.assertRaises(ValueError):
            filter_items([], '18')

    def test_nested_metadata_and_conservative_multi_country_rating(self):
        item = {'label': 'Children item', 'file': 'original', 'info': {'video': {'mpaa': 'PG-13', 'genre': 'Children / Adventure'}}}
        self.assertEqual(filter_items([item])['included_count'], 1)
        self.assertEqual(certification_age(movie('US: PG-13 / UK: 15')), 15)
        self.assertEqual(filter_items([movie('US: PG-13 / UK: 15')])['included_count'], 0)

    def test_conflicting_nested_and_unknown_compound_ratings_fail_closed(self):
        self.assertEqual(certification_age(movie('PG', info={'video': {'mpaa': '18'}})), 18)
        for rating in ('US: G + AU: M', 'US: G AU: M', 'PG / FSK 16'):
            self.assertIsNone(certification_age(movie(rating)))
        self.assertIsNone(certification_age(movie('PG', metadata={'certification': {'AU': 'M'}})))

    def test_menu_folders_and_pagination_return_empty_honestly(self):
        result = filter_items([{'label': 'Movies', 'filetype': 'directory', 'file': 'original'}, movie('PG', label='Next page')])
        self.assertEqual(result['files'], [])
        self.assertEqual(result['excluded_counts']['pagination'], 1)

    def test_validated_source_invokes_only_directory_method(self):
        item = movie('PG')
        kodi = Kodi([item, movie('18')])
        source = 'plugin://plugin.video.pov/?mode=tmdb_movies&genre=10751'
        result = collect_family_directory(kodi, Index(), source)
        self.assertEqual(result['files'], [item])
        self.assertEqual(result['source'], source)
        self.assertEqual(len(kodi.calls), 1)
        self.assertEqual(kodi.calls[0][0], 'Files.GetDirectory')
        self.assertEqual(kodi.calls[0][1]['directory'], source)

    def test_rejects_recursion_nonvideo_actions_and_disabled_addons(self):
        sources = ['plugin://service.kodi.addonadmin/?mode=family', 'http://example.invalid/', 'plugin://script.trakt/',
                   'plugin://plugin.video.pov/?mode=play_media', 'plugin://plugin.video.pov/?mode=playNextEpisode',
                   'plugin://plugin.video.pov/resolve/123', 'plugin://plugin.video.pov/%70lay/123', 'plugin://plugin.video.pov/?action=clear_cache',
                   'plugin://plugin.video.pov/?mode=trakt_sync', 'plugin://plugin.video.missing/']
        sources += ['plugin://plugin.video.pov/?info=play', 'plugin://plugin.video.pov/?mode=search',
                    'plugin://plugin.video.pov/?isfolder=false', 'plugin://plugin.video.pov/tools/']
        for source in sources:
            with self.subTest(source=source), self.assertRaises(ValueError):
                collect_family_directory(Kodi([]), Index(), source)
        for installed, enabled in ((False, True), (True, False), (None, True), (True, None)):
            with self.assertRaises(ValueError):
                validate_source(Index(installed, enabled), 'plugin://plugin.video.pov/')

    def test_invalid_filter_does_not_query_source(self):
        kodi = Kodi([])
        with self.assertRaises(ValueError):
            collect_family_directory(kodi, Index(), 'plugin://plugin.video.pov/', max_rating='18')
        self.assertEqual(kodi.calls, [])

    def test_missing_directory_result_is_not_an_empty_success(self):
        kodi = Kodi([])
        for reply in ({'result': {}}, {'result': {'files': None}}, {'result': 'OK'}):
            kodi.jsonrpc = lambda *args, reply=reply: reply
            with self.assertRaisesRegex(ValueError, 'no directory listing'):
                collect_family_directory(kodi, Index(), 'plugin://plugin.video.pov/')

    def test_nested_directory_filter_is_persisted_and_reapplied(self):
        folder = 'plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=123'
        wrapped = family_directory_url(folder, 'PG', True)
        query = parse_qs(urlsplit(wrapped).query)
        self.assertEqual(query['source'], [folder])
        safe, mature = movie('PG'), movie('15')
        result = collect_family_directory(Kodi([safe, mature]), Index(), query['source'][0], query['max_rating'][0], query['family_only'][0] == 'true')
        self.assertEqual(result['files'], [safe])

    def test_directory_render_retains_original_context(self):
        class ListItem:
            def __init__(self, **kwargs):
                self.kwargs, self.properties = kwargs, {}
            def setInfo(self, kind, info): self.info = info
            def setArt(self, art): self.art = art
            def setProperty(self, key, value): self.properties[key] = value
            def addContextMenuItems(self, items): self.context = items
        class GUI:
            pass
        GUI.ListItem = ListItem
        class Plugin:
            def setContent(self, *args): pass
            def addDirectoryItem(self, handle, url, item, isFolder=False): self.added = (url, item, isFolder)
            def endOfDirectory(self, handle, **kwargs): self.ended = kwargs
        plugin = Plugin()
        item = movie('PG', file='plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=123', filetype='directory', showtitle='Mickey Mouse', info={'video': {'showtitle': 'Nested original'}}, resume={'position': 3, 'total': 90}, art={'poster': 'original-poster'}, contextmenu=[('Source', 'original-command')])
        render_directory(GUI, plugin, 1, filter_items([item]))
        self.assertEqual(parse_qs(urlsplit(plugin.added[0]).query)['source'], [item['file']])
        self.assertEqual(urlsplit(plugin.added[0]).netloc, 'service.kodi.addonadmin')
        self.assertTrue(plugin.added[2])
        self.assertEqual(plugin.added[1].art, item['art'])
        self.assertEqual(plugin.added[1].context, item['contextmenu'])
        self.assertEqual(plugin.added[1].properties['ResumeTime'], '3')
        self.assertEqual(plugin.added[1].info['tvshowtitle'], 'Mickey Mouse')
        self.assertNotIn('showtitle', plugin.added[1].info)
        self.assertEqual(item['showtitle'], 'Mickey Mouse')
        self.assertEqual(item['info']['video']['showtitle'], 'Nested original')
        self.assertNotIn('IsPlayable', plugin.added[1].properties)
        self.assertEqual(plugin.ended, {'succeeded': True, 'cacheToDisc': False})
        playable = movie('PG')
        render_directory(GUI, plugin, 1, filter_items([playable]))
        self.assertEqual(plugin.added[0], playable['file'])
        self.assertFalse(plugin.added[2])
        self.assertEqual(plugin.added[1].properties['IsPlayable'], 'true')

    def test_personal_progress_follows_only_observed_next_pages_and_keeps_later_kids(self):
        first='plugin://plugin.video.pov/?name=32481&iconImage=in_progress_tvshow.png&mode=build_tvshow_list&action=in_progress_tvshows'
        second, third = ['plugin://plugin.video.pov/?new_page=%s&mode=build_tvshow_list&action=in_progress_tvshows&exit_list_params=&name=In+Progress+TV+Shows' % n for n in (2,3)]
        safe1=movie('PG',file='plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=10',filetype='directory')
        safe2=movie('TV-Y',file='plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=11',filetype='directory',label='Later-page child show')
        mature=movie('TV-MA',file='plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=12',filetype='directory')
        kodi=self.paginated_kodi({first:[safe1,self.next_page(second)],second:[mature,safe1,self.next_page(third)],third:[safe2]})
        result=collect_family_directory(kodi,Index(),first)
        self.assertEqual(result['files'],[safe1,safe2])
        self.assertEqual([params['directory'] for _,params in kodi.calls],[first,second,third])
        self.assertTrue(all(method=='Files.GetDirectory' for method,_ in kodi.calls))
        self.assertEqual(result['pagination']['pages_read'],3)
        self.assertEqual(result['pagination']['items_read'],3)
        self.assertFalse(result['pagination']['truncated'])

    def test_progress_pagination_rejects_other_addons_changed_routes_playback_and_loops(self):
        first=self.progress_page(1)
        invalid=[self.progress_page(2).replace('plugin.video.pov','plugin.video.other'),
                 self.progress_page(2).replace('in_progress_tvshows','trakt_tv_popular'),
                 'plugin://plugin.video.pov/?mode=play_media&new_page=2',
                 'plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=12&new_page=2',
                 first,self.progress_page(4),self.progress_page(2)+'&command=delete',
                 self.progress_page(2)+'&new_page=3']
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                kodi=self.paginated_kodi({first:[movie('PG'),self.next_page(candidate)]})
                result=collect_family_directory(kodi,Index(),first)
                self.assertEqual(len(kodi.calls),1)
                self.assertTrue(result['pagination']['truncated'])
                self.assertIn(result['pagination']['reason'],['unsafe_next_page','pagination_loop'])

    def test_arbitrary_lists_seasons_and_non_directory_next_labels_are_not_paginated(self):
        for source in ['plugin://plugin.video.pov/?mode=build_tvshow_list&action=trakt_tv_popular',
                       'plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=10',
                       'plugin://plugin.video.pov/?mode=build_episode_list&tmdb_id=10&season=1']:
            kodi=self.paginated_kodi({source:[movie('PG'),self.next_page(self.progress_page(2))]})
            result=collect_family_directory(kodi,Index(),source)
            self.assertEqual(len(kodi.calls),1)
            self.assertFalse(result['pagination']['eligible'])
        source=self.progress_page(1)
        kodi=self.paginated_kodi({source:[movie('PG'),dict(self.next_page(self.progress_page(2)),filetype='file')]})
        collect_family_directory(kodi,Index(),source)
        self.assertEqual(len(kodi.calls),1)

    def test_next_episode_and_resume_roots_support_typed_pagination_without_fetching_leaves(self):
        for mode in ['build_next_episode','build_in_progress_episode']:
            first,second=[self.progress_page(n,mode,'') for n in (1,2)]
            leaf=movie('TV-Y',label='Episode',season=1,episode=2)
            kodi=self.paginated_kodi({first:[self.next_page(second)],second:[leaf]})
            result=collect_family_directory(kodi,Index(),first)
            self.assertEqual(result['files'],[leaf])
            self.assertEqual([params['directory'] for _,params in kodi.calls],[first,second])

    def test_progress_page_and_title_caps_report_truncation_without_extra_fetch(self):
        paths=[self.progress_page(n) for n in range(1,8)]
        pages={path:[movie('PG',file='original-%s'%i),self.next_page(paths[i+1])] for i,path in enumerate(paths[:-1])}
        kodi=self.paginated_kodi(pages)
        result=collect_family_directory(kodi,Index(),paths[0])
        self.assertEqual(len(kodi.calls),6)
        self.assertEqual(result['pagination']['reason'],'page_limit')
        self.assertTrue(result['pagination']['truncated'])
        kodi=self.paginated_kodi({paths[0]:[movie('PG',file='original-%s'%i) for i in range(601)]+[self.next_page(paths[1])]})
        result=collect_family_directory(kodi,Index(),paths[0])
        self.assertEqual(len(kodi.calls),1)
        self.assertEqual(result['included_count'],600)
        self.assertEqual(result['pagination']['reason'],'item_limit')


if __name__ == '__main__':
    unittest.main()
