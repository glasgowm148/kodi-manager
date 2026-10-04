import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import widget_preview
import server
from widget_plugin import family_directory_url


class SavedRowPreviewTests(unittest.TestCase):
    def setUp(self):
        self.path = 'plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular'
        self.row = {'id': 'saved-1', 'label': 'Popular', 'path': self.path,
                    'action': 'ActivateWindow(Videos,"%s",return)' % self.path}
        self.layout = {'sections': [{'id': 'home', 'rows': [self.row]}]}
        self.index = SimpleNamespace(get=lambda aid: {'installed': True, 'enabled': aid != 'plugin.video.off'} if aid in ('plugin.video.pov', 'plugin.video.off', 'script.bingie.widgets') else None)
        self.kodi = SimpleNamespace(jsonrpc=Mock(return_value={'result': {'files': [{'label': 'Example', 'type': 'movie', 'year': 2024, 'file': 'videodb://movies/titles/1/'}], 'limits': {'start': 0, 'end': 1, 'total': 1}}}))
        self.layout_patch = patch.object(widget_preview, 'inspect_layout', return_value=self.layout)
        self.layout_patch.start()
        self.addCleanup(self.layout_patch.stop)

    def preview(self, **body):
        return widget_preview.row_preview(self.kodi, self.index, {'section_id': 'home', 'row_id': 'saved-1', **body})

    def saved_family_row(self, source=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.manager_path = folder.name
        (Path(folder.name) / 'addon.xml').write_text('<addon id="service.kodi.addonadmin"><extension point="xbmc.python.pluginsource" library="resources/lib/widget_plugin.py"><provides>video</provides></extension></addon>')
        old_get = self.index.get
        self.index.get = lambda aid: {'installed': True, 'enabled': True, 'path': folder.name} if aid == 'service.kodi.addonadmin' else old_get(aid)
        source = source or 'plugin://plugin.video.pov/?mode=build_tvshow_list&action=in_progress_tvshows'
        path = family_directory_url(source, '12A', True)
        self.row.update(path=path, action='ActivateWindow(Videos,%s,return)' % path)
        return source, path

    def test_saved_plugin_source_and_action_remain_exact(self):
        result = self.preview(limit=7)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['source'], {key: self.row[key] for key in ('label', 'path', 'action')})
        self.assertEqual(result['resolved_path'], self.path)
        self.kodi.jsonrpc.assert_called_once()
        method, params = self.kodi.jsonrpc.call_args.args
        self.assertEqual(method, 'Files.GetDirectory')
        self.assertEqual(params['directory'], self.path)
        self.assertEqual(params['limits'], {'start': 0, 'end': 7})

    def test_saved_family_preview_collects_all_observed_progress_pages_before_limiting_items(self):
        source, wrapper = self.saved_family_row()
        next_path = source + '&new_page=2'
        def movie(number, rating='PG'):
            return {'label': 'Family show %s' % number, 'type': 'tvshow', 'filetype': 'directory', 'file': 'plugin://plugin.video.pov/?mode=build_season_list&tvshow_id=%s' % number, 'mpaa': rating, 'genre': ['Family'], 'year': 2025}
        pages = {source: [movie(i) for i in range(40)] + [movie('unrated', 'NR'), movie('adult', '18'), {'label': 'Next Page', 'filetype': 'directory', 'file': next_path}], next_path: [movie(i) for i in range(40, 50)]}
        self.kodi.jsonrpc.side_effect = lambda method, params: {'result': {'files': pages[params['directory']]}}
        result = self.preview(limit=48)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['items']), 48)
        self.assertEqual(result['limits'], {'start': 0, 'end': 48, 'total': 50})
        self.assertEqual(result['included_count'], 50)
        self.assertEqual(result['input_count'], 52)
        self.assertEqual(result['pagination']['pages_read'], 2)
        self.assertEqual(result['pagination']['items_read'], 52)
        self.assertFalse(result['pagination']['truncated'])
        self.assertTrue(result['sample']['truncated'])
        self.assertTrue(all(item['classification'] == 'media' for item in result['items']))
        self.assertEqual(result['source']['path'], wrapper)
        self.assertEqual(result['source']['action'], self.row['action'])
        self.assertEqual([call.args[1]['directory'] for call in self.kodi.jsonrpc.call_args_list], [source, next_path])
        self.assertTrue(all(call.args[0] == 'Files.GetDirectory' for call in self.kodi.jsonrpc.call_args_list))
        self.assertTrue(all('limits' not in call.args[1] for call in self.kodi.jsonrpc.call_args_list))

    def test_saved_family_preview_reports_collector_pagination_bounds(self):
        source, wrapper = self.saved_family_row()
        def listing(method, params):
            path = params['directory']
            page = int(path.rsplit('new_page=', 1)[1]) if 'new_page=' in path else 1
            return {'result': {'files': [{'label': 'Family show %s' % page, 'type': 'tvshow', 'filetype': 'directory', 'file': 'plugin://plugin.video.pov/?tvshow_id=%s' % page, 'mpaa': 'PG', 'genre': ['Family']}, {'label': 'Next Page', 'filetype': 'directory', 'file': source + '&new_page=%s' % (page + 1)}]}}
        self.kodi.jsonrpc.side_effect = listing
        result = self.preview(limit=12)
        self.assertEqual(result['limits']['total'], 6)
        self.assertEqual(result['pagination']['pages_read'], 6)
        self.assertTrue(result['pagination']['truncated'])
        self.assertEqual(result['pagination']['reason'], 'page_limit')
        self.assertTrue(result['sample']['truncated'])
        self.assertEqual(self.kodi.jsonrpc.call_count, 6)
        self.assertIn('counts cover the collected pages', result['sample']['message'])

    def test_family_watchlist_reload_token_preserves_source_and_rating_filter(self):
        source, wrapper = self.saved_family_row()
        self.row['path'] = wrapper + '&reload=123'
        with patch.object(widget_preview, 'collect_family_directory', return_value={
                'files': [], 'included_count': 0, 'input_count': 0,
                'excluded_counts': {}, 'max_rating': '12A', 'family_only': True,
                'pagination': {'truncated': False}}) as collect:
            result = self.preview()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['resolved_path'], wrapper + '&reload=123')
        collect.assert_called_once_with(self.kodi, self.index, source, '12A', True)

    def test_malformed_saved_family_routes_and_missing_extension_never_list_directories(self):
        source, wrapper = self.saved_family_row()
        for path in (wrapper + '&extra=true', wrapper + '&max_rating=PG', wrapper.replace('max_rating=12A', 'max_rating=18'), family_directory_url('plugin://plugin.video.pov/?mode=play_media'), wrapper.replace('?mode=family', '?mode=play')):
            with self.subTest(path=path):
                self.row['path'] = path
                result = self.preview()
                self.assertEqual(result['status'], 'unsupported')
        self.row['path'] = wrapper
        (Path(self.manager_path) / 'addon.xml').write_text('<addon id="service.kodi.addonadmin"/>')
        self.assertEqual(self.preview()['status'], 'unsupported')
        (Path(self.manager_path) / 'addon.xml').write_text('<invalid')
        self.assertEqual(self.preview()['status'], 'unsupported')
        self.kodi.jsonrpc.assert_not_called()

    def test_new_popular_variable_is_a_path_and_label_resolves_in_kodi(self):
        self.row.update(path='', action='$VAR[DefNewHubContent]', label='$VAR[DefNewHubName]')
        info = Mock(side_effect=lambda expression: {'$VAR[DefNewHubContent]': self.path, '$VAR[DefNewHubName]': '[B]Latest releases[/B]'}[expression])
        with patch.object(widget_preview, 'xbmc', SimpleNamespace(getInfoLabel=info)):
            result = self.preview()
        self.assertEqual(result['resolved_label'], 'Latest releases')
        self.assertEqual(result['resolved_path'], self.path)
        self.assertEqual(result['source']['action'], '$VAR[DefNewHubContent]')
        self.assertEqual(self.row['action'], '$VAR[DefNewHubContent]')
        self.assertEqual(result['resolution'], 'Kodi getInfoLabel')

    def test_mixed_info_expression_and_activatewindow_are_resolved_without_execution(self):
        original = self.path + '&reload=$INFO[Window(Home).Property(widgetreload)]'
        self.row.update(path='', action='ActivateWindow(Videos,"%s",return)' % original)
        resolved = self.row['action'].replace('$INFO[Window(Home).Property(widgetreload)]', '123')
        with patch.object(widget_preview, 'xbmc', SimpleNamespace(getInfoLabel=Mock(return_value=resolved))):
            result = self.preview()
        self.assertEqual(result['resolved_path'], self.path + '&reload=123')
        self.assertEqual(result['source']['action'], self.row['action'])
        self.assertEqual(self.kodi.jsonrpc.call_args.args[0], 'Files.GetDirectory')

    def test_all_observed_new_popular_content_variables_use_the_runtime_directory(self):
        # The deployed IncludesPaths.xml defines an unnumbered variable and 1–3.
        for name in ('DefNewHubContent', 'DefNewHub1Content', 'DefNewHub2Content', 'DefNewHub3Content'):
            expression = '$VAR[%s]' % name
            self.row.update(path='', action=expression, raw_label='$VAR[DefNewHubName]', label='Saved label')
            info = lambda value: '[CAPITALIZE]Latest releases[/CAPITALIZE]' if value == self.row['raw_label'] else self.path
            with self.subTest(name=name), patch.object(widget_preview, 'xbmc', SimpleNamespace(getInfoLabel=info)):
                result = self.preview()
                self.assertEqual(result['resolved_path'], self.path)
                self.assertEqual(result['resolved_label'], 'Latest releases')
                self.assertEqual(result['source']['action'], expression)
                self.assertEqual(result['source']['label'], 'Saved label')

    def test_unresolved_optional_reload_is_removed_without_changing_route_or_saved_source(self):
        self.row['path'] += '&reload=$INFO[Window(Home).Property(widgetreload)]&sort=rank'
        with patch.object(widget_preview, 'xbmc', SimpleNamespace(getInfoLabel=lambda value: value)):
            result = self.preview()
        self.assertEqual(result['resolved_path'], self.path + '&sort=rank')
        self.assertIn('$INFO[', result['source']['path'])
        self.assertEqual(result['status'], 'ok')

    def test_unresolved_main_variable_has_a_diagnostic_and_no_directory_request(self):
        self.row.update(path='', action='$VAR[DefNewHub2Content]')
        for api in (None, SimpleNamespace(getInfoLabel=lambda _: ''), SimpleNamespace(getInfoLabel=lambda value: value)):
            with self.subTest(api=api), patch.object(widget_preview, 'xbmc', api):
                result = self.preview()
                self.assertEqual(result['status'], 'unresolved')
                self.assertIn('skin variable', result['reason'])
        self.kodi.jsonrpc.assert_not_called()

    def test_only_saved_ids_and_bounded_limits_are_accepted(self):
        for body in ({'row_id': 'unknown'}, {'section_id': 'unknown'}, {'path': 'special://videoplaylists/'}, {'action': 'PlayMedia(x)'}, {'limit': 49}, {'limit': True}, {'limit': '4'}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.preview(**body)
        self.kodi.jsonrpc.assert_not_called()

    def test_native_directories_are_read_only_and_preview_media_metadata(self):
        for path in ('special://videoplaylists/', 'special://videoplaylists/Recent.xsp', 'addons://sources/video/', 'videodb://movies/titles/', 'videodb://tvshows/titles/', 'library://video/movies/titles.xml'):
            with self.subTest(path=path):
                self.kodi.jsonrpc.reset_mock()
                self.row.update(path=path, action='ActivateWindow(Videos,%s,return)' % path)
                result = self.preview(limit=4)
                self.assertEqual(result['status'], 'ok')
                self.assertEqual(result['items'][0]['title'], 'Example')
                self.assertEqual(result['items'][0]['classification'], 'media')
                self.assertFalse(result['items'][0]['traversable'])
                self.assertEqual(self.kodi.jsonrpc.call_args.args[0], 'Files.GetDirectory')
                self.assertEqual(self.kodi.jsonrpc.call_args.args[1]['directory'], path)

    def test_traversal_arbitrary_files_and_actions_never_reach_kodi(self):
        blocked = ('special://videoplaylists/../passwords.xml', 'special://videoplaylists/%252e%252e/passwords.xml', 'special://profile/passwords.xml', 'smb://server/movies/', 'file:///tmp/file', '/tmp/file', 'http://host/file', 'addons://sources/audio/', 'library://music/', 'plugin://plugin.video.off/', 'plugin://plugin.video.pov/?mode=play', 'plugin://service.kodi.addonadmin/?mode=family', 'RunScript(script.bingie.widgets)', 'ActivateWindow(Settings)', 'PlayMedia(videodb://movies/titles/1/)', 'ActivateWindow(Videos,special://videoplaylists/,return);RunScript(x)')
        for path in blocked:
            with self.subTest(path=path):
                self.row.update(path=path, action=path)
                result = self.preview()
                self.assertEqual(result['status'], 'unsupported')
                self.assertTrue(result['reason'])
        self.kodi.jsonrpc.assert_not_called()

    def test_bingie_native_plugin_is_a_narrow_observed_allowlist(self):
        for action in ('recent', 'popular'):
            path = 'plugin://script.bingie.widgets/?action=%s&mediatype=media&reload=1' % action
            self.row.update(path='', action=path)
            self.assertEqual(self.preview()['status'], 'ok')
            self.assertEqual(self.kodi.jsonrpc.call_args.args[1]['directory'], path)
        self.kodi.jsonrpc.reset_mock()
        for path in ('plugin://script.bingie.widgets/?action=play&mediatype=media', 'plugin://script.bingie.widgets/?action=recent&mediatype=media&filename=file', 'plugin://script.other/?action=recent&mediatype=media'):
            self.row['action'] = path
            self.assertEqual(self.preview()['status'], 'unsupported')
        self.kodi.jsonrpc.assert_not_called()

    def test_favourites_include_only_safe_video_folders_and_never_execute_actions(self):
        self.row.update(path='', action='ActivateWindow(FavouritesBrowser)')
        favourites = [
            {'title': 'Popular', 'type': 'window', 'window': 'videos', 'windowparameter': self.path, 'thumbnail': 'https://image.tmdb.org/poster.jpg'},
            {'title': 'Playlist', 'type': 'window', 'window': '10025', 'windowparameter': 'special://videoplaylists/'},
            {'title': 'Unsafe script', 'type': 'script', 'path': 'RunScript(x)'},
            {'title': 'Media playback', 'type': 'media', 'path': 'smb://server/movie.mkv'},
            {'title': 'Bad route', 'type': 'window', 'window': 'videos', 'windowparameter': 'plugin://plugin.video.pov/?mode=play'},
            {'title': 'Settings', 'type': 'window', 'window': 'settings', 'windowparameter': self.path},
            {'title': 'Malformed', 'type': 'window', 'window': 'videos', 'windowparameter': {}},
        ]
        self.kodi.jsonrpc.return_value = {'result': {'favourites': favourites}}
        result = self.preview(limit=1)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([item['label'] for item in result['items']], ['Popular'])
        self.assertEqual(result['skipped'], 5)
        self.assertTrue(result['sample']['truncated'])
        self.assertEqual(result['source']['action'], 'ActivateWindow(FavouritesBrowser)')
        self.kodi.jsonrpc.assert_called_once_with('Favourites.GetFavourites', {'properties': ['window', 'windowparameter', 'thumbnail', 'path']})

    def test_rpc_failure_is_diagnostic_without_echoing_remote_error_details(self):
        self.kodi.jsonrpc.return_value = {'error': {'message': 'private remote detail'}}
        result = self.preview()
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('private remote detail', result['reason'])


class RowPreviewEndpointTests(unittest.TestCase):
    def test_authenticated_endpoint_is_available_with_write_mode_disabled(self):
        state = SimpleNamespace(kodi=object(), index=SimpleNamespace(refresh=Mock()), config={'auth_token': 'preview-test-session', 'host': '127.0.0.1', 'write_enabled': False}, log=lambda *_: None)
        http_server = ThreadingHTTPServer(('127.0.0.1', 0), server.make_handler(state))
        thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http_server.server_close)
        self.addCleanup(http_server.shutdown)
        body = {'section_id': 'home', 'row_id': 'saved-1', 'limit': 12}
        with patch.object(server, 'row_preview', return_value={'status': 'ok', 'items': []}) as preview:
            for authorized in (False, True):
                headers = {'Content-Type': 'application/json'}
                if authorized:
                    headers['Authorization'] = 'Bearer preview-test-session'
                connection = http.client.HTTPConnection(*http_server.server_address)
                connection.request('POST', '/api/widgets/row-preview', json.dumps(body), headers)
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200 if authorized else 401)
                connection.close()
                if not authorized:
                    preview.assert_not_called()
                    state.index.refresh.assert_not_called()
                else:
                    self.assertEqual(payload['data']['status'], 'ok')
                    preview.assert_called_once_with(state.kodi, state.index, body)
                    state.index.refresh.assert_called_once()


if __name__ == '__main__':
    unittest.main()
