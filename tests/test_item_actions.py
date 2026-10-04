from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/kodi_manager'))
from item_actions import item_actions


class WrappedItemActionsTests(unittest.TestCase):
    def test_watchlist_removal_is_first_and_uses_series_id_for_episode(self):
        item = {'file': 'plugin://plugin.video.pov/?mode=play_media&mediatype=episode&tmdb_id=79744&season=2&episode=4'}
        props, actions = item_actions(item, 'episode', 'plugin://plugin.video.pov/?mode=build_tvshow_list&action=trakt_watchlist')
        self.assertEqual(props, {'km_tmdb_id': '79744', 'km_mediatype': 'tvshow'})
        self.assertEqual(actions[0][0], 'Remove from watchlist')
        self.assertEqual(actions[1][0], 'Browse show')
        self.assertIn('action=remove', actions[0][1])

    def test_movie_discovery_adds_to_same_cloud_list_without_show_action(self):
        props, actions = item_actions({'file': 'plugin://plugin.video.pov/?mode=play_media&tmdb_id=345'}, 'movie', 'plugin://plugin.video.pov/?action=trending')
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0][0], 'Add to watchlist')

    def test_missing_or_foreign_ids_never_create_an_action(self):
        for url in ['plugin://plugin.video.pov/?tmdb_id=None', 'plugin://other.addon/?tmdb_id=345']:
            self.assertEqual(item_actions({'file': url}, 'movie', ''), ({}, []))

    def test_unknown_jsonrpc_show_type_keeps_metadata_and_removal_action(self):
        from widget_plugin import render_directory
        li, tag, plugin = Mock(), Mock(), Mock()
        li.getVideoInfoTag.return_value = tag
        gui = SimpleNamespace(ListItem=Mock(return_value=li))
        render_directory(gui, plugin, 1, {
            'source': 'plugin://plugin.video.pov/?mode=build_tvshow_list&action=trakt_watchlist',
            'max_rating': '12A', 'family_only': False,
            'files': [{'type': 'unknown', 'filetype': 'directory', 'label': 'Example',
                       'file': 'plugin://plugin.video.pov/?mode=build_season_list&tmdb_id=123'}]})
        tag.setMediaType.assert_called_once_with('tvshow')
        self.assertEqual(li.addContextMenuItems.call_args.args[0][0][0], 'Remove from watchlist')
        li.setProperty.assert_any_call('km_tmdb_id', '123')


    def test_focus_waits_for_rendered_list_and_accounts_for_parent_folder(self):
        import sys
        from unittest.mock import patch
        from urllib.parse import urlencode
        from widget_plugin import focus_episode
        source = 'plugin://plugin.video.pov/?mode=build_episode_list&tmdb_id=82728&season=1&km_focus_episode=23'
        path = 'plugin://service.kodi.addonadmin/?' + urlencode({'mode':'family','source':source})
        control, window = Mock(), Mock()
        control.size.side_effect = [0, 24]
        control.getListItem.side_effect = lambda i: SimpleNamespace(getVideoInfoTag=lambda: SimpleNamespace(getEpisode=lambda:i, getSeason=lambda:1))
        window.getControl.return_value = control
        reads = iter(['0','24'])
        def label(key):
            if key == 'Container.FolderPath': return path
            if key == 'Container(525).NumAllItems': return next(reads)
            import re
            match = re.search(r'Absolute\((\d+)\)', key)
            return str(int(match.group(1))) if key.endswith('.Episode') else '1'
        xbmc = SimpleNamespace(getInfoLabel=label, getCondVisibility=lambda cond:cond=='Window.IsActive(videos)', sleep=Mock())
        with patch.dict(sys.modules, {'xbmc':xbmc,'xbmcgui':SimpleNamespace(Window=lambda _:window)}):
            focus_episode({'source':source,'files':[{'episode':i} for i in range(1,24)]})
        control.selectItem.assert_called_once_with(23)
        xbmc.sleep.assert_called_once_with(100)
