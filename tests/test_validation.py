import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src", "kodi_manager"))

from validation import coerce_value, is_secret_like, setting_editable


class ValidationTests(unittest.TestCase):
    def test_secret_detection(self):
        self.assertTrue(is_secret_like("oauth_token", "Token"))
        self.assertTrue(is_secret_like("realdebrid.key", "Key"))

    def test_reject_secret_edit(self):
        self.assertFalse(setting_editable({"id": "api_key", "label": "API key", "type": "text"}))

    def test_reject_action_file_folder(self):
        for typ in ("action", "file", "folder"):
            self.assertFalse(setting_editable({"id": "x", "label": "X", "type": typ}))

    def test_allow_safe_bool_edit(self):
        s = {"id": "enabled", "label": "Enabled", "type": "bool"}
        self.assertTrue(setting_editable(s))
        self.assertEqual(coerce_value(s, True), "true")

    def test_validate_select(self):
        s = {"id": "mode", "label": "Mode", "type": "enum", "options": [{"value": "a"}, {"value": "b"}]}
        self.assertEqual(coerce_value(s, "b"), "b")
        with self.assertRaises(ValueError):
            coerce_value(s, "c")


if __name__ == "__main__":
    unittest.main()
