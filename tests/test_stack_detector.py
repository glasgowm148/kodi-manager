import os
import sys
import json
import sqlite3
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))

from stack_detector import detect_stack


class FakeKodi:
    def get_active_skin(self):
        return {"addon_id": "skin.bingie", "name": "Bingie", "version": "", "path": ""}


class FakeIndex:
    def __init__(self):
        ids = [
            "peripheral.joystick",
            "plugin.program.openwizard",
            "plugin.video.fen",
            "plugin.video.fenlight",
            "plugin.video.imdb.trailers",
            "plugin.video.tmdb.bingie.helper",
            "script.module.autocompletion",
            "script.module.cocoscrapers",
            "script.skinshortcuts",
            "service.autostop",
            "service.kodi.addonadmin",
            "shortcutmanager",
            "skin.bingie",
            "skin.estuary",
        ]
        self.addons = {aid: self._addon(aid) for aid in ids}

    def _addon(self, aid):
        return {
            "addon_id": aid,
            "name": aid,
            "enabled": None,
            "jsonrpc_present": False,
            "installed_folder_present": False,
            "addon_data_present": True,
            "has_user_settings": True,
            "has_settings_schema": False,
            "sources": ["addon_data folder"],
            "detected_from": ["addon_data"],
            "adapter_name": "GenericAdapter",
            "role": "",
        }

    def get(self, aid):
        return self.addons.get(aid)


class StackDetectorTests(unittest.TestCase):
    def test_trakt_dependency_is_not_standalone_addon(self):
        index = FakeIndex()
        index.addons['script.module.trakt'] = index._addon('script.module.trakt')
        stack = detect_stack(FakeKodi(), index)
        self.assertFalse(stack['trakt']['standalone_found'])

    def test_pov_local_trakt_without_standalone(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            pov = index._addon('plugin.video.pov')
            pov.update(name='POV', installed=True, enabled=True, user_settings_path=os.path.join(folder, 'settings.xml'))
            index.addons['plugin.video.pov'] = pov
            with open(pov['user_settings_path'], 'w') as fh:
                fh.write('<settings><setting id="trakt.token">sample-private-token</setting><setting id="trakt_user">sample-user</setting></settings>')
            stack = detect_stack(FakeKodi(), index)
            self.assertFalse(stack['trakt']['standalone_found'])
            self.assertEqual(stack['trakt_integration']['status'], 'configured')
            self.assertFalse(stack['trakt_integration']['verified'])
            self.assertEqual(stack['trakt_integration']['providers'][0]['addon_id'], 'plugin.video.pov')
            self.assertNotIn('sample-private-token', json.dumps(stack['trakt_integration']))

    def test_pov_does_not_require_fenlight_or_cocoscrapers(self):
        index = FakeIndex()
        del index.addons['plugin.video.fenlight']
        del index.addons['plugin.video.fen']
        del index.addons['script.module.cocoscrapers']
        index.addons['plugin.video.pov'] = index._addon('plugin.video.pov')
        index.addons['plugin.program.shortcutmanager'] = index._addon('plugin.program.shortcutmanager')
        stack = detect_stack(FakeKodi(), index)
        self.assertFalse(any('fenlight missing' in warning or 'cocoscrapers missing' in warning or 'Playback add-on not detected' in warning for warning in stack['warnings']))
        self.assertEqual(stack['bingie_build']['shortcutmanager']['addon_id'], 'plugin.program.shortcutmanager')

    def test_fenlight_database_trakt_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            index = FakeIndex()
            index.addons['plugin.video.fenlight']['addon_data_path'] = folder
            os.mkdir(os.path.join(folder, 'databases'))
            con = sqlite3.connect(os.path.join(folder, 'databases', 'settings.db'))
            con.execute('create table settings (setting_id text, setting_value text)')
            con.execute('insert into settings values (?, ?)', ('trakt.token', 'sample-private-token'))
            con.commit()
            con.close()
            stack = detect_stack(FakeKodi(), index)
            self.assertEqual(stack['trakt_integration']['status'], 'configured')
            self.assertEqual(stack['trakt_integration']['providers'][0]['evidence'][0]['source'], 'settings.db')
            self.assertNotIn('sample-private-token', json.dumps(stack['trakt_integration']))

    def test_unknown_skin_is_not_marked_active_or_enabled(self):
        kodi = FakeKodi()
        kodi.get_active_skin = lambda: {}
        stack = detect_stack(kodi, FakeIndex())
        self.assertFalse(stack["skin"]["active"])
        self.assertFalse(stack["skin"]["installed"])
        self.assertIsNone(stack["skin"]["enabled"])

    def test_active_skin_confirms_installation_without_index_entry(self):
        index = FakeIndex()
        del index.addons["skin.bingie"]
        stack = detect_stack(FakeKodi(), index)
        self.assertTrue(stack["skin"]["active"])
        self.assertTrue(stack["skin"]["installed"])
        self.assertTrue(stack["skin"]["enabled"])
        self.assertTrue(stack["skin"]["found"])

    def test_pov_detection_preserves_installed_and_config_states(self):
        for installed, config, enabled in ((True, True, True), (True, False, False), (None, True, None)):
            with self.subTest(installed=installed, config=config, enabled=enabled):
                index = FakeIndex()
                pov = index._addon("plugin.video.pov")
                pov.update(installed=installed, addon_data_present=config, has_user_settings=config, enabled=enabled, name="POV", version="1.0")
                index.addons["plugin.video.pov"] = pov
                stack = detect_stack(FakeKodi(), index)
                self.assertTrue(stack["pov"]["found"])
                self.assertEqual(stack["pov"]["addon_id"], "plugin.video.pov")
                self.assertEqual(stack["pov"]["role"], "pov")
                self.assertEqual(stack["pov"]["installed"], installed)
                self.assertEqual(stack["pov"]["config_present"], config)
                self.assertEqual(stack["pov"]["enabled"], enabled)
                self.assertEqual(stack["pov"]["version"], "1.0")
                self.assertIn("plugin.video.pov", stack["trakt_integration"]["scanned_addons"])

    def test_pov_absent_is_reported_without_matching_other_addons(self):
        index = FakeIndex()
        index.addons["plugin.video.povhelper"] = index._addon("plugin.video.povhelper")
        stack = detect_stack(FakeKodi(), index)
        self.assertFalse(stack["pov"]["found"])
        self.assertFalse(stack["pov"]["installed"])
        self.assertFalse(stack["pov"]["config_present"])
        self.assertEqual(stack["pov"]["role"], "pov")

    def test_big_moco_addon_data_detection(self):
        stack = detect_stack(FakeKodi(), FakeIndex())
        self.assertEqual(stack["skin"]["addon_id"], "skin.bingie")
        self.assertEqual(stack["skin"]["role"], "skin")
        self.assertTrue(stack["skin"]["active"])
        self.assertTrue(stack["skin"]["config_present"])
        self.assertEqual(stack["tmdbhelper"]["addon_id"], "plugin.video.tmdb.bingie.helper")
        self.assertEqual(stack["tmdbhelper"]["role"], "tmdbhelper")
        self.assertEqual(stack["tmdbhelper"]["variant"], "bingie")
        self.assertTrue(stack["tmdbhelper"]["config_present"])
        self.assertEqual(stack["fenlight"]["addon_id"], "plugin.video.fenlight")
        self.assertEqual(stack["fenlight"]["role"], "fenlight")
        self.assertEqual(stack["fen"]["addon_id"], "plugin.video.fen")
        self.assertEqual(stack["fen"]["role"], "fen")
        self.assertEqual(stack["cocoscrapers"]["addon_id"], "script.module.cocoscrapers")
        self.assertEqual(stack["cocoscrapers"]["role"], "cocoscrapers")
        self.assertFalse(stack["trakt"]["standalone_found"])
        self.assertEqual(stack["trakt"]["role"], "trakt_standalone")
        self.assertIn("Trakt standalone add-on not found", stack["trakt"]["message"])
        self.assertEqual(stack["related_skin_addons"]["script.skinshortcuts"]["role"], "skin_dependency")
        self.assertEqual(stack["related_skin_addons"]["shortcutmanager"]["role"], "skin_dependency")
        self.assertEqual(stack["related_skin_addons"]["plugin.program.openwizard"]["role"], "maintenance")
        self.assertFalse(any("tmdbhelper not detected" in w for w in stack["warnings"]))
        self.assertFalse(any("fenlight not detected" in w for w in stack["warnings"]))
        self.assertFalse(any("cocoscrapers not detected" in w for w in stack["warnings"]))


if __name__ == "__main__":
    unittest.main()
