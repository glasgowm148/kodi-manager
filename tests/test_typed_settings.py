"""Kodi 20+ typed boolean settings: read via getSettings().getBool, text form as fallback."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import kodi_api  # noqa: E402
import service  # noqa: E402


class TypedSettings:
    def __init__(self, values, fail=()):
        self.values, self.fail, self.written = values, set(fail), {}

    def getBool(self, key):
        if key in self.fail:
            raise TypeError("not a bool setting")
        return self.values[key]

    def setBool(self, key, value):
        self.written[key] = value


class TypedAddon:
    """Text form disagrees with the typed value, as on Kodi 22 for unsaved bools."""
    def __init__(self, typed, text=None, fail=()):
        self.typed = TypedSettings(typed, fail)
        self.text = dict({"auth_token": "synthetic-token"}, **(text or {}))
        self.text_writes = []

    def getSettings(self):
        return self.typed

    def getSetting(self, key):
        return self.text.get(key, "")

    def setSetting(self, key, value):
        self.text_writes.append((key, value))
        self.text[key] = value


class LoadConfigTypedBoolTests(unittest.TestCase):
    def load(self, addon):
        with tempfile.TemporaryDirectory() as folder, patch.object(service, "translate", return_value=folder):
            return service.load_config(addon)

    def test_bools_come_from_the_typed_api(self):
        typed = {key: True for key in service.BOOL_KEYS}
        config = self.load(TypedAddon(typed, text={key: "false" for key in service.BOOL_KEYS}))
        for key in ("enabled", "shield_exit_workaround", "allow_lan", "write_enabled", "widget_cache_auto",
                    "delete_installer_result_after_first_login"):
            self.assertIs(config[key], True, key)

    def test_text_form_is_the_fallback_when_the_typed_read_fails(self):
        typed = {key: False for key in service.BOOL_KEYS}
        config = self.load(TypedAddon(typed, text={"write_enabled": "true"}, fail={"write_enabled"}))
        self.assertIs(config["write_enabled"], True)
        self.assertIs(config["allow_lan"], False)

    def test_non_bool_settings_keep_the_text_form(self):
        config = self.load(TypedAddon({key: False for key in service.BOOL_KEYS}, text={"port": "9000"}))
        self.assertEqual(config["port"], 9000)


class KodiApiWriteModeTests(unittest.TestCase):
    def test_write_mode_is_read_and_written_as_a_bool(self):
        addon = TypedAddon({"write_enabled": True}, text={"write_enabled": ""})
        fake = type("xbmcaddon", (), {"Addon": staticmethod(lambda addon_id: addon)})
        with patch.object(kodi_api, "xbmcaddon", fake):
            api = kodi_api.KodiAPI()
            self.assertEqual(api.get_addon_setting("service.kodi.addonadmin", "write_enabled"), "true")
            api.set_addon_setting("service.kodi.addonadmin", "write_enabled", "false")
            self.assertEqual(addon.typed.written, {"write_enabled": False})
            self.assertEqual(addon.text_writes, [])
            # Other settings and other add-ons keep the text API.
            api.set_addon_setting("service.kodi.addonadmin", "port", "8765")
            api.set_addon_setting("plugin.video.example", "write_enabled", "true")
            self.assertEqual(addon.text_writes, [("port", "8765"), ("write_enabled", "true")])
            self.assertEqual(api.get_addon_setting("plugin.video.example", "write_enabled"), "true")


if __name__ == "__main__":
    unittest.main()
