import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import service
from kodi_api import KodiAPI


class FakeAddon:
    def __init__(self, write_enabled):
        self.settings = {"auth_token": "test-existing-token", "write_enabled": write_enabled}
        self.writes = []

    def getSetting(self, key):
        return self.settings.get(key, "")

    def setSetting(self, key, value):
        self.writes.append((key, value))
        self.settings[key] = value


class ServiceConfigTests(unittest.TestCase):
    def test_explicit_write_setting_overrides_legacy_installer_seed(self):
        for current, legacy, expected in (("false", True, False), ("true", False, True)):
            with self.subTest(current=current), tempfile.TemporaryDirectory() as folder:
                with open(Path(folder) / "installer_seed.json", "w") as handle:
                    json.dump({"write_enabled": legacy}, handle)
                addon = FakeAddon(current)
                with patch.object(service, "translate", return_value=folder):
                    config = service.load_config(addon)
                self.assertIs(config["write_enabled"], expected)
                self.assertFalse(any(key == "write_enabled" for key, _ in addon.writes))
                self.assertEqual(addon.settings["write_enabled"], current)

    def test_rpc_addon_properties_preserve_path_and_dependencies_without_invalid_type(self):
        kodi = KodiAPI()
        requests = []
        def rpc(method, params):
            requests.append((method, params))
            self.assertNotIn("type", params["properties"])
            self.assertIn("path", params["properties"])
            self.assertIn("dependencies", params["properties"])
            addon = {"addonid": "plugin.video.pov", "name": "POV", "enabled": False, "path": "/addons/pov", "dependencies": [{"addonid": "xbmc.python", "version": "3.0.0"}], "type": "xbmc.python.pluginsource"}
            return {"result": {"addons": [addon]}} if method == "Addons.GetAddons" else {"result": {"addon": addon}}
        with patch.object(kodi, "jsonrpc", side_effect=rpc), patch("kodi_api.translate", side_effect=lambda path: path):
            listed = kodi.list_addons()
            details = kodi.get_addon_details("plugin.video.pov")
        self.assertEqual([method for method, _ in requests], ["Addons.GetAddons", "Addons.GetAddonDetails"])
        for addon in (listed[0], details):
            self.assertEqual(addon["addon_id"], "plugin.video.pov")
            self.assertFalse(addon["enabled"])
            self.assertEqual(addon["path"], "/addons/pov")
            self.assertEqual(addon["type"], "xbmc.python.pluginsource")
            self.assertEqual(addon["dependencies"][0]["addonid"], "xbmc.python")


if __name__ == "__main__":
    unittest.main()
