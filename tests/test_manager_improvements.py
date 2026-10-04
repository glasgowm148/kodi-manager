import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))

from server import health_summary, playback_test


class FakeKodi:
    installer_seed = {}

    def get_active_skin(self):
        return {"addon_id": "skin.bingie", "name": "Bingie", "version": "1", "path": ""}

    def get_kodi_version(self):
        return "21.2"

    def get_log_lines(self, n=200):
        return ["INFO ok", "WARNING sample warning", "ERROR sample error"]

    def list_addons(self):
        return []

    def get_addon_details(self, addon_id):
        return {}

    def jsonrpc(self, method, params=None):
        if method == "Player.GetActivePlayers":
            return {"result": []}
        return {"result": {}}


class FakeIndex:
    probe = {"addon_data_probe": {"selected_path": "/profile/addon_data"}, "addons_probe": {"selected_path": "/home/addons"}}

    def __init__(self):
        ids = ["skin.bingie", "plugin.video.tmdb.bingie.helper", "plugin.video.fenlight", "plugin.video.fen", "script.module.cocoscrapers"]
        self.addons = {aid: self._addon(aid) for aid in ids}

    def _addon(self, aid):
        return {"addon_id": aid, "name": aid, "installed": True, "config_present": True, "addon_data_present": True, "enabled": True, "detected_from": ["test"], "sources": ["test"], "addon_data_path": "", "settings_schema_path": "", "user_settings_path": ""}

    def refresh(self):
        return self.addons

    def list(self):
        return list(self.addons.values())

    def get(self, aid):
        return self.addons.get(aid)


class ManagerImprovementTests(unittest.TestCase):
    def test_health_summary_reports_stats_and_log_problems(self):
        h = health_summary(FakeKodi(), FakeIndex(), {"write_enabled": True, "installer_seed": {}})
        self.assertIn(h["status"], ("warning", "error"))
        self.assertEqual(h["stats"]["addons"], 5)
        self.assertEqual(h["stats"]["stack_detected"], 5)
        self.assertEqual(h["stats"]["kodi_log_errors"], 1)

    def test_playback_test_is_safe_dry_run(self):
        r = playback_test(FakeKodi(), FakeIndex(), {"target_player_addon_id": "plugin.video.fenlight", "plugin_url": "plugin://plugin.video.fenlight/"})
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["target_player_addon_id"], "plugin.video.fenlight")
        self.assertTrue(any(step["step"] == "Plugin URL format" and step["ok"] for step in r["steps"]))

    def test_health_summary_counts_pov(self):
        index = FakeIndex()
        index.addons["plugin.video.pov"] = index._addon("plugin.video.pov")
        h = health_summary(FakeKodi(), index, {"write_enabled": True, "installer_seed": {}})
        self.assertEqual(h["stats"]["stack_detected"], 6)
        self.assertEqual(h["stats"]["addons"], 6)


if __name__ == "__main__":
    unittest.main()
