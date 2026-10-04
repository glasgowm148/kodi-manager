import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))

from settings_schema import parse_schema, flatten_settings


SAMPLES = os.path.join(os.path.dirname(__file__), "sample_settings")


class ParserTests(unittest.TestCase):
    def parse_inline(self, schema, user_settings=None):
        with tempfile.TemporaryDirectory() as folder:
            schema_path = os.path.join(folder, "schema.xml")
            with open(schema_path, "w") as handle:
                handle.write(schema)
            user_path = None
            if user_settings is not None:
                user_path = os.path.join(folder, "settings.xml")
                with open(user_path, "w") as handle:
                    handle.write(user_settings)
            return parse_schema(schema_path, SAMPLES, user_path)

    def test_parse_merge_labels_and_groups(self):
        parsed = parse_schema(os.path.join(SAMPLES, "tmdbhelper_settings.xml"), SAMPLES, os.path.join(SAMPLES, "settings.xml"))
        self.assertEqual(parsed["groups"][0]["label"], "General")
        settings = flatten_settings(parsed)
        self.assertEqual(settings["enable_metadata"]["value"], "false")
        self.assertEqual(settings["username"]["label"], "User name")
        self.assertEqual(settings["max_items"]["value"], "50")
        self.assertEqual(settings["view_mode"]["options"][1]["value"], "poster")

    def test_mask_token_like_settings(self):
        parsed = parse_schema(os.path.join(SAMPLES, "tmdbhelper_settings.xml"), SAMPLES, os.path.join(SAMPLES, "settings.xml"))
        setting = flatten_settings(parsed)["api_key"]
        self.assertTrue(setting["masked"])
        self.assertEqual(setting["value"], "••••••••")
        self.assertFalse(setting["editable"])

    def test_missing_schema_graceful(self):
        parsed = parse_schema(os.path.join(SAMPLES, "missing.xml"), SAMPLES, None)
        self.assertEqual(parsed["groups"], [])
        self.assertTrue(parsed["warnings"])

    def test_missing_user_settings_uses_defaults(self):
        parsed = parse_schema(os.path.join(SAMPLES, "tmdbhelper_settings.xml"), SAMPLES, None)
        self.assertEqual(flatten_settings(parsed)["enable_metadata"]["value"], "true")

    def test_modern_nested_default_options_and_categories(self):
        parsed = self.parse_inline('''<settings version="1"><section id="main"><category id="playback" label="Playback"><group id="routing">
            <setting id="player" label="Player" type="string"><default>pov</default><constraints><options><option label="POV">pov</option><option label="Fen">fen</option></options></constraints></setting>
            <setting id="enabled" type="boolean"><default>false</default></setting>
            </group></category></section></settings>''')
        self.assertEqual(parsed["groups"][0]["label"], "Playback")
        settings = flatten_settings(parsed)
        self.assertEqual(settings["player"]["default"], "pov")
        self.assertEqual(settings["player"]["options"], [{"value": "pov", "label": "POV"}, {"value": "fen", "label": "Fen"}])
        self.assertEqual(settings["player"]["value_source"], "default")
        self.assertTrue(settings["player"]["is_default"])
        self.assertEqual(settings["enabled"]["value"], "false")
        self.assertTrue(settings["enabled"]["default_known"])

    def test_missing_boolean_default_remains_unknown(self):
        parsed = self.parse_inline('<settings><setting id="unknown" type="boolean"/><setting id="off" type="boolean" default="false"/></settings>')
        settings = flatten_settings(parsed)
        self.assertEqual(settings["unknown"]["value"], "")
        self.assertFalse(settings["unknown"]["default_known"])
        self.assertEqual(settings["unknown"]["value_source"], "unknown")
        self.assertIsNone(settings["unknown"]["is_default"])
        self.assertEqual(settings["off"]["value"], "false")
        self.assertEqual(settings["off"]["value_source"], "default")
        self.assertTrue(settings["off"]["is_default"])

    def test_saved_false_keeps_saved_provenance_without_implying_enabled(self):
        parsed = self.parse_inline('<settings><setting id="enabled" type="boolean" default="true"/><setting id="off" type="boolean" default="false"/></settings>', '<settings><setting id="enabled">false</setting><setting id="off" default="true">false</setting></settings>')
        settings = flatten_settings(parsed)
        self.assertEqual(settings["enabled"]["value"], "false")
        self.assertEqual(settings["enabled"]["value_source"], "saved")
        self.assertFalse(settings["enabled"]["is_default"])
        self.assertTrue(settings["off"]["is_default"])

    def test_numeric_equivalence_does_not_hide_case_sensitive_text_changes(self):
        parsed = self.parse_inline('<settings><setting id="limit" type="number" default="1"/><setting id="label" type="string" default="POV"/></settings>', '<settings><setting id="limit" value="1.00"/><setting id="label" value="pov"/></settings>')
        settings = flatten_settings(parsed)
        self.assertTrue(settings["limit"]["is_default"])
        self.assertFalse(settings["label"]["is_default"])
        self.assertEqual(settings["limit"]["value_source"], "saved")

    def test_empty_nested_default_is_known_but_missing_default_is_not(self):
        parsed = self.parse_inline('<settings><setting id="empty" type="string"><default/></setting><setting id="missing" type="string"/></settings>')
        settings = flatten_settings(parsed)
        self.assertTrue(settings["empty"]["default_known"])
        self.assertTrue(settings["empty"]["is_default"])
        self.assertFalse(settings["missing"]["default_known"])
        self.assertIsNone(settings["missing"]["is_default"])


if __name__ == "__main__":
    unittest.main()
