import os
import sys
import json
import tempfile
import unittest
from xml.sax.saxutils import escape

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))

from pipeline import build_pipeline, build_accounts, _setting_obj, switch_player


class FakeKodi:
    def get_active_skin(self):
        return {"addon_id": "skin.bingie", "name": "Bingie", "version": "2.0.2", "path": ""}

    def get_kodi_version(self):
        return "21.2"


class FakeIndex:
    def __init__(self):
        ids = [
            "skin.bingie",
            "plugin.video.tmdb.bingie.helper",
            "plugin.video.fenlight",
            "plugin.video.fen",
            "script.module.cocoscrapers",
            "script.skinshortcuts",
            "shortcutmanager",
            "plugin.program.openwizard",
        ]
        self.addons = {aid: self._addon(aid) for aid in ids}

    def refresh(self):
        return self.addons

    def _addon(self, aid):
        return {
            "addon_id": aid,
            "name": aid,
            "version": "1.0",
            "installed": True,
            "config_present": True,
            "addon_data_present": True,
            "detected_from": ["addon_data folder"],
            "sources": ["addon_data folder"],
            "addon_data_path": "",
            "settings_schema_path": "",
            "user_settings_path": "",
        }

    def get(self, aid):
        return self.addons.get(aid)


class PipelineTests(unittest.TestCase):
    def test_pipeline_classification_fixture(self):
        pipe = build_pipeline(FakeKodi(), FakeIndex())
        ids = {n["id"]: n.get("addon_id") for n in pipe["nodes"]}
        self.assertEqual(ids["skin"], "skin.bingie")
        self.assertEqual(ids["helper"], "plugin.video.tmdb.bingie.helper")
        self.assertEqual(ids["player"], "")
        self.assertEqual(ids["scraper"], "")
        self.assertEqual(pipe["routing"]["movie_player"]["addon_id"], "")
        self.assertEqual(pipe["summary"]["primary_player"]["selection"], "unknown")
        self.assertTrue(any(e["from"] == "skin" and e["to"] == "helper" for e in pipe["edges"]))
        self.assertTrue(any(e["from"] == "helper" and e["to"] == "player" for e in pipe["edges"]))
        self.assertEqual(pipe["summary"]["accounts"]["torbox"]["status"], "not found")

    def _settings(self, folder, name, values):
        path = os.path.join(folder, name)
        with open(path, "w") as fh:
            fh.write('<settings>' + ''.join('<setting id="%s">%s</setting>' % (sid, escape(value)) for sid, value in values.items()) + '</settings>')
        return path

    def test_selected_pov_route_overrides_other_installed_players(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            pov = index._addon("plugin.video.pov")
            pov.update(enabled=True, path=folder, name="POV")
            index.addons[pov["addon_id"]] = pov
            helper = index.addons["plugin.video.tmdb.bingie.helper"]
            helper.update(addon_data_path=folder, user_settings_path=self._settings(folder, 'helper.xml', {
                'default_player_movies': 'pov.json play_movie', 'default_player_episodes': 'pov.json play_episode',
            }))
            os.mkdir(os.path.join(folder, 'players'))
            for name, addon in (('pov.json', 'plugin.video.pov'), ('fenlight.json', 'plugin.video.fenlight')):
                with open(os.path.join(folder, 'players', name), 'w') as fh:
                    json.dump({'plugin': addon, 'play_movie': 'plugin://%s/' % addon}, fh)
            os.makedirs(os.path.join(folder, 'resources', 'lib', 'magneto'))
            os.mkdir(os.path.join(folder, 'resources', 'lib', 'modules'))
            with open(os.path.join(folder, 'resources', 'lib', 'modules', 'sources.py'), 'w') as fh:
                fh.write('from magneto import sources as magneto_sources')
            pipe = build_pipeline(FakeKodi(), index)
            self.assertEqual(pipe['summary']['primary_player']['addon_id'], 'plugin.video.pov')
            self.assertEqual(pipe['routing']['movie_player']['source'], 'selected_player_file')
            self.assertEqual(pipe['summary']['scraper_module']['name'], 'POV bundled Magneto')
            self.assertTrue(pipe['summary']['scraper_module']['used'])
            self.assertEqual(pipe['summary']['available_scraper_modules'][0]['addon_id'], 'script.module.cocoscrapers')

    def test_installed_player_files_do_not_prove_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            index.addons['plugin.video.tmdb.bingie.helper']['addon_data_path'] = folder
            os.mkdir(os.path.join(folder, 'players'))
            with open(os.path.join(folder, 'players', 'pov.json'), 'w') as fh:
                json.dump({'plugin': 'plugin.video.pov'}, fh)
            pipe = build_pipeline(FakeKodi(), index)
            self.assertEqual(pipe['routing']['movie_player']['confidence'], 'unknown')
            self.assertEqual(pipe['summary']['primary_player']['selection'], 'unknown')

    def test_integrated_trakt_uses_credentials_and_emits_no_values(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            pov = index._addon('plugin.video.pov')
            index.addons['plugin.video.pov'] = pov
            pov['user_settings_path'] = self._settings(folder, 'pov.xml', {'trakt.token': 'sample-private-token', 'trakt_user': 'sample-user'})
            pipe = build_pipeline(FakeKodi(), index)
            trakt = pipe['summary']['accounts']['trakt']
            self.assertEqual(trakt['status'], 'configured')
            self.assertFalse(trakt['verified'])
            self.assertEqual(trakt['providers'][0]['addon_id'], 'plugin.video.pov')
            self.assertNotIn('sample-private-token', json.dumps(trakt))
            self.assertNotIn('Standalone Trakt missing; integration may still live inside add-ons.', pipe['summary']['health']['warnings'])

    def test_false_defaults_and_client_credentials_do_not_link_accounts(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            pov = index._addon('plugin.video.pov')
            index.addons['plugin.video.pov'] = pov
            pov['user_settings_path'] = self._settings(folder, 'pov.xml', {
                'trakt.client_id': 'app-client', 'trakt.client_secret': 'app-secret', 'trakt_indicators_active': 'true',
                'tb.enabled': 'false', 'tb.token': '0', 'trakt.token': 'false',
            })
            accounts = build_accounts(FakeKodi(), index)
            self.assertEqual(accounts['summary']['trakt']['status'], 'unknown')
            self.assertEqual(accounts['summary']['torbox']['status'], 'unknown')
            self.assertFalse(any(s['configured'] for g in accounts['groups'] for s in g['settings'] if s['id'] in ('tb.enabled', 'tb.token', 'trakt.token')))

    def test_direct_helper_setting_and_declared_scraper_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            helper = index.addons['plugin.video.tmdb.bingie.helper']
            helper['user_settings_path'] = self._settings(folder, 'helper.xml', {'default_player_movies': 'plugin.video.fen'})
            index.addons['plugin.video.fen']['path'] = folder
            with open(os.path.join(folder, 'addon.xml'), 'w') as fh:
                fh.write('<addon><requires><import addon="script.module.cocoscrapers"/></requires></addon>')
            pipe = build_pipeline(FakeKodi(), index)
            self.assertEqual(pipe['summary']['primary_player']['addon_id'], 'plugin.video.fen')
            self.assertEqual(pipe['summary']['scraper_module']['relationship'], 'declared dependency')
            self.assertEqual(pipe['summary']['scraper_module']['addon_id'], 'script.module.cocoscrapers')

    def test_local_secret_visibility(self):
        setting = _setting_obj("plugin.video.fenlight", {"id": "torbox.api_key", "label": "TorBox API key", "type": "text", "value": "secret", "editable": True})
        self.assertFalse(setting["masked"])
        self.assertEqual(setting["value"], "secret")
        self.assertTrue(setting["editable"])

    def test_safe_bool_editable(self):
        setting = _setting_obj("plugin.video.fenlight", {"id": "autoplay.enabled", "label": "Autoplay", "type": "boolean", "value": "true", "editable": True})
        self.assertFalse(setting["masked"])
        self.assertTrue(setting["editable"])

    def test_action_rejected_for_edit_ui(self):
        setting = _setting_obj("plugin.video.fenlight", {"id": "show_dialog", "label": "Show dialog", "type": "action", "value": "0", "editable": False})
        self.assertFalse(setting["editable"])
        self.assertEqual(setting["risk"], "unsupported")

    def test_switch_player_refuses_missing_pov(self):
        with self.assertRaises(ValueError):
            switch_player(FakeKodi(), FakeIndex(), "plugin.video.pov", write_enabled=True)


if __name__ == "__main__":
    unittest.main()
