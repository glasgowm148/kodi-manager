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

    def test_integer_settings_take_whole_finite_numbers_only(self):
        s = {"id": "limit", "label": "Limit", "type": "integer"}
        self.assertEqual(coerce_value(s, 12), "12")
        self.assertEqual(coerce_value(s, " 7 "), "7")
        self.assertEqual(coerce_value(s, "5.0"), "5")
        for bad in ("1.5", "nan", "inf", "-Infinity", True, "", "ten"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                coerce_value(s, bad)

    def test_number_settings_reject_nan_and_infinity(self):
        for typ in ("number", "slider"):
            s = {"id": "volume", "label": "Volume", "type": typ}
            self.assertEqual(coerce_value(s, "0.5"), "0.5")
            for bad in ("nan", "inf", "1e999", "1_0", False):
                with self.assertRaises(ValueError, msg=repr(bad)):
                    coerce_value(s, bad)

    def test_fen_light_database_numbers_are_checked_like_settings_xml(self):
        from fenlight_db import coerce_db_value
        self.assertEqual(coerce_db_value("number", " 0.5 "), "0.5")
        self.assertEqual(coerce_db_value("integer", "5.0"), "5")
        for typ in ("number", "integer"):
            for bad in ("nan", "inf", "-Infinity", "1e999", "1_0", True, "", "ten"):
                with self.assertRaises(ValueError, msg="%s %r" % (typ, bad)):
                    coerce_db_value(typ, bad)
        with self.assertRaises(ValueError):
            coerce_db_value("integer", "1.5")

    def test_missing_or_structured_values_are_not_stored_as_python_text(self):
        for typ in ("text", "string", "password", "integer", "enum"):
            s = {"id": "x", "label": "X", "type": typ}
            for bad in (None, {"a": 1}, ["a"]):
                with self.assertRaises(ValueError, msg="%s %r" % (typ, bad)):
                    coerce_value(s, bad)


if __name__ == "__main__":
    unittest.main()
